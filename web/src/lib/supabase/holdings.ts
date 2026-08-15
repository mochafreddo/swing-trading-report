import "server-only";

import {
  ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
  ADD_BUY_IDEMPOTENCY_MISMATCH_DETAIL,
} from "@/lib/add-buy-idempotency";
import { getSupabaseEnv } from "@/lib/env.server";
import { normalizeHoldingMutationForPersistence } from "@/lib/holding-mutation";
import { buildHoldingTickerAliases } from "@/lib/holding-ticker";
import {
  buildHoldingsKeysetFilter,
  encodeHoldingCursor,
} from "@/lib/holdings-pagination";
import { hasOwn } from "@/lib/object-utils";
import {
  buildAuthHeaders,
  fetchSupabase,
  parseError,
  parseErrorPayload,
  SupabaseApiError,
} from "@/lib/supabase/admin-client";
import type {
  HoldingCursor,
  HoldingBrokerState,
  HoldingMutationInput,
  HoldingRecord,
  HoldingReplaceSnapshot,
} from "@/lib/types";

const HOLDINGS_SELECT =
  "ticker,quantity,entry_price,entry_currency,entry_date,strategy,entry_pattern,notes,tags,stop_override,target_override,broker_state,broker_missing_first_seen_date,broker_missing_last_seen_date,broker_missing_count,broker_missing_diff_hash,created_at,updated_at";

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

export interface ReplaceAllHoldingsResult {
  insertedCount: number;
  updatedCount: number;
  deletedCount: number;
  unchangedCount: number;
}

export interface BrokerHoldingsMutationResult extends ReplaceAllHoldingsResult {
  postStateDigest: string;
}

export interface BrokerHoldingsState {
  holdings: HoldingRecord[];
  holdingsDigest: string;
}

export interface ReplaceAllHoldingsOptions {
  expectedCurrentHoldings?: readonly HoldingRecord[];
}

export interface ApplyScheduledTossQuarantineInput {
  targetRows: HoldingReplaceSnapshot[];
  quarantineTickers: string[];
  expectedCurrentHoldings: readonly HoldingRecord[];
  sessionDate: string;
  diffHash: string;
}

export interface ApplyScheduledTossQuarantineResult {
  insertedCount: number;
  updatedCount: number;
  quarantinedCount: number;
  unchangedCount: number;
  postStateDigest: string;
}

const BROKER_DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

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

export async function fetchAllHoldings(): Promise<HoldingRecord[]> {
  const env = getSupabaseEnv();
  const pageSize = 500;
  const items: HoldingRecord[] = [];

  for (let offset = 0; ; offset += pageSize) {
    const query = new URLSearchParams({
      select: HOLDINGS_SELECT,
      order: "ticker.asc",
      limit: String(pageSize),
      offset: String(offset),
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
        `Failed to fetch holdings snapshot: ${await parseError(response)}`,
        response.status,
      );
    }

    const payload = (await response.json()) as unknown;
    const rows = Array.isArray(payload) ? (payload as HoldingRecord[]) : [];
    items.push(...rows);

    if (rows.length < pageSize) {
      return items;
    }
  }
}

function parseReplaceAllHoldingsResult(
  payload: unknown,
): ReplaceAllHoldingsResult | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const raw = payload[0] as
    | {
        inserted_count?: unknown;
        updated_count?: unknown;
        deleted_count?: unknown;
        unchanged_count?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const insertedCount =
    typeof raw.inserted_count === "number" &&
    Number.isFinite(raw.inserted_count)
      ? raw.inserted_count
      : null;
  const updatedCount =
    typeof raw.updated_count === "number" && Number.isFinite(raw.updated_count)
      ? raw.updated_count
      : null;
  const deletedCount =
    typeof raw.deleted_count === "number" && Number.isFinite(raw.deleted_count)
      ? raw.deleted_count
      : null;
  const unchangedCount =
    typeof raw.unchanged_count === "number" &&
    Number.isFinite(raw.unchanged_count)
      ? raw.unchanged_count
      : null;

  if (
    insertedCount === null ||
    updatedCount === null ||
    deletedCount === null ||
    unchangedCount === null
  ) {
    return null;
  }

  return {
    insertedCount,
    updatedCount,
    deletedCount,
    unchangedCount,
  };
}

