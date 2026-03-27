import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import type { ReportType } from "@/lib/types";
import {
  buildHoldingsKeysetFilter,
  encodeHoldingCursor,
} from "@/lib/holdings-pagination";
import {
  ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
  ADD_BUY_IDEMPOTENCY_MISMATCH_DETAIL,
} from "@/lib/add-buy-idempotency";
import { buildHoldingTickerAliases } from "@/lib/holding-ticker";
import { FetchTimeoutError, fetchWithTimeout } from "@/lib/fetch-timeout";
import type {
  HoldingCursor,
  HoldingMutationInput,
  HoldingRecord,
} from "@/lib/types";

const HOLDINGS_SELECT =
  "ticker,quantity,entry_price,entry_currency,entry_date,strategy,notes,tags,stop_override,target_override,created_at,updated_at";

const RUNTIME_STATE_SELECT = "state_key,state_payload,expires_at";

export class SupabaseApiError extends Error {
  public readonly code: string | null;
  public readonly upstreamCode: string | null;
  public readonly details: string | null;
  public readonly hint: string | null;

  constructor(
    message: string,
    public readonly status: number,
    options?: {
      code?: string | null;
      upstreamCode?: string | null;
      details?: string | null;
      hint?: string | null;
    },
  ) {
    super(message);
    this.code = options?.code ?? null;
    this.upstreamCode = options?.upstreamCode ?? null;
    this.details = options?.details ?? null;
    this.hint = options?.hint ?? null;
  }
}

async function fetchSupabase(
  url: string,
  init: Omit<RequestInit, "signal">,
): Promise<Response> {
  try {
    return await fetchWithTimeout(url, init);
  } catch (error) {
    if (error instanceof FetchTimeoutError) {
      throw new SupabaseApiError(
        `Supabase request timed out after ${error.timeoutMs}ms`,
        504,
      );
    }
    throw error;
  }
}

function buildAuthHeaders(extra?: Record<string, string>): HeadersInit {
  const env = getSupabaseEnv();
  return {
    apikey: env.SUPABASE_API_KEY,
    Authorization: `Bearer ${env.SUPABASE_API_KEY}`,
    ...extra,
  };
}

function encodeStorageKey(key: string): string {
  return key
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

interface ParsedSupabaseErrorPayload {
  message: string;
  code: string | null;
  details: string | null;
  hint: string | null;
}

function trimTextOrNull(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

async function parseErrorPayload(
  response: Response,
): Promise<ParsedSupabaseErrorPayload> {
  const text = await response.text();
  if (!text) {
    return {
      message: `HTTP ${response.status}`,
      code: null,
      details: null,
      hint: null,
    };
  }

  try {
    const parsed = JSON.parse(text) as {
      message?: unknown;
      error?: unknown;
      code?: unknown;
      details?: unknown;
      hint?: unknown;
    };
    const message =
      trimTextOrNull(parsed.message) || trimTextOrNull(parsed.error) || text;
    return {
      message,
      code: trimTextOrNull(parsed.code),
      details: trimTextOrNull(parsed.details),
      hint: trimTextOrNull(parsed.hint),
    };
  } catch {
    return {
      message: text,
      code: null,
      details: null,
      hint: null,
    };
  }
}

async function parseError(response: Response): Promise<string> {
  const parsed = await parseErrorPayload(response);
  return parsed.message;
}

const REPORT_INDEX_SELECT =
  "report_key,report_type,report_date,duplicate_index,generated_at,summary,tickers,tickers_hydrated";

export interface RuntimeStateEntry {
  state_key: string;
  state_payload: Record<string, unknown>;
  expires_at: string;
}

export interface ConsumeLoginThrottleAttemptInput {
  key: string;
  now: number;
  windowMs: number;
  blockMs: number;
  maxAttempts: number;
  userKeyCap: number;
}

export interface ConsumeLoginThrottleAttemptResult {
  failures: number;
  windowStartedAt: number;
  blockedUntil: number;
  isBlocked: boolean;
  retryAfterSeconds: number;
}

export interface ClaimRuntimeStateLockInput {
  key: string;
  now: number;
  ttlSeconds: number;
  payload?: Record<string, unknown>;
}

export interface ClaimRuntimeStateLockResult {
  acquired: boolean;
  expiresAt: string;
}

export interface ReleaseRuntimeStateLockInput {
  key: string;
  ownerToken: string;
}

function parseRuntimeStateEntry(payload: unknown): RuntimeStateEntry | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const raw = payload[0] as
    | {
        state_key?: unknown;
        state_payload?: unknown;
        expires_at?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  if (
    typeof raw.state_key !== "string" ||
    !raw.state_key.trim() ||
    typeof raw.expires_at !== "string" ||
    !raw.expires_at.trim() ||
    !raw.state_payload ||
    typeof raw.state_payload !== "object" ||
    Array.isArray(raw.state_payload)
  ) {
    return null;
  }

  return {
    state_key: raw.state_key,
    state_payload: raw.state_payload as Record<string, unknown>,
    expires_at: raw.expires_at,
  };
}

export async function fetchRuntimeStateEntry(
  key: string,
): Promise<RuntimeStateEntry | null> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: RUNTIME_STATE_SELECT,
    state_key: `eq.${key}`,
    limit: "1",
  });
  const url = `${env.SUPABASE_URL}/rest/v1/runtime_state?${query.toString()}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch runtime state '${key}': ${await parseError(response)}`,
      response.status,
    );
  }

  return parseRuntimeStateEntry(await response.json());
}

