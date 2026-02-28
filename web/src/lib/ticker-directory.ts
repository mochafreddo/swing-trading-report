import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import {
  downloadStorageJson,
  fetchReportIndexPage,
  fetchRuntimeStateEntry,
  type ReportIndexCursor,
  upsertRuntimeStateEntry,
} from "@/lib/supabase-admin";

const DIRECTORY_STATE_KEY = "ticker_directory:v1";
const DIRECTORY_VERSION = 1;
const DIRECTORY_STALE_MS = 24 * 60 * 60 * 1000;
const DIRECTORY_EXPIRES_MS = 365 * 24 * 60 * 60 * 1000;
const DIRECTORY_BUILD_REPORT_LIMIT = 60;
const REPORT_PAGE_SIZE = 20;

export interface TickerDirectoryCandidate {
  ticker: string;
  name: string | null;
}

interface TickerDirectoryEntryV1 {
  ticker: string;
  name: string | null;
  aliases: string[];
  lastSeenReportDate: string | null;
  lastSeenReportKey: string | null;
  updatedAtMs: number;
}

interface TickerDirectoryPayloadV1 {
  version: 1;
  builtAtMs: number;
  source: {
    buyReportsScanned: number;
    buyReportKeys: string[];
  };
  entries: TickerDirectoryEntryV1[];
}

export interface TickerDirectorySearchResult {
  ticker: string;
  name: string | null;
}

export interface TickerDirectorySearchResponse {
  q: string;
  results: TickerDirectorySearchResult[];
  directory: {
    builtAtMs: number;
    sourceReports: number;
  };
}

export interface RecentBuyCandidatesResponse {
  report: {
    key: string;
    reportDate: string | null;
  } | null;
  candidates: TickerDirectoryCandidate[];
}

type ReportIndexRow = Awaited<
  ReturnType<typeof fetchReportIndexPage>
>["items"][number];

interface SearchOptions {
  q: string;
  limit?: number;
}

interface RecentCandidatesOptions {
  limitReports?: number;
  limitCandidates?: number;
}

function normalizeSearchText(value: string): string {
  const normalized = value.trim().toUpperCase().normalize("NFKC");
  const compact = normalized.replace(/[^\p{L}\p{N}]+/gu, "");
  return compact || normalized;
}

function toCleanString(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim();
}

function normalizeCandidateTicker(value: unknown): string {
  const raw = toCleanString(value).toUpperCase();
  if (!raw) {
    return "";
  }
  return normalizeHoldingTickerForMutation(raw);
}

function normalizeCandidateName(value: unknown): string | null {
  const text = toCleanString(value);
  return text ? text : null;
}

function collectTickerAliases(ticker: string, name: string | null): string[] {
  const aliases = new Set<string>();
  const upperTicker = ticker.toUpperCase();
  aliases.add(upperTicker);

  const lastDotIndex = upperTicker.lastIndexOf(".");
  if (lastDotIndex > 0) {
    const symbol = upperTicker.slice(0, lastDotIndex);
    const suffix = upperTicker.slice(lastDotIndex + 1);
    aliases.add(symbol);

    const classMatch = symbol.match(/^([A-Z][A-Z0-9]*)\.([ABC])$/);
    if (classMatch) {
      aliases.add(`${classMatch[1]}/${classMatch[2]}`);
      aliases.add(`${classMatch[1]}/${classMatch[2]}.${suffix}`);
    }
  }

  if (name) {
    aliases.add(name);
    aliases.add(name.replace(/\s+/g, ""));
  }

  return Array.from(aliases);
}

function parseTickerDirectoryPayload(
  payload: Record<string, unknown>,
): TickerDirectoryPayloadV1 | null {
  const version = payload.version;
  const builtAtMs = payload.builtAtMs;
  const source = payload.source;
  const entries = payload.entries;

  if (
    version !== DIRECTORY_VERSION ||
    typeof builtAtMs !== "number" ||
    !Number.isFinite(builtAtMs) ||
    !source ||
    typeof source !== "object" ||
    Array.isArray(source) ||
    !Array.isArray(entries)
  ) {
    return null;
  }

  const sourceData = source as {
    buyReportsScanned?: unknown;
    buyReportKeys?: unknown;
  };
  const buyReportsScanned =
    typeof sourceData.buyReportsScanned === "number" &&
    Number.isFinite(sourceData.buyReportsScanned)
      ? Math.max(0, Math.floor(sourceData.buyReportsScanned))
      : 0;
  const buyReportKeys = Array.isArray(sourceData.buyReportKeys)
    ? sourceData.buyReportKeys
        .filter((key): key is string => typeof key === "string")
        .map((key) => key.trim())
        .filter(Boolean)
    : [];

  const parsedEntries: TickerDirectoryEntryV1[] = [];
  for (const entry of entries) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const raw = entry as {
      ticker?: unknown;
      name?: unknown;
      aliases?: unknown;
      lastSeenReportDate?: unknown;
      lastSeenReportKey?: unknown;
      updatedAtMs?: unknown;
    };
    const ticker = normalizeCandidateTicker(raw.ticker);
    if (!ticker) {
      continue;
    }
    const aliases = Array.isArray(raw.aliases)
      ? raw.aliases
          .filter((alias): alias is string => typeof alias === "string")
          .map((alias) => alias.trim())
          .filter(Boolean)
      : [];
    const updatedAtMs =
      typeof raw.updatedAtMs === "number" && Number.isFinite(raw.updatedAtMs)
        ? raw.updatedAtMs
        : builtAtMs;
    parsedEntries.push({
      ticker,
      name: normalizeCandidateName(raw.name),
      aliases:
        aliases.length > 0 ? aliases : collectTickerAliases(ticker, null),
      lastSeenReportDate: normalizeCandidateName(raw.lastSeenReportDate),
      lastSeenReportKey: normalizeCandidateName(raw.lastSeenReportKey),
      updatedAtMs,
    });
  }

  return {
    version: 1,
    builtAtMs,
    source: {
      buyReportsScanned,
      buyReportKeys,
    },
    entries: parsedEntries,
  };
}