function serializeHoldingReplaceRow(row: HoldingReplaceSnapshot) {
  const payload = {
    ticker: row.ticker,
    quantity: row.quantity,
    entry_price: row.entry_price,
    entry_currency: row.entry_currency,
    entry_date: row.entry_date,
    strategy: row.strategy,
    ...(hasOwn(row, "entry_pattern") && row.entry_pattern !== undefined
      ? { entry_pattern: row.entry_pattern }
      : {}),
    notes: row.notes,
    tags: row.tags,
    stop_override: row.stop_override,
    target_override: row.target_override,
  } satisfies HoldingMutationInput & {
    ticker: string;
    quantity: number;
    entry_price: number;
    tags: string[];
  };
  return normalizeHoldingMutationForPersistence(payload);
}

function serializeExpectedHolding(row: HoldingRecord) {
  const payload = normalizeHoldingMutationForPersistence({
    ticker: row.ticker,
    quantity: row.quantity,
    entry_price: row.entry_price,
    entry_currency: row.entry_currency,
    entry_date: row.entry_date,
    strategy: row.strategy,
    entry_pattern: row.entry_pattern,
    notes: row.notes,
    tags: row.tags,
    stop_override: row.stop_override,
    target_override: row.target_override,
  } satisfies HoldingMutationInput & {
    ticker: string;
    quantity: number;
    entry_price: number;
    tags: string[];
  });
  return {
    ...payload,
    broker_state: row.broker_state ?? "confirmed",
    broker_missing_first_seen_date: row.broker_missing_first_seen_date ?? null,
    broker_missing_last_seen_date: row.broker_missing_last_seen_date ?? null,
    broker_missing_count: row.broker_missing_count ?? 0,
    broker_missing_diff_hash: row.broker_missing_diff_hash ?? null,
  } satisfies ReturnType<typeof normalizeHoldingMutationForPersistence> & {
    broker_state: HoldingBrokerState;
    broker_missing_first_seen_date: string | null;
    broker_missing_last_seen_date: string | null;
    broker_missing_count: number;
    broker_missing_diff_hash: string | null;
  };
}

function parseScheduledTossQuarantineResult(
  payload: unknown,
): ApplyScheduledTossQuarantineResult | null {
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const raw = payload[0] as
    | {
        inserted_count?: unknown;
        updated_count?: unknown;
        quarantined_count?: unknown;
        unchanged_count?: unknown;
        post_state_digest?: unknown;
      }
    | undefined;
  if (!raw || typeof raw !== "object") {
    return null;
  }

  const insertedCount =
    typeof raw.inserted_count === "number" &&
    Number.isFinite(raw.inserted_count)
      ? raw.inserted_count
      : null;
  const updatedCount =
    typeof raw.updated_count === "number" && Number.isFinite(raw.updated_count)
      ? raw.updated_count
      : null;
  const quarantinedCount =
    typeof raw.quarantined_count === "number" &&
    Number.isFinite(raw.quarantined_count)
      ? raw.quarantined_count
      : null;
  const unchangedCount =
    typeof raw.unchanged_count === "number" &&
    Number.isFinite(raw.unchanged_count)
      ? raw.unchanged_count
      : null;
  const postStateDigest =
    typeof raw.post_state_digest === "string" &&
    BROKER_DIGEST_PATTERN.test(raw.post_state_digest)
      ? raw.post_state_digest
      : null;

  if (
    insertedCount === null ||
    updatedCount === null ||
    quarantinedCount === null ||
    unchangedCount === null ||
    postStateDigest === null
  ) {
    return null;
  }

  return {
    insertedCount,
    updatedCount,
    quarantinedCount,
    unchangedCount,
    postStateDigest,
  };
}

