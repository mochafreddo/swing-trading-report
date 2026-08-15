import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import { quotePostgrestValue } from "@/lib/postgrest-filter";
import { parseReportStorageKey } from "@/lib/report-key";
import {
  isReportType,
  type DecisionBoardRunKind,
  type ReportType,
} from "@/lib/types";
import {
  buildAuthHeaders,
  fetchSupabase,
  parseError,
  SupabaseApiError,
} from "@/lib/supabase/admin-client";

const REPORT_INDEX_SELECT =
  "bucket_id,report_key,report_type,report_date,duplicate_index,generated_at,summary,tickers,tickers_hydrated,run_kind,run_id,idempotency_key,decision_created_at";
const LEGACY_REPORT_INDEX_ORDER =
  "report_date.desc,duplicate_index.desc,report_key.desc,bucket_id.desc";
const DECISION_BOARD_REPORT_INDEX_ORDER =
  "decision_created_at.desc,run_id.desc,report_key.desc,bucket_id.desc";
const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const IDEMPOTENCY_KEY_PATTERN = /^sha256:[0-9a-f]{64}$/;
const DECISION_BOARD_TICKER_PATTERN = /^[A-Z][A-Z0-9]*(?:[./-][A-Z0-9]+)*$/;
const TIMESTAMP_WITH_OFFSET_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const LATEST_DECISION_BOARD_PAGE_SIZE = 25;
const LATEST_DECISION_BOARD_MAX_PAGES = 100;

export interface ReportIndexRow {
  bucket_id: string;
  report_key: string;
  report_type: ReportType;
  report_date: string;
  duplicate_index: number;
  generated_at: string | null;
  summary: Record<string, unknown> | null;
  tickers: string[];
  tickers_hydrated: boolean;
  run_kind?: DecisionBoardRunKind | null;
  run_id?: string | null;
  idempotency_key?: string | null;
  decision_created_at?: string | null;
}

export interface FetchReportIndexPageOptions {
  type?: ReportType | "all";
  limit?: number;
  cursor?: ReportIndexCursor;
  includeTotal?: boolean;
  lookahead?: boolean;
  runKind?: DecisionBoardRunKind;
}

export interface ReportIndexCursor {
  report_date: string;
  duplicate_index: number;
  report_key: string;
  bucket_id: string;
  decision_created_at?: string;
  run_id?: string;
}

export interface FetchReportIndexPageResult {
  items: ReportIndexRow[];
  total: number;
  fetchedCount: number;
  hasMore: boolean;
  nextCursor: ReportIndexCursor | null;
}

export interface ReportIndexUpsertInput {
  bucketId?: string;
  reportKey: string;
  reportType: ReportType;
  reportDate: string;
  duplicateIndex: number;
  generatedAt?: string;
  summary?: Record<string, unknown>;
  tickers?: string[];
  tickersHydrated?: boolean;
}

function encodeStorageKey(key: string): string {
  return key
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function parseContentRangeTotal(headerValue: string | null): number | null {
  if (!headerValue) {
    return null;
  }
  const totalValue = headerValue.split("/")[1];
  if (!totalValue || totalValue === "*") {
    return null;
  }
  const parsed = Number.parseInt(totalValue, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function trimmedString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function nonNegativeNumber(
  value: unknown,
  options: { integer?: boolean } = {},
): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    return null;
  }
  if (options.integer === true && !Number.isInteger(value)) {
    return null;
  }
  return value;
}

function normalizedStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((entry): entry is string => typeof entry === "string")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function parseReportIndexCursor(payload: unknown): ReportIndexCursor | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const raw = payload as {
    report_date?: unknown;
    duplicate_index?: unknown;
    report_key?: unknown;
    bucket_id?: unknown;
  };

  const reportDate = trimmedString(raw.report_date);
  const duplicateIndex = nonNegativeNumber(raw.duplicate_index, {
    integer: true,
  });
  const reportKey = trimmedString(raw.report_key);
  const bucketId = trimmedString(raw.bucket_id) || "reports";

  if (!reportDate || duplicateIndex === null || !reportKey) {
    return null;
  }

  return {
    report_date: reportDate,
    duplicate_index: duplicateIndex,
    report_key: reportKey,
    bucket_id: bucketId,
  };
}