function clampInt(value: number | undefined, min: number, max: number): number {
  if (!Number.isFinite(value ?? NaN)) {
    return min;
  }
  return Math.min(max, Math.max(min, Math.floor(value ?? min)));
}

async function collectRecentBuyRows(
  limitReports: number,
): Promise<ReportIndexRow[]> {
  const rows: ReportIndexRow[] = [];
  let cursor: ReportIndexCursor | undefined;

  while (rows.length < limitReports) {
    const pageSize = Math.min(REPORT_PAGE_SIZE, limitReports - rows.length);
    if (pageSize <= 0) {
      break;
    }

    const page = await fetchReportIndexPage({
      type: "buy",
      limit: pageSize,
      cursor,
      includeTotal: false,
      lookahead: true,
    });
    if (page.items.length <= 0) {
      break;
    }

    rows.push(...page.items);
    if (!page.hasMore || page.nextCursor === null) {
      break;
    }
    cursor = page.nextCursor;
  }

  return rows.slice(0, limitReports);
}

function scoreEntry(
  entry: TickerDirectoryEntryV1,
  queryUpper: string,
  queryNormalized: string,
): number | null {
  const tickerUpper = entry.ticker.toUpperCase();
  const lastDotIndex = tickerUpper.lastIndexOf(".");
  const baseSymbol = lastDotIndex > 0 ? tickerUpper.slice(0, lastDotIndex) : "";
  const nameUpper = (entry.name ?? "").toUpperCase();

  if (tickerUpper === queryUpper || baseSymbol === queryUpper) {
    return 0;
  }
  if (tickerUpper.startsWith(queryUpper) || baseSymbol.startsWith(queryUpper)) {
    return 1;
  }
  if (nameUpper.startsWith(queryUpper)) {
    return 2;
  }

  const aliases = entry.aliases.length > 0 ? entry.aliases : [tickerUpper];
  for (const alias of aliases) {
    const normalizedAlias = normalizeSearchText(alias);
    if (normalizedAlias.includes(queryNormalized)) {
      return 3;
    }
  }

  return null;
}

async function loadCachedDirectory(): Promise<TickerDirectoryPayloadV1 | null> {
  const state = await fetchRuntimeStateEntry(DIRECTORY_STATE_KEY);
  if (!state) {
    return null;
  }
  return parseTickerDirectoryPayload(state.state_payload);
}

async function getLatestBuyReportKey(): Promise<string | null> {
  const page = await fetchReportIndexPage({
    type: "buy",
    limit: 1,
    includeTotal: false,
  });
  return page.items[0]?.report_key ?? null;
}

function shouldRefreshDirectory(
  cached: TickerDirectoryPayloadV1 | null,
  latestKey: string | null,
  nowMs: number,
): boolean {
  if (!cached) {
    return true;
  }
  if (nowMs - cached.builtAtMs > DIRECTORY_STALE_MS) {
    return true;
  }
  if (latestKey && !cached.source.buyReportKeys.includes(latestKey)) {
    return true;
  }
  return false;
}