export async function upsertRuntimeStateEntry(
  key: string,
  payload: Record<string, unknown>,
  expiresAtIso: string,
): Promise<void> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/runtime_state?on_conflict=state_key`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal",
    }),
    body: JSON.stringify([
      {
        state_key: key,
        state_payload: payload,
        expires_at: expiresAtIso,
      },
    ]),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to upsert runtime state '${key}': ${await parseError(response)}`,
      response.status,
    );
  }
}

export async function deleteRuntimeStateEntry(key: string): Promise<void> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    state_key: `eq.${key}`,
  });
  const url = `${env.SUPABASE_URL}/rest/v1/runtime_state?${query.toString()}`;
  const response = await fetchSupabase(url, {
    method: "DELETE",
    headers: buildAuthHeaders({
      Accept: "application/json",
      Prefer: "return=minimal",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to delete runtime state '${key}': ${await parseError(response)}`,
      response.status,
    );
  }
}

function parseConsumeLoginThrottleAttemptResult(
  payload: unknown,
): ConsumeLoginThrottleAttemptResult | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const raw = payload[0] as
    | {
        failures?: unknown;
        window_started_at?: unknown;
        blocked_until?: unknown;
        is_blocked?: unknown;
        retry_after_seconds?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  if (
    typeof raw.failures !== "number" ||
    !Number.isFinite(raw.failures) ||
    !Number.isInteger(raw.failures) ||
    raw.failures < 0 ||
    typeof raw.window_started_at !== "number" ||
    !Number.isFinite(raw.window_started_at) ||
    !Number.isInteger(raw.window_started_at) ||
    raw.window_started_at < 0 ||
    typeof raw.blocked_until !== "number" ||
    !Number.isFinite(raw.blocked_until) ||
    !Number.isInteger(raw.blocked_until) ||
    raw.blocked_until < 0 ||
    typeof raw.is_blocked !== "boolean" ||
    typeof raw.retry_after_seconds !== "number" ||
    !Number.isFinite(raw.retry_after_seconds) ||
    !Number.isInteger(raw.retry_after_seconds) ||
    raw.retry_after_seconds < 0
  ) {
    return null;
  }

  return {
    failures: raw.failures,
    windowStartedAt: raw.window_started_at,
    blockedUntil: raw.blocked_until,
    isBlocked: raw.is_blocked,
    retryAfterSeconds: raw.retry_after_seconds,
  };
}

function parseClaimRuntimeStateLockResult(
  payload: unknown,
): ClaimRuntimeStateLockResult | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }
  const raw = payload[0] as
    | {
        acquired?: unknown;
        expires_at?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  if (typeof raw.acquired !== "boolean" || typeof raw.expires_at !== "string") {
    return null;
  }
  return {
    acquired: raw.acquired,
    expiresAt: raw.expires_at,
  };
}

export async function claimRuntimeStateLock(
  input: ClaimRuntimeStateLockInput,
): Promise<ClaimRuntimeStateLockResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/claim_runtime_state_lock`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_state_key: input.key,
      p_now: new Date(input.now).toISOString(),
      p_ttl_seconds: Math.max(1, Math.floor(input.ttlSeconds)),
      p_state_payload: input.payload ?? {},
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to claim runtime state lock '${input.key}': ${await parseError(response)}`,
      response.status,
    );
  }

  const parsed = parseClaimRuntimeStateLockResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      `Failed to parse runtime state lock claim result for '${input.key}'`,
      500,
    );
  }
  return parsed;
}

export async function releaseRuntimeStateLock(
  input: ReleaseRuntimeStateLockInput,
): Promise<boolean> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/release_runtime_state_lock`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_state_key: input.key,
      p_owner_token: input.ownerToken,
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to release runtime state lock '${input.key}': ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  if (typeof payload !== "boolean") {
    throw new SupabaseApiError(
      `Failed to parse runtime state lock release result for '${input.key}'`,
      500,
    );
  }
  return payload;
}

export async function consumeLoginThrottleAttempt(
  input: ConsumeLoginThrottleAttemptInput,
): Promise<ConsumeLoginThrottleAttemptResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/consume_login_throttle_attempt`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_state_key: input.key,
      p_now: new Date(input.now).toISOString(),
      p_window_seconds: Math.max(1, Math.floor(input.windowMs / 1000)),
      p_block_seconds: Math.max(1, Math.floor(input.blockMs / 1000)),
      p_max_attempts: Math.max(1, Math.floor(input.maxAttempts)),
      p_user_key_cap: Math.max(1, Math.floor(input.userKeyCap)),
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to consume login throttle attempt: ${await parseError(response)}`,
      response.status,
    );
  }

  const parsed = parseConsumeLoginThrottleAttemptResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      "Supabase did not return a valid consume_login_throttle_attempt result",
      500,
    );
  }
  return parsed;
}

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