function parseDecisionBoardIndexCursor(
  payload: unknown,
): ReportIndexCursor | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const raw = payload as {
    report_date?: unknown;
    duplicate_index?: unknown;
    report_key?: unknown;
    bucket_id?: unknown;
    decision_created_at?: unknown;
    run_id?: unknown;
  };
  const reportDate = trimmedString(raw.report_date);
  const duplicateIndex = nonNegativeNumber(raw.duplicate_index, {
    integer: true,
  });
  const reportKey = trimmedString(raw.report_key);
  const bucketId = trimmedString(raw.bucket_id);
  const decisionCreatedAt = nullableIdentityString(raw.decision_created_at);
  const runId = nullableIdentityString(raw.run_id);
  if (
    typeof raw.report_date !== "string" ||
    raw.report_date !== reportDate ||
    duplicateIndex === null ||
    typeof raw.report_key !== "string" ||
    raw.report_key !== reportKey ||
    !reportKey ||
    typeof raw.bucket_id !== "string" ||
    raw.bucket_id !== bucketId ||
    !bucketId ||
    decisionCreatedAt == null ||
    parseOffsetTimestamp(decisionCreatedAt) === null ||
    runId == null ||
    !RUN_ID_PATTERN.test(runId)
  ) {
    return null;
  }
  return {
    report_date: reportDate,
    duplicate_index: duplicateIndex,
    report_key: reportKey,
    bucket_id: bucketId,
    decision_created_at: decisionCreatedAt,
    run_id: runId,
  };
}

function buildReportIndexKeysetFilter(cursor: ReportIndexCursor): string {
  const reportDate = quotePostgrestValue(cursor.report_date);
  const reportKey = quotePostgrestValue(cursor.report_key);
  const bucketId = quotePostgrestValue(cursor.bucket_id);
  return `(report_date.lt.${reportDate},and(report_date.eq.${reportDate},duplicate_index.lt.${cursor.duplicate_index}),and(report_date.eq.${reportDate},duplicate_index.eq.${cursor.duplicate_index},report_key.lt.${reportKey}),and(report_date.eq.${reportDate},duplicate_index.eq.${cursor.duplicate_index},report_key.eq.${reportKey},bucket_id.lt.${bucketId}))`;
}

function buildDecisionBoardKeysetFilter(cursor: ReportIndexCursor): string {
  if (!cursor.decision_created_at || !cursor.run_id) {
    throw new TypeError(
      "Decision Board cursor requires created time and run ID",
    );
  }
  const createdAt = quotePostgrestValue(cursor.decision_created_at);
  const runId = quotePostgrestValue(cursor.run_id);
  const reportKey = quotePostgrestValue(cursor.report_key);
  const bucketId = quotePostgrestValue(cursor.bucket_id);
  return `(decision_created_at.lt.${createdAt},and(decision_created_at.eq.${createdAt},run_id.lt.${runId}),and(decision_created_at.eq.${createdAt},run_id.eq.${runId},report_key.lt.${reportKey}),and(decision_created_at.eq.${createdAt},run_id.eq.${runId},report_key.eq.${reportKey},bucket_id.lt.${bucketId}))`;
}

function parseOffsetTimestamp(value: unknown): Date | null {
  if (typeof value !== "string" || !TIMESTAMP_WITH_OFFSET_PATTERN.test(value)) {
    return null;
  }
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) ? new Date(milliseconds) : null;
}

function nullableIdentityString(value: unknown): string | null | undefined {
  if (value == null) {
    return null;
  }
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value !== value.trim()
  ) {
    return undefined;
  }
  return value;
}