function parseBrokerReplaceResult(
  payload: unknown,
): BrokerHoldingsMutationResult | null {
  const counts = parseReplaceAllHoldingsResult(payload);
  const raw = Array.isArray(payload) ? payload[0] : null;
  const postStateDigest =
    raw &&
    typeof raw === "object" &&
    "post_state_digest" in raw &&
    typeof raw.post_state_digest === "string" &&
    BROKER_DIGEST_PATTERN.test(raw.post_state_digest)
      ? raw.post_state_digest
      : null;
  return counts && postStateDigest ? { ...counts, postStateDigest } : null;
}

function parseBrokerHoldingNumber(value: unknown): number | null {
  const parsed =
    typeof value === "number"
      ? value
      : typeof value === "string"
        ? Number(value)
        : Number.NaN;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

function parseBrokerHoldingRow(value: unknown): HoldingRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  const quantity = parseBrokerHoldingNumber(raw.quantity);
  const entryPrice = parseBrokerHoldingNumber(raw.entry_price);
  if (
    typeof raw.ticker !== "string" ||
    !raw.ticker ||
    quantity === null ||
    entryPrice === null ||
    !Array.isArray(raw.tags) ||
    !raw.tags.every((tag) => typeof tag === "string")
  ) {
    return null;
  }
  const nullableText = (field: string): string | null =>
    typeof raw[field] === "string" ? raw[field] : null;
  const nullableNumber = (field: string): number | null =>
    raw[field] == null ? null : parseBrokerHoldingNumber(raw[field]);
  const missingCount = raw.broker_missing_count;
  if (
    (raw.broker_state !== "confirmed" &&
      raw.broker_state !== "not_seen_in_toss") ||
    typeof missingCount !== "number" ||
    !Number.isSafeInteger(missingCount) ||
    missingCount < 0
  ) {
    return null;
  }
  const stopOverride = nullableNumber("stop_override");
  const targetOverride = nullableNumber("target_override");
  if (
    (raw.stop_override != null && stopOverride === null) ||
    (raw.target_override != null && targetOverride === null)
  ) {
    return null;
  }
  return {
    ticker: raw.ticker,
    quantity,
    entry_price: entryPrice,
    entry_currency: nullableText("entry_currency"),
    entry_date: nullableText("entry_date"),
    strategy: nullableText("strategy"),
    entry_pattern: nullableText("entry_pattern"),
    notes: nullableText("notes"),
    tags: [...raw.tags],
    stop_override: stopOverride,
    target_override: targetOverride,
    broker_state: raw.broker_state,
    broker_missing_first_seen_date: nullableText(
      "broker_missing_first_seen_date",
    ),
    broker_missing_last_seen_date: nullableText(
      "broker_missing_last_seen_date",
    ),
    broker_missing_count: missingCount,
    broker_missing_diff_hash: nullableText("broker_missing_diff_hash"),
    created_at: "",
    updated_at: "",
  };
}

function parseBrokerHoldingsState(
  payload: unknown,
): BrokerHoldingsState | null {
  if (!Array.isArray(payload) || payload.length !== 1) return null;
  const raw = payload[0];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  if (
    !Array.isArray(record.holdings) ||
    typeof record.holdings_digest !== "string" ||
    !BROKER_DIGEST_PATTERN.test(record.holdings_digest)
  ) {
    return null;
  }
  const holdings = record.holdings.map(parseBrokerHoldingRow);
  if (holdings.some((row) => row === null)) return null;
  return {
    holdings: holdings as HoldingRecord[],
    holdingsDigest: record.holdings_digest,
  };
}

