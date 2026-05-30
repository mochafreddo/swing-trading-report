import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import { isReportType, type ReportType } from "@/lib/types";
import {
  buildAuthHeaders,
  fetchSupabase,
  parseError,
  SupabaseApiError,
} from "@/lib/supabase/admin-client";

const REPORT_INDEX_SELECT =
  "report_key,report_type,report_date,duplicate_index,generated_at,summary,tickers,tickers_hydrated";

export interface ReportIndexRow {
  report_key: string;
  report_type: ReportType;
  report_date: string;
  duplicate_index: number;
  generated_at: string | null;
  summary: Record<string, unknown> | null;
  tickers: string[];
  tickers_hydrated: boolean;
}

export interface FetchReportIndexPageOptions {
  type?: ReportType | "all";
  limit?: number;
  cursor?: ReportIndexCursor;
  includeTotal?: boolean;
  lookahead?: boolean;
}

export interface ReportIndexCursor {
  report_date: string;
  duplicate_index: number;
  report_key: string;
}

export interface FetchReportIndexPageResult {
  items: ReportIndexRow[];
  total: number;
  fetchedCount: number;
  hasMore: boolean;
  nextCursor: ReportIndexCursor | null;
}

export interface ReportIndexUpsertInput {
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

function quotePostgrestValue(value: string): string {
  const escaped = value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `"${escaped}"`;
}

function trimmedString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function parseReportIndexCursor(payload: unknown): ReportIndexCursor | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const raw = payload as {
    report_date?: unknown;
    duplicate_index?: unknown;
    report_key?: unknown;
  };

  const reportDate = trimmedString(raw.report_date);
  const duplicateIndex =
    typeof raw.duplicate_index === "number" &&
    Number.isFinite(raw.duplicate_index) &&
    Number.isInteger(raw.duplicate_index)
      ? raw.duplicate_index
      : null;
  const reportKey = trimmedString(raw.report_key);

  if (
    !reportDate ||
    duplicateIndex === null ||
    duplicateIndex < 0 ||
    !reportKey
  ) {
    return null;
  }

  return {
    report_date: reportDate,
    duplicate_index: duplicateIndex,
    report_key: reportKey,
  };
}

function buildReportIndexKeysetFilter(cursor: ReportIndexCursor): string {
  const reportDate = quotePostgrestValue(cursor.report_date);
  const reportKey = quotePostgrestValue(cursor.report_key);
  return `(report_date.lt.${reportDate},and(report_date.eq.${reportDate},duplicate_index.lt.${cursor.duplicate_index}),and(report_date.eq.${reportDate},duplicate_index.eq.${cursor.duplicate_index},report_key.lt.${reportKey}))`;
}

function parseReportIndexRows(payload: unknown): ReportIndexRow[] {
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
      report_type?: unknown;
      report_date?: unknown;
      duplicate_index?: unknown;
      generated_at?: unknown;
      summary?: unknown;
      tickers?: unknown;
      tickers_hydrated?: unknown;
    };

    const reportKey = trimmedString(raw.report_key);
    const reportType = isReportType(raw.report_type) ? raw.report_type : null;
    const reportDate = trimmedString(raw.report_date);
    const duplicateIndex =
      typeof raw.duplicate_index === "number" &&
      Number.isFinite(raw.duplicate_index)
        ? raw.duplicate_index
        : null;
    if (
      !reportKey ||
      !reportType ||
      !reportDate ||
      duplicateIndex === null ||
      duplicateIndex < 0
    ) {
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
    const tickers = Array.isArray(raw.tickers)
      ? raw.tickers
          .filter((value): value is string => typeof value === "string")
          .map((value) => value.trim())
          .filter(Boolean)
      : [];
    const tickersHydrated = raw.tickers_hydrated === true;

    rows.push({
      report_key: reportKey,
      report_type: reportType,
      report_date: reportDate,
      duplicate_index: duplicateIndex,
      generated_at: generatedAt,
      summary,
      tickers,
      tickers_hydrated: tickersHydrated,
    });
  }
  return rows;
}

export async function fetchReportIndexPage(
  options: FetchReportIndexPageOptions = {},
): Promise<FetchReportIndexPageResult> {
  const env = getSupabaseEnv();
  const type = options.type ?? "all";
  const pageSize = Math.min(Math.max(options.limit ?? 100, 1), 1000);
  const includeTotal = options.includeTotal !== false;
  const lookahead = options.lookahead === true;
  const query = new URLSearchParams({
    select: REPORT_INDEX_SELECT,
    order: "report_date.desc,duplicate_index.desc,report_key.desc",
    limit: String(lookahead ? pageSize + 1 : pageSize),
  });
  if (options.cursor) {
    query.set("or", buildReportIndexKeysetFilter(options.cursor));
  }
  if (type !== "all") {
    query.set("report_type", `eq.${type}`);
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
  const items = parseReportIndexRows(pageRows);
  const nextCursor = hasMore
    ? parseReportIndexCursor(pageRows[pageRows.length - 1])
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

export async function upsertReportIndexEntry(
  input: ReportIndexUpsertInput,
): Promise<void> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/report_index?on_conflict=report_key`;
  const row = {
    report_key: input.reportKey,
    report_type: input.reportType,
    report_date: input.reportDate,
    duplicate_index: Math.max(0, Math.trunc(input.duplicateIndex)),
    generated_at: input.generatedAt ?? null,
    summary: input.summary ?? null,
    tickers: (input.tickers ?? [])
      .map((ticker) => ticker.trim())
      .filter(Boolean),
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