function parseReportIndexRows(
  payload: unknown,
  expectedRunKind?: DecisionBoardRunKind,
): ReportIndexRow[] {
  if (!Array.isArray(payload)) {
    return [];
  }

  const rows: ReportIndexRow[] = [];
  for (const entry of payload) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const raw = entry as {
      report_key?: unknown;
      bucket_id?: unknown;
      report_type?: unknown;
      report_date?: unknown;
      duplicate_index?: unknown;
      generated_at?: unknown;
      summary?: unknown;
      tickers?: unknown;
      tickers_hydrated?: unknown;
      run_kind?: unknown;
      run_id?: unknown;
      idempotency_key?: unknown;
      decision_created_at?: unknown;
    };

    const bucketId = trimmedString(raw.bucket_id) || "reports";
    const reportKey = trimmedString(raw.report_key);
    const reportType = isReportType(raw.report_type) ? raw.report_type : null;
    const reportDate = trimmedString(raw.report_date);
    const duplicateIndex = nonNegativeNumber(raw.duplicate_index);
    if (!reportKey || !reportType || !reportDate || duplicateIndex === null) {
      continue;
    }

    const generatedAt =
      typeof raw.generated_at === "string" && raw.generated_at.trim()
        ? raw.generated_at
        : null;
    const summary =
      raw.summary &&
      typeof raw.summary === "object" &&
      !Array.isArray(raw.summary)
        ? (raw.summary as Record<string, unknown>)
        : null;
    const tickers = normalizedStringArray(raw.tickers);
    const tickersHydrated = raw.tickers_hydrated === true;

    const runKind = nullableIdentityString(raw.run_kind);
    const runId = nullableIdentityString(raw.run_id);
    const idempotencyKey = nullableIdentityString(raw.idempotency_key);
    const decisionCreatedAt = nullableIdentityString(raw.decision_created_at);
    if (
      runKind === undefined ||
      runId === undefined ||
      idempotencyKey === undefined ||
      decisionCreatedAt === undefined
    ) {
      continue;
    }

    if (reportType === "decision-board") {
      const parsedKey = parseReportStorageKey(reportKey);
      const createdAt = parseOffsetTimestamp(decisionCreatedAt);
      const utcDate = createdAt?.toISOString().slice(0, 10);
      if (
        typeof raw.bucket_id !== "string" ||
        raw.bucket_id !== bucketId ||
        typeof raw.report_key !== "string" ||
        raw.report_key !== reportKey ||
        typeof raw.report_date !== "string" ||
        raw.report_date !== reportDate ||
        duplicateIndex !== 0 ||
        (runKind !== "ENTRY" && runKind !== "HOLDING") ||
        (expectedRunKind !== undefined && runKind !== expectedRunKind) ||
        runId === null ||
        !RUN_ID_PATTERN.test(runId) ||
        idempotencyKey === null ||
        !IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey) ||
        decisionCreatedAt === null ||
        createdAt === null ||
        utcDate !== reportDate ||
        parsedKey?.type !== "decision-board" ||
        parsedKey.reportDate !== reportDate ||
        parsedKey.runKind !== runKind ||
        parsedKey.runId !== runId ||
        parsedKey.idempotencyKey !== idempotencyKey ||
        raw.generated_at != null ||
        raw.summary != null ||
        !Array.isArray(raw.tickers) ||
        raw.tickers_hydrated !== true ||
        raw.tickers.length !== tickers.length ||
        raw.tickers.some(
          (ticker, index) =>
            typeof ticker !== "string" ||
            ticker !== tickers[index] ||
            !DECISION_BOARD_TICKER_PATTERN.test(ticker),
        ) ||
        new Set(tickers).size !== tickers.length ||
        tickers.some(
          (ticker, index) => index > 0 && tickers[index - 1] >= ticker,
        )
      ) {
        continue;
      }
    } else if (
      runKind !== null ||
      runId !== null ||
      idempotencyKey !== null ||
      decisionCreatedAt !== null
    ) {
      continue;
    }

    rows.push({
      bucket_id: bucketId,
      report_key: reportKey,
      report_type: reportType,
      report_date: reportDate,
      duplicate_index: duplicateIndex,
      generated_at: generatedAt,
      summary,
      tickers,
      tickers_hydrated: tickersHydrated,
      run_kind: runKind as DecisionBoardRunKind | null,
      run_id: runId,
      idempotency_key: idempotencyKey,
      decision_created_at: decisionCreatedAt,
    });
  }
  return rows;
}