export async function replaceAllHoldings(
  input: HoldingReplaceSnapshot[],
  options: ReplaceAllHoldingsOptions = {},
): Promise<ReplaceAllHoldingsResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/replace_holdings_v1`;
  const body: {
    p_holdings: Array<ReturnType<typeof serializeHoldingReplaceRow>>;
    p_expected_holdings?: Array<ReturnType<typeof serializeExpectedHolding>>;
  } = {
    p_holdings: input.map(serializeHoldingReplaceRow),
  };
  if (options.expectedCurrentHoldings) {
    body.p_expected_holdings = options.expectedCurrentHoldings.map(
      serializeExpectedHolding,
    );
  }
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    const parsedError = await parseErrorPayload(response);
    const isSnapshotConflict =
      parsedError.code === "40001" ||
      parsedError.details === "holdings_snapshot_conflict";
    throw new SupabaseApiError(
      `Failed to replace holdings: ${parsedError.message}`,
      isSnapshotConflict ? 409 : response.status,
      {
        upstreamCode: parsedError.code,
        details: parsedError.details,
        hint: parsedError.hint,
      },
    );
  }

  const parsed = parseReplaceAllHoldingsResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      "Supabase did not return a valid replace_holdings_v1 result",
      500,
    );
  }

  return parsed;
}

export async function replaceAllHoldingsAndCaptureBrokerDigest(
  input: HoldingReplaceSnapshot[],
  options: ReplaceAllHoldingsOptions = {},
): Promise<BrokerHoldingsMutationResult> {
  const env = getSupabaseEnv();
  const body: {
    p_holdings: Array<ReturnType<typeof serializeHoldingReplaceRow>>;
    p_expected_holdings?: Array<ReturnType<typeof serializeExpectedHolding>>;
  } = { p_holdings: input.map(serializeHoldingReplaceRow) };
  if (options.expectedCurrentHoldings) {
    body.p_expected_holdings = options.expectedCurrentHoldings.map(
      serializeExpectedHolding,
    );
  }
  const response = await fetchSupabase(
    `${env.SUPABASE_URL}/rest/v1/rpc/apply_broker_holdings_replace_v0`,
    {
      method: "POST",
      headers: buildAuthHeaders({
        "Content-Type": "application/json",
        Accept: "application/json",
      }),
      body: JSON.stringify(body),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const parsedError = await parseErrorPayload(response);
    const isSnapshotConflict =
      parsedError.code === "40001" ||
      parsedError.details === "holdings_snapshot_conflict";
    throw new SupabaseApiError(
      `Failed to replace broker holdings: ${parsedError.message}`,
      isSnapshotConflict ? 409 : response.status,
      {
        upstreamCode: parsedError.code,
        details: parsedError.details,
        hint: parsedError.hint,
      },
    );
  }
  const parsed = parseBrokerReplaceResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      "Supabase did not return a valid apply_broker_holdings_replace_v0 result",
      500,
    );
  }
  return parsed;
}

export async function fetchBrokerHoldingsState(): Promise<BrokerHoldingsState> {
  const env = getSupabaseEnv();
  const response = await fetchSupabase(
    `${env.SUPABASE_URL}/rest/v1/rpc/get_broker_holdings_state_v0`,
    {
      method: "POST",
      headers: buildAuthHeaders({
        "Content-Type": "application/json",
        Accept: "application/json",
      }),
      body: "{}",
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch broker holdings state: ${await parseError(response)}`,
      response.status,
    );
  }
  const parsed = parseBrokerHoldingsState(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      "get_broker_holdings_state_v0 returned an invalid result",
      500,
    );
  }
  return parsed;
}

