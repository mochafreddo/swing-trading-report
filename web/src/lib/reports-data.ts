import { getSupabaseEnv } from "@/lib/env.server";
import { createMemoryTtlLruCache } from "@/lib/memory-ttl-lru-cache";
import { parseReportStorageKey } from "@/lib/report-key";
import {
  REPORT_DETAIL_CACHE_MAX_ENTRIES,
  REPORT_DETAIL_CACHE_TTL_MS,
  REPORT_LIST_CACHE_MAX_ENTRIES,
  REPORT_LIST_CACHE_TTL_MS,
  REPORT_SEARCH_CACHE_TTL_MS,
} from "@/lib/reports-cache-config";
import {
  downloadStorageJson,
  fetchReportIndexPage,
  type ReportIndexCursor,
} from "@/lib/supabase-admin";
import type {
  ReportListItem,
  ReportSearchWarning,
  ReportsListResponse,
  ReportType,
} from "@/lib/types";

const REPORT_SEARCH_PAGE_SIZE = 100;

type ReportIndexRow = Awaited<
  ReturnType<typeof fetchReportIndexPage>
>["items"][number];

function matchesTickerQuery(
  tickers: string[] | undefined,
  query: string,
): boolean {
  if (!tickers || tickers.length === 0) {
    return false;
  }
  const needle = query.toLowerCase();
  return tickers.some((ticker) => ticker.toLowerCase().includes(needle));
}

function toReportListItem(
  row: ReportIndexRow,
  extras?: Pick<ReportListItem, "generatedAt" | "summary" | "tickers">,
): ReportListItem {
  return {
    key: row.report_key,
    type: row.report_type,
    reportDate: row.report_date,
    duplicateIndex: row.duplicate_index,
    ...extras,
  };
}

function buildPartialFailureWarning(error: unknown): ReportSearchWarning {
  const message = error instanceof Error ? error.message : "Unknown error";
  return {
    code: "partial_failure",
    message: `검색 중 일부 인덱스 페이지를 불러오지 못했습니다: ${message}`,
  };
}

function buildIndexIncompleteWarning(count: number): ReportSearchWarning {
  return {
    code: "index_incomplete",
    message: `인덱스 미완료 리포트 ${count}건은 검색 결과에서 제외되었습니다.`,
  };
}

export interface ListReportsOptions {
  type: "all" | ReportType;
  q: string;
  limit: number;
  searchWindow: number;
  refresh?: boolean;
}

type ListReportsInput = Omit<ListReportsOptions, "refresh">;

const reportListCache = createMemoryTtlLruCache<ReportsListResponse>({
  maxEntries: REPORT_LIST_CACHE_MAX_ENTRIES,
});

const reportDetailCache = createMemoryTtlLruCache<{
  key: string;
  report: Record<string, unknown>;
}>({
  maxEntries: REPORT_DETAIL_CACHE_MAX_ENTRIES,
});

function isReportsCacheEnabled(): boolean {
  if (process.env.NODE_ENV !== "test") {
    return true;
  }
  return process.env.SAB_ENABLE_REPORTS_CACHE_IN_TEST === "1";
}

function buildListReportsCacheKey(options: ListReportsInput): string {
  const normalizedQuery = options.q.trim().toLowerCase();
  return [
    `type=${options.type}`,
    `q=${normalizedQuery}`,
    `limit=${options.limit}`,
    `searchWindow=${options.searchWindow}`,
  ].join("&");
}

function resolveListReportsTtlMs(query: string): number {
  return query.trim() ? REPORT_SEARCH_CACHE_TTL_MS : REPORT_LIST_CACHE_TTL_MS;
}

