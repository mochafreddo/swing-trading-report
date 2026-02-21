import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import type { ReportType } from "@/lib/types";
import {
  buildHoldingsKeysetFilter,
  encodeHoldingCursor,
} from "@/lib/holdings-pagination";
import type {
  HoldingCursor,
  HoldingMutationInput,
  HoldingRecord,
} from "@/lib/types";

const HOLDINGS_SELECT =
  "ticker,quantity,entry_price,entry_currency,entry_date,strategy,notes,tags,stop_override,target_override,created_at,updated_at";

export class SupabaseApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
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

const REPORT_INDEX_SELECT =
  "report_key,report_type,report_date,duplicate_index,generated_at,summary,tickers,tickers_hydrated";

interface StorageListOptions {
  prefix?: string;
  limit?: number;
  offset?: number;
}

export async function listStorageObjectsPage(
  bucket: string,
  options: StorageListOptions = {},
): Promise<StorageListRow[]> {
  const { prefix = "", limit = 1000, offset = 0 } = options;
  const env = getSupabaseEnv();
  const url = `${env.SUPABASE_URL}/storage/v1/object/list/${encodeURIComponent(bucket)}`;

  const response = await fetch(url, {
    method: "POST",
    headers: buildAuthHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify({
      prefix,
      limit,
      offset,
      sortBy: {
        column: "name",
        order: "asc",
      },
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to list storage objects: ${await parseError(response)}`,
      response.status,
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
      const page = await listStorageObjectsPage(bucket, {
        prefix,
        limit,
        offset,
      });

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

interface CachedStorageKeysEntry {
  keys: string[];
  expiresAt: number;
}

const storageKeysCache = new Map<string, CachedStorageKeysEntry>();
const storageKeysInFlight = new Map<string, Promise<string[]>>();

export function __resetStorageKeysCacheForTests(): void {
  storageKeysCache.clear();
  storageKeysInFlight.clear();
}

export async function listAllStorageKeysCached(
  bucket: string,
  ttlSeconds: number,
): Promise<string[]> {
  const ttlMilliseconds = Math.max(0, ttlSeconds) * 1000;
  if (ttlMilliseconds === 0) {
    return listAllStorageKeys(bucket);
  }

  const now = Date.now();
  const cached = storageKeysCache.get(bucket);
  if (cached && cached.expiresAt > now) {
    return [...cached.keys];
  }

  const inFlight = storageKeysInFlight.get(bucket);
  if (inFlight) {
    const keys = await inFlight;
    return [...keys];
  }

  const loading = (async () => {
    const keys = await listAllStorageKeys(bucket);
    storageKeysCache.set(bucket, {
      keys: [...keys],
      expiresAt: Date.now() + ttlMilliseconds,
    });
    return [...keys];
  })();

  storageKeysInFlight.set(bucket, loading);

  try {
    const keys = await loading;
    return [...keys];
  } finally {
    if (storageKeysInFlight.get(bucket) === loading) {
      storageKeysInFlight.delete(bucket);
    }
  }
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
}

export interface FetchReportIndexPageResult {
  items: ReportIndexRow[];
  total: number;
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
      raw.report_type === "buy" || raw.report_type === "sell"
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
  const query = new URLSearchParams({
    select: REPORT_INDEX_SELECT,
    order: "report_date.desc,duplicate_index.desc",
    limit: String(pageSize),
  });
  if (type !== "all") {
    query.set("report_type", `eq.${type}`);
  }

  const url = `${env.SUPABASE_URL}/rest/v1/report_index?${query.toString()}`;
  const response = await fetch(url, {
    headers: buildAuthHeaders({
      Accept: "application/json",
      Prefer: "count=exact",
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
  const items = parseReportIndexRows(payload);
  const total =
    parseContentRangeTotal(response.headers.get("content-range")) ??
    items.length;
  return {
    items,
    total,
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

  const response = await fetch(url, {
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

  const response = await fetch(url, {
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
  const response = await fetch(url, {
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

export async function createHolding(
  input: HoldingMutationInput,
): Promise<HoldingRecord> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({ select: HOLDINGS_SELECT });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetch(url, {
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
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: HOLDINGS_SELECT,
    ticker: `eq.${ticker}`,
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetch(url, {
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

export async function deleteHolding(ticker: string): Promise<boolean> {
  const env = getSupabaseEnv();
  const query = new URLSearchParams({
    select: "ticker",
    ticker: `eq.${ticker}`,
  });
  const url = `${env.SUPABASE_URL}/rest/v1/holdings?${query.toString()}`;

  const response = await fetch(url, {
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