export async function captureBrokerHoldingsDigest(
  expectedPreStateDigest: string,
): Promise<string> {
  if (!BROKER_DIGEST_PATTERN.test(expectedPreStateDigest)) {
    throw new TypeError("Expected broker holdings pre-state digest is invalid");
  }
  const env = getSupabaseEnv();
  const response = await fetchSupabase(
    `${env.SUPABASE_URL}/rest/v1/rpc/capture_broker_holdings_digest_v0`,
    {
      method: "POST",
      headers: buildAuthHeaders({
        "Content-Type": "application/json",
        Accept: "application/json",
      }),
      body: JSON.stringify({
        p_expected_pre_state_digest: expectedPreStateDigest,
      }),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    const parsedError = await parseErrorPayload(response);
    const isConflict =
      parsedError.code === "40001" ||
      parsedError.details === "broker_holdings_pre_state_conflict";
    throw new SupabaseApiError(
      `Failed to capture broker holdings digest: ${parsedError.message}`,
      isConflict ? 409 : response.status,
      {
        upstreamCode: parsedError.code,
        details: parsedError.details,
        hint: parsedError.hint,
      },
    );
  }
  const payload = (await response.json()) as unknown;
  const raw =
    Array.isArray(payload) && payload.length === 1 ? payload[0] : null;
  const digest =
    raw &&
    typeof raw === "object" &&
    "holdings_digest" in raw &&
    typeof raw.holdings_digest === "string"
      ? raw.holdings_digest
      : "";
  if (!BROKER_DIGEST_PATTERN.test(digest)) {
    throw new SupabaseApiError(
      "capture_broker_holdings_digest_v0 returned an invalid result",
      500,
    );
  }
  return digest;
}

export async function applyScheduledTossQuarantine(
  input: ApplyScheduledTossQuarantineInput,
): Promise<ApplyScheduledTossQuarantineResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/apply_broker_holdings_quarantine_v0`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_holdings: input.targetRows.map(serializeHoldingReplaceRow),
      p_quarantine_tickers: input.quarantineTickers,
      p_expected_holdings: input.expectedCurrentHoldings.map(
        serializeExpectedHolding,
      ),
      p_session_date: input.sessionDate,
      p_diff_hash: input.diffHash,
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    const parsedError = await parseErrorPayload(response);
    const isSnapshotConflict =
      parsedError.code === "40001" ||
      parsedError.details === "holdings_snapshot_conflict";
    throw new SupabaseApiError(
      `Failed to apply scheduled Toss quarantine: ${parsedError.message}`,
      isSnapshotConflict ? 409 : response.status,
      {
        upstreamCode: parsedError.code,
        details: parsedError.details,
        hint: parsedError.hint,
      },
    );
  }

  const parsed = parseScheduledTossQuarantineResult(await response.json());
  if (!parsed) {
    throw new SupabaseApiError(
      "Supabase did not return a valid apply_broker_holdings_quarantine_v0 result",
      500,
    );
  }

  return parsed;
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

async function fetchHoldingByAnyTickerAlias(
  ticker: string,
): Promise<HoldingRecord | null> {
  for (const alias of buildHoldingTickerAliases(ticker)) {
    const existing = await fetchHoldingByExactTicker(alias);
    if (existing) {
      return existing;
    }
  }
  return null;
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
    body: JSON.stringify(normalizeHoldingMutationForPersistence(patch)),
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
    const existing = await fetchHoldingByAnyTickerAlias(ticker);
    if (existing) {
      throw new SupabaseApiError(
        `Holding '${existing.ticker}' already exists`,
        409,
      );
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
    body: JSON.stringify(normalizeHoldingMutationForPersistence(input)),
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
  if (typeof patch.ticker === "string" && patch.ticker) {
    const target = await fetchHoldingByAnyTickerAlias(ticker);
    if (target) {
      const targetAliases = new Set(buildHoldingTickerAliases(target.ticker));
      const patchAliases = buildHoldingTickerAliases(patch.ticker);
      const isSameLogicalTicker = patchAliases.some((alias) =>
        targetAliases.has(alias),
      );
      if (!isSameLogicalTicker) {
        const existing = await fetchHoldingByAnyTickerAlias(patch.ticker);
        if (existing && !targetAliases.has(existing.ticker)) {
          throw new SupabaseApiError(
            `Holding '${existing.ticker}' already exists`,
            409,
          );
        }
      }
      return patchHoldingByExactTicker(target.ticker, patch);
    }
  }

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