export async function fetchReportIndexPage(
  options: FetchReportIndexPageOptions = {},
): Promise<FetchReportIndexPageResult> {
  const env = getSupabaseEnv();
  const type = options.type ?? "all";
  const runKind = options.runKind;
  if (runKind !== undefined && type !== "decision-board") {
    throw new TypeError("runKind requires type=decision-board");
  }
  if (runKind !== undefined && runKind !== "ENTRY" && runKind !== "HOLDING") {
    throw new TypeError("runKind must be ENTRY or HOLDING");
  }
  const isDecisionBoard = type === "decision-board";
  const pageSize = Math.min(Math.max(options.limit ?? 100, 1), 1000);
  const includeTotal = options.includeTotal !== false;
  const lookahead = options.lookahead === true;
  const query = new URLSearchParams({
    select: REPORT_INDEX_SELECT,
    order: isDecisionBoard
      ? DECISION_BOARD_REPORT_INDEX_ORDER
      : LEGACY_REPORT_INDEX_ORDER,
    limit: String(lookahead ? pageSize + 1 : pageSize),
  });
  if (options.cursor) {
    query.set(
      "or",
      isDecisionBoard
        ? buildDecisionBoardKeysetFilter(options.cursor)
        : buildReportIndexKeysetFilter(options.cursor),
    );
  }
  if (type !== "all") {
    query.set("report_type", `eq.${type}`);
  }
  if (runKind !== undefined) {
    query.set("run_kind", `eq.${runKind}`);
  }

  const url = `${env.SUPABASE_URL}/rest/v1/report_index?${query.toString()}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
      ...(includeTotal ? { Prefer: "count=exact" } : {}),
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch report index: ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  const rows = Array.isArray(payload) ? payload : [];
  const hasMore = lookahead && rows.length > pageSize;
  const pageRows = hasMore ? rows.slice(0, pageSize) : rows;
  const fetchedCount = pageRows.length;
  const items = parseReportIndexRows(pageRows, runKind);
  const nextCursor = hasMore
    ? isDecisionBoard
      ? parseDecisionBoardIndexCursor(pageRows[pageRows.length - 1])
      : parseReportIndexCursor(pageRows[pageRows.length - 1])
    : null;
  const total =
    (includeTotal
      ? parseContentRangeTotal(response.headers.get("content-range"))
      : null) ?? items.length;
  return {
    items,
    total,
    fetchedCount,
    hasMore,
    nextCursor,
  };
}

export async function fetchLatestDecisionBoardReport(
  runKind: DecisionBoardRunKind,
): Promise<ReportIndexRow | null> {
  let cursor: ReportIndexCursor | undefined;
  for (
    let pageNumber = 0;
    pageNumber < LATEST_DECISION_BOARD_MAX_PAGES;
    pageNumber += 1
  ) {
    const page = await fetchReportIndexPage({
      type: "decision-board",
      runKind,
      limit: LATEST_DECISION_BOARD_PAGE_SIZE,
      includeTotal: false,
      lookahead: true,
      cursor,
    });
    const row = page.items[0];
    if (row?.run_kind === runKind) {
      return row;
    }
    if (!page.hasMore) {
      return null;
    }
    if (!page.nextCursor) {
      throw new SupabaseApiError(
        "Failed to continue latest Decision Board lookup: no safe Decision Board cursor",
        502,
      );
    }
    cursor = page.nextCursor;
  }
  throw new SupabaseApiError(
    `${LATEST_DECISION_BOARD_MAX_PAGES}-page safety limit reached during latest Decision Board lookup`,
    502,
  );
}

export async function upsertReportIndexEntry(
  input: ReportIndexUpsertInput,
): Promise<void> {
  const env = getSupabaseEnv();
  const bucketId = input.bucketId?.trim() || env.SUPABASE_REPORTS_BUCKET;
  const url = `${env.SUPABASE_URL}/rest/v1/report_index?on_conflict=bucket_id,report_key`;
  const row = {
    bucket_id: bucketId,
    report_key: input.reportKey,
    report_type: input.reportType,
    report_date: input.reportDate,
    duplicate_index: Math.max(0, Math.trunc(input.duplicateIndex)),
    generated_at: input.generatedAt ?? null,
    summary: input.summary ?? null,
    tickers: normalizedStringArray(input.tickers),
    tickers_hydrated: input.tickersHydrated === true,
  };

  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal",
    }),
    body: JSON.stringify([row]),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to upsert report index: ${await parseError(response)}`,
      response.status,
    );
  }
}