function parseReportIndexCursor(payload: unknown): ReportIndexCursor | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const raw = payload as {
    report_date?: unknown;
    duplicate_index?: unknown;
    report_key?: unknown;
  };

  const reportDate =
    typeof raw.report_date === "string" ? raw.report_date.trim() : "";
  const duplicateIndex =
    typeof raw.duplicate_index === "number" &&
    Number.isFinite(raw.duplicate_index) &&
    Number.isInteger(raw.duplicate_index)
      ? raw.duplicate_index
      : null;
  const reportKey =
    typeof raw.report_key === "string" ? raw.report_key.trim() : "";

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

    const reportKey =
      typeof raw.report_key === "string" ? raw.report_key.trim() : "";
    const reportType =
      raw.report_type === "buy" ||
      raw.report_type === "sell" ||
      raw.report_type === "entry"
        ? raw.report_type
        : null;
    const reportDate =
      typeof raw.report_date === "string" ? raw.report_date.trim() : "";
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
    if (payload && typeof payload === "object") {
      return payload as Record<string, unknown>;
    }
  } catch {
    // no-op
  }

  throw new SupabaseApiError(`Report '${key}' is not a valid JSON object`, 500);
}

export interface FetchHoldingsPageOptions {
  limit?: number;
  cursor?: HoldingCursor;
}