async function listReportsUncached(
  options: ListReportsInput,
): Promise<ReportsListResponse> {
  const { type, q, limit, searchWindow } = options;

  if (!q) {
    const { items, hasMore } = await fetchReportIndexPage({
      type,
      limit,
      includeTotal: false,
      lookahead: true,
    });
    return {
      items: items.map((row) => toReportListItem(row)),
      total: null,
      searched: 0,
      searchWindow,
      truncated: hasMore,
      warnings: [],
    };
  }

  const matchedItems: ReportListItem[] = [];
  const warnings: ReportSearchWarning[] = [];
  let searched = 0;
  let cursor: ReportIndexCursor | undefined;
  let hasMoreCandidates = false;
  let partialFailure = false;
  let incompleteRows = 0;

  while (searched < searchWindow) {
    const pageSize = Math.min(REPORT_SEARCH_PAGE_SIZE, searchWindow - searched);
    if (pageSize <= 0) {
      break;
    }

    let page: Awaited<ReturnType<typeof fetchReportIndexPage>>;
    try {
      page = await fetchReportIndexPage({
        type,
        limit: pageSize,
        cursor,
        includeTotal: false,
        lookahead: true,
      });
    } catch (error) {
      if (searched === 0) {
        throw error;
      }
      warnings.push(buildPartialFailureWarning(error));
      partialFailure = true;
      break;
    }

    if (page.fetchedCount <= 0) {
      break;
    }

    for (const row of page.items) {
      if (!row.tickers_hydrated) {
        incompleteRows += 1;
        continue;
      }

      if (!matchesTickerQuery(row.tickers, q)) {
        continue;
      }

      matchedItems.push(
        toReportListItem(row, {
          generatedAt: row.generated_at ?? undefined,
          summary: row.summary ?? undefined,
          tickers: row.tickers.length > 0 ? row.tickers : undefined,
        }),
      );
    }

    searched += page.fetchedCount;
    hasMoreCandidates = page.hasMore;
    if (!page.hasMore) {
      break;
    }
    if (!page.nextCursor) {
      warnings.push(
        buildPartialFailureWarning(
          new Error("검색 커서를 계산하지 못해 검색을 중단했습니다."),
        ),
      );
      partialFailure = true;
      break;
    }
    cursor = page.nextCursor;
  }

  if (incompleteRows > 0) {
    warnings.push(buildIndexIncompleteWarning(incompleteRows));
  }

  return {
    items: matchedItems.slice(0, limit),
    total: matchedItems.length,
    searched,
    searchWindow,
    truncated:
      partialFailure || (searched >= searchWindow && hasMoreCandidates),
    warnings,
  };
}

export async function listReports(
  options: ListReportsOptions,
): Promise<ReportsListResponse> {
  const input: ListReportsInput = {
    type: options.type,
    q: options.q.trim(),
    limit: options.limit,
    searchWindow: options.searchWindow,
  };
  const refresh = options.refresh === true;

  if (!isReportsCacheEnabled()) {
    return listReportsUncached(input);
  }

  return reportListCache.getOrLoad({
    key: buildListReportsCacheKey(input),
    ttlMs: resolveListReportsTtlMs(input.q),
    refresh,
    load: () => listReportsUncached(input),
  });
}

export class InvalidReportKeyError extends Error {
  readonly status = 400;

  constructor(message = "Invalid report key format") {
    super(message);
  }
}

async function readReportDetailUncached(key: string): Promise<{
  key: string;
  report: Record<string, unknown>;
}> {
  const env = getSupabaseEnv();
  const report = await downloadStorageJson(env.SUPABASE_REPORTS_BUCKET, key);
  return { key, report };
}

export async function readReportDetail(
  key: string,
  options?: { refresh?: boolean },
): Promise<{
  key: string;
  report: Record<string, unknown>;
}> {
  const parsedKey = parseReportStorageKey(key);
  if (!parsedKey) {
    throw new InvalidReportKeyError();
  }

  const refresh = options?.refresh === true;
  if (!isReportsCacheEnabled()) {
    return readReportDetailUncached(parsedKey.key);
  }

  return reportDetailCache.getOrLoad({
    key: parsedKey.key,
    ttlMs: REPORT_DETAIL_CACHE_TTL_MS,
    refresh,
    load: () => readReportDetailUncached(parsedKey.key),
  });
}

export function __resetReportsCacheForTests(): void {
  reportListCache.clear();
  reportDetailCache.clear();
}