export async function fetchReportIndexEntry(
  reportKey: string,
  bucketId?: string,
): Promise<ReportIndexRow | null> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: REPORT_INDEX_SELECT,
    report_key: `eq.${reportKey}`,
    limit: "2",
  });
  const bucket = bucketId?.trim();
  if (bucket) {
    query.set("bucket_id", `eq.${bucket}`);
  }
  const url = `${env.SUPABASE_URL}/rest/v1/report_index?${query.toString()}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch report index entry: ${await parseError(response)}`,
      response.status,
    );
  }

  const rows = parseReportIndexRows((await response.json()) as unknown);
  if (rows.length > 1) {
    throw new SupabaseApiError(
      `Report key '${reportKey}' exists in multiple buckets; specify bucket_id`,
      409,
    );
  }
  return rows[0] ?? null;
}

export async function downloadStorageJson(
  bucket: string,
  key: string,
): Promise<Record<string, unknown>> {
  const env = getSupabaseEnv();
  const encodedKey = encodeStorageKey(key);
  const url = `${env.SUPABASE_URL}/storage/v1/object/${encodeURIComponent(bucket)}/${encodedKey}`;

  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to download '${key}': ${await parseError(response)}`,
      response.status,
    );
  }

  const text = await response.text();
  try {
    const payload = JSON.parse(text) as unknown;
    if (payload && typeof payload === "object" && !Array.isArray(payload)) {
      return payload as Record<string, unknown>;
    }
  } catch {
    // no-op
  }

  throw new SupabaseApiError(`Report '${key}' is not a valid JSON object`, 500);
}

export async function downloadStorageBytes(
  bucket: string,
  key: string,
  maxBytes: number,
): Promise<Uint8Array> {
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
    throw new TypeError("storage byte limit is invalid");
  }
  const env = getSupabaseEnv();
  const encodedKey = encodeStorageKey(key);
  const url = `${env.SUPABASE_URL}/storage/v1/object/${encodeURIComponent(bucket)}/${encodedKey}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({ Accept: "application/json" }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new SupabaseApiError(
      "Storage object download failed",
      response.status,
    );
  }

  const declaredLength = response.headers.get("content-length");
  if (declaredLength !== null) {
    const parsedLength = Number(declaredLength);
    if (
      !Number.isSafeInteger(parsedLength) ||
      parsedLength < 0 ||
      parsedLength > maxBytes
    ) {
      throw new SupabaseApiError("Storage object exceeds byte limit", 422);
    }
  }
  if (!response.body) {
    throw new SupabaseApiError("Storage object body is unavailable", 422);
  }

  const chunks: Uint8Array[] = [];
  let length = 0;
  const reader = response.body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      length += value.byteLength;
      if (length > maxBytes) {
        await reader.cancel();
        throw new SupabaseApiError("Storage object exceeds byte limit", 422);
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}
