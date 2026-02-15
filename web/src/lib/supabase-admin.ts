import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import {
  buildHoldingsKeysetFilter,
  encodeHoldingCursor
} from "@/lib/holdings-pagination";
import type {
  HoldingCursor,
  HoldingMutationInput,
  HoldingRecord
} from "@/lib/types";

const HOLDINGS_SELECT =
  "ticker,quantity,entry_price,entry_currency,entry_date,strategy,notes,tags,stop_override,target_override,created_at,updated_at";

export class SupabaseApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

function buildAuthHeaders(extra?: Record<string, string>): HeadersInit {
  const env = getSupabaseEnv();
  return {
    apikey: env.SUPABASE_API_KEY,
    Authorization: `Bearer ${env.SUPABASE_API_KEY}`,
    ...extra
  };
}

function encodeStorageKey(key: string): string {
  return key
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

async function parseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `HTTP ${response.status}`;
  }

  try {
    const parsed = JSON.parse(text) as { message?: string; error?: string };
    return parsed.message || parsed.error || text;
  } catch {
    return text;
  }
}

export interface StorageListRow {
  name?: string;
}

interface StorageListOptions {
  prefix?: string;
  limit?: number;
  offset?: number;
}

export async function listStorageObjectsPage(
  bucket: string,
  options: StorageListOptions = {}
): Promise<StorageListRow[]> {
  const { prefix = "", limit = 1000, offset = 0 } = options;
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/storage/v1/object/list/${encodeURIComponent(bucket)}`;

  const response = await fetch(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json"
    }),
    body: JSON.stringify({
      prefix,
      limit,
      offset,
      sortBy: {
        column: "name",
        order: "asc"
      }
    }),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to list storage objects: ${await parseError(response)}`,
      response.status
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload)) {
    return [];
  }

  return payload as StorageListRow[];
}

export async function listAllStorageKeys(bucket: string): Promise<string[]> {
  const keys = new Set<string>();
  const prefixesToVisit: string[] = [""];
  const visitedPrefixes = new Set<string>();
  const limit = 1000;

  while (prefixesToVisit.length > 0) {
    const prefix = prefixesToVisit.pop() ?? "";
    if (visitedPrefixes.has(prefix)) {
      continue;
    }
    visitedPrefixes.add(prefix);

    let offset = 0;
    while (true) {
      const page = await listStorageObjectsPage(bucket, { prefix, limit, offset });

      for (const item of page) {
        if (typeof item.name !== "string") {
          continue;
        }

        const name = item.name.trim();
        if (!name) {
          continue;
        }

        const fullName =
          prefix && name.startsWith(prefix) ? name : `${prefix}${name}`;

        if (name.endsWith(".json")) {
          keys.add(fullName);
          continue;
        }

        if (!name.includes(".")) {
          prefixesToVisit.push(`${fullName}/`);
        }
      }

      if (page.length < limit) {
        break;
      }
      offset += limit;
    }
  }

  return Array.from(keys);
}

export async function downloadStorageJson(
  bucket: string,
  key: string
): Promise<Record<string, unknown>> {
  const env = getSupabaseEnv();
  const encodedKey = encodeStorageKey(key);
  const url = `${env.SUPABASE_URL}/storage/v1/object/${encodeURIComponent(bucket)}/${encodedKey}`;

  const response = await fetch(url, {
    headers: buildAuthHeaders({
      Accept: "application/json"
    }),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to download '${key}': ${await parseError(response)}`,
      response.status
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

export async function fetchHoldingsPage(
  options: FetchHoldingsPageOptions = {}
): Promise<FetchHoldingsPageResult> {
  const env = getSupabaseEnv();
  const pageSize = Math.min(Math.max(options.limit ?? 100, 1), 200);
  const query = new URLSearchParams({
    select: HOLDINGS_SELECT,
    order: "updated_at.desc,ticker.asc",
    limit: String(pageSize + 1)
  });
  if (options.cursor) {
    query.set("or", buildHoldingsKeysetFilter(options.cursor));
  }

  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;
  const response = await fetch(url, {
    headers: buildAuthHeaders({
      Accept: "application/json"
    }),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to fetch holdings: ${await parseError(response)}`,
      response.status
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
          ticker: tail.ticker
        })
      : null;

  return {
    items,
    nextCursor,
    hasMore
  };
}

export async function createHolding(
  input: HoldingMutationInput
): Promise<HoldingRecord> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({ select: HOLDINGS_SELECT });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetch(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
      Prefer: "return=representation"
    }),
    body: JSON.stringify(input),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to create holding: ${await parseError(response)}`,
      response.status
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
  patch: HoldingMutationInput
): Promise<HoldingRecord | null> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: HOLDINGS_SELECT,
    ticker: `eq.${ticker}`
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetch(url, {
    method: "PATCH",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
      Prefer: "return=representation"
    }),
    body: JSON.stringify(patch),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to update holding '${ticker}': ${await parseError(response)}`,
      response.status
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  return payload[0] as HoldingRecord;
}

export async function deleteHolding(ticker: string): Promise<boolean> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: "ticker",
    ticker: `eq.${ticker}`
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetch(url, {
    method: "DELETE",
    headers: buildAuthHeaders({
      Accept: "application/json",
      Prefer: "return=representation"
    }),
    cache: "no-store"
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to delete holding '${ticker}': ${await parseError(response)}`,
      response.status
    );
  }

  const payload = (await response.json()) as unknown;
  return Array.isArray(payload) && payload.length > 0;
}