async function rebuildDirectory(): Promise<TickerDirectoryPayloadV1> {
  const nowMs = Date.now();
  const env = getSupabaseEnv();
  const rows = await collectRecentBuyRows(DIRECTORY_BUILD_REPORT_LIMIT);
  const entries = new Map<
    string,
    {
      ticker: string;
      name: string | null;
      aliases: Set<string>;
      lastSeenReportDate: string | null;
      lastSeenReportKey: string | null;
      updatedAtMs: number;
    }
  >();

  for (const row of rows) {
    let report: Record<string, unknown>;
    try {
      report = await downloadStorageJson(
        env.SUPABASE_REPORTS_BUCKET,
        row.report_key,
      );
    } catch {
      continue;
    }
    const candidates = extractBuyCandidatesFromReport(report);
    for (const candidate of candidates) {
      const existing = entries.get(candidate.ticker);
      const aliases = collectTickerAliases(candidate.ticker, candidate.name);
      if (!existing) {
        entries.set(candidate.ticker, {
          ticker: candidate.ticker,
          name: candidate.name,
          aliases: new Set(aliases),
          lastSeenReportDate: row.report_date,
          lastSeenReportKey: row.report_key,
          updatedAtMs: nowMs,
        });
        continue;
      }

      if (!existing.name && candidate.name) {
        existing.name = candidate.name;
      }
      for (const alias of aliases) {
        existing.aliases.add(alias);
      }
    }
  }

  const payload: TickerDirectoryPayloadV1 = {
    version: 1,
    builtAtMs: nowMs,
    source: {
      buyReportsScanned: rows.length,
      buyReportKeys: rows.map((row) => row.report_key),
    },
    entries: Array.from(entries.values())
      .map((entry) => ({
        ticker: entry.ticker,
        name: entry.name,
        aliases: Array.from(entry.aliases),
        lastSeenReportDate: entry.lastSeenReportDate,
        lastSeenReportKey: entry.lastSeenReportKey,
        updatedAtMs: entry.updatedAtMs,
      }))
      .sort((left, right) => left.ticker.localeCompare(right.ticker)),
  };

  await upsertRuntimeStateEntry(
    DIRECTORY_STATE_KEY,
    payload as unknown as Record<string, unknown>,
    new Date(nowMs + DIRECTORY_EXPIRES_MS).toISOString(),
  );

  return payload;
}

async function loadDirectoryForSearch(): Promise<TickerDirectoryPayloadV1> {
  const nowMs = Date.now();
  const cached = await loadCachedDirectory();
  let latestKey: string | null = null;
  try {
    latestKey = await getLatestBuyReportKey();
  } catch {
    latestKey = null;
  }

  if (!shouldRefreshDirectory(cached, latestKey, nowMs)) {
    return cached as TickerDirectoryPayloadV1;
  }

  try {
    return await rebuildDirectory();
  } catch {
    if (cached) {
      return cached;
    }
    throw new Error("Failed to build ticker directory");
  }
}

export function extractBuyCandidatesFromReport(
  report: Record<string, unknown>,
): TickerDirectoryCandidate[] {
  const rows = Array.isArray(report.candidates) ? report.candidates : [];
  const seen = new Set<string>();
  const results: TickerDirectoryCandidate[] = [];
  for (const row of rows) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      continue;
    }
    const raw = row as { ticker?: unknown; name?: unknown };
    const ticker = normalizeCandidateTicker(raw.ticker);
    if (!ticker || seen.has(ticker)) {
      continue;
    }
    seen.add(ticker);
    results.push({
      ticker,
      name: normalizeCandidateName(raw.name),
    });
  }
  return results;
}

export async function searchTickerDirectory(
  options: SearchOptions,
): Promise<TickerDirectorySearchResponse> {
  const q = options.q.trim();
  const limit = clampInt(options.limit, 1, 50);
  const directory = await loadDirectoryForSearch();
  const queryUpper = q.toUpperCase();
  const queryNormalized = normalizeSearchText(q);
  const results = directory.entries
    .map((entry) => ({
      entry,
      score: scoreEntry(entry, queryUpper, queryNormalized),
    }))
    .filter(
      (
        item,
      ): item is {
        entry: TickerDirectoryEntryV1;
        score: number;
      } => item.score !== null,
    )
    .sort((left, right) => {
      if (left.score !== right.score) {
        return left.score - right.score;
      }
      return left.entry.ticker.localeCompare(right.entry.ticker);
    })
    .slice(0, limit)
    .map((item) => ({
      ticker: item.entry.ticker,
      name: item.entry.name,
    }));

  return {
    q,
    results,
    directory: {
      builtAtMs: directory.builtAtMs,
      sourceReports: directory.source.buyReportKeys.length,
    },
  };
}

export async function listRecentBuyCandidates(
  options: RecentCandidatesOptions = {},
): Promise<RecentBuyCandidatesResponse> {
  const limitReports = clampInt(options.limitReports, 1, 50);
  const limitCandidates = clampInt(options.limitCandidates, 1, 100);
  const env = getSupabaseEnv();
  const rows = await collectRecentBuyRows(limitReports);

  for (const row of rows) {
    let report: Record<string, unknown>;
    try {
      report = await downloadStorageJson(
        env.SUPABASE_REPORTS_BUCKET,
        row.report_key,
      );
    } catch {
      continue;
    }
    const candidates = extractBuyCandidatesFromReport(report).slice(
      0,
      limitCandidates,
    );
    if (candidates.length <= 0) {
      continue;
    }
    return {
      report: {
        key: row.report_key,
        reportDate: row.report_date,
      },
      candidates,
    };
  }

  return {
    report: null,
    candidates: [],
  };
}
