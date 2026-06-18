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
import {
  buildAuthHeaders,
  fetchSupabase,
  parseError,
  parseErrorPayload,
  SupabaseApiError,
} from "@/lib/supabase/admin-client";
import type {
  HoldingCursor,
  HoldingMutationInput,
  HoldingRecord,
  HoldingReplaceSnapshot,
} from "@/lib/types";

const HOLDINGS_SELECT =
  "ticker,quantity,entry_price,entry_currency,entry_date,strategy,entry_pattern,notes,tags,stop_override,target_override,created_at,updated_at";

const hasOwn = (value: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

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

export async function replaceAllHoldings(
  input: HoldingReplaceSnapshot[],
): Promise<ReplaceAllHoldingsResult> {
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/rest/v1/rpc/replace_holdings_v1`;
  const response = await fetchSupabase(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      p_holdings: input.map((row) => {
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
      }),
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to replace holdings: ${await parseError(response)}`,
      response.status,
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