export interface FetchHoldingsPageResult {
  items: HoldingRecord[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface HoldingAddBuyInput {
  buy_quantity: number;
  buy_price: number;
  buy_date?: string;
}

export async function fetchHoldingsPage(
  options: FetchHoldingsPageOptions = {},
): Promise<FetchHoldingsPageResult> {
  const env = getSupabaseEnv();
  const pageSize = Math.min(Math.max(options.limit ?? 100, 1), 200);
  const query = new URLSearchParams({
    select: HOLDINGS_SELECT,
    order: "updated_at.desc,ticker.asc",
    limit: String(pageSize + 1),
  });
  if (options.cursor) {
    query.set("or", buildHoldingsKeysetFilter(options.cursor));
  }

  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch holdings: ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  const rows = Array.isArray(payload) ? (payload as HoldingRecord[]) : [];
  const hasMore = rows.length > pageSize;
  const items = hasMore ? rows.slice(0, pageSize) : rows;

  const tail = items.at(-1);
  const nextCursor =
    hasMore && tail && typeof tail.updated_at === "string"
      ? encodeHoldingCursor({
          updated_at: tail.updated_at,
          ticker: tail.ticker,
        })
      : null;

  return {
    items,
    nextCursor,
    hasMore,
  };
}

async function fetchHoldingByExactTicker(
  ticker: string,
): Promise<HoldingRecord | null> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: HOLDINGS_SELECT,
    ticker: `eq.${ticker}`,
    limit: "1",
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;
  const response = await fetchSupabase(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch holding '${ticker}': ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  return payload[0] as HoldingRecord;
}

async function patchHoldingByExactTicker(
  ticker: string,
  patch: HoldingMutationInput,
): Promise<HoldingRecord | null> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: HOLDINGS_SELECT,
    ticker: `eq.${ticker}`,
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetchSupabase(url, {
    method: "PATCH",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
      Prefer: "return=representation",
    }),
    body: JSON.stringify(patch),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to update holding '${ticker}': ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  return payload[0] as HoldingRecord;
}

async function deleteHoldingByExactTicker(ticker: string): Promise<boolean> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: "ticker",
    ticker: `eq.${ticker}`,
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetchSupabase(url, {
    method: "DELETE",
    headers: buildAuthHeaders({
      Accept: "application/json",
      Prefer: "return=representation",
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to delete holding '${ticker}': ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  return Array.isArray(payload) && payload.length > 0;
}

export async function createHolding(
  input: HoldingMutationInput,
): Promise<HoldingRecord> {
  const ticker = typeof input.ticker === "string" ? input.ticker : "";
  if (ticker) {
    for (const alias of buildHoldingTickerAliases(ticker)) {
      const existing = await fetchHoldingByExactTicker(alias);
      if (existing) {
        throw new SupabaseApiError(
          `Holding '${existing.ticker}' already exists`,
          409,
        );
      }
    }
  }

  const env = getSupabaseEnv();
  const query = new URLSearchParams({ select: HOLDINGS_SELECT });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
      Prefer: "return=representation",
    }),
    body: JSON.stringify(input),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to create holding: ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload) || payload.length === 0) {
    throw new SupabaseApiError("Supabase did not return created holding", 500);
  }

  return payload[0] as HoldingRecord;
}

export async function updateHolding(
  ticker: string,
  patch: HoldingMutationInput,
): Promise<HoldingRecord | null> {
  for (const alias of buildHoldingTickerAliases(ticker)) {
    const updated = await patchHoldingByExactTicker(alias, patch);
    if (updated) {
      return updated;
    }
  }
  return null;
}

export async function deleteHolding(ticker: string): Promise<boolean> {
  let deletedAny = false;
  for (const alias of buildHoldingTickerAliases(ticker)) {
    const deleted = await deleteHoldingByExactTicker(alias);
    if (deleted) {
      deletedAny = true;
    }
  }
  return deletedAny;
}

export async function addBuyToHolding(
  ticker: string,
  input: HoldingAddBuyInput,
  idempotencyKey: string,
): Promise<HoldingRecord | null> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/holdings_add_buy_v1`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_ticker: ticker,
      p_buy_quantity: input.buy_quantity,
      p_buy_price: input.buy_price,
      p_buy_date: input.buy_date ?? null,
      p_idempotency_key: idempotencyKey,
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    const parsedError = await parseErrorPayload(response);
    const isIdempotencyPayloadMismatch =
      response.status === 409 &&
      parsedError.details === ADD_BUY_IDEMPOTENCY_MISMATCH_DETAIL;
    throw new SupabaseApiError(
      `Failed to add buy to holding '${ticker}': ${parsedError.message}`,
      response.status,
      {
        code: isIdempotencyPayloadMismatch
          ? ADD_BUY_IDEMPOTENCY_MISMATCH_CODE
          : null,
        upstreamCode: parsedError.code,
        details: parsedError.details,
        hint: parsedError.hint,
      },
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }
  return payload[0] as HoldingRecord;
}
