import "server-only";

import { getSupabaseEnv } from "@/lib/env.server";
import { toErrorMessage } from "@/lib/error-utils";
import { createMemoryTtlLruCache } from "@/lib/memory-ttl-lru-cache";
import {
  parseVerifiedDecisionBoardReport,
  type DecisionBoardEnvelopeV0,
} from "@/lib/decision-board-schema";
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
  fetchReportIndexEntry,
  fetchReportIndexPage,
  SupabaseApiError,
  type ReportIndexCursor,
} from "@/lib/supabase-admin";
import type {
  ReportListItem,
  ReportSearchWarning,
  ReportsListResponse,
  DecisionBoardRunKind,
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
    bucketId: row.bucket_id,
    type: row.report_type,
    reportDate: row.report_date,
    duplicateIndex: row.duplicate_index,
    ...(row.run_kind ? { runKind: row.run_kind } : {}),
    ...(row.run_id ? { runId: row.run_id } : {}),
    ...extras,
  };
}

function buildPartialFailureWarning(error: unknown): ReportSearchWarning {
  return {
    code: "partial_failure",
    message: `검색 중 일부 인덱스 페이지를 불러오지 못했습니다: ${toErrorMessage(error)}`,
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
  runKind?: DecisionBoardRunKind;
}

type ListReportsInput = Omit<ListReportsOptions, "refresh">;

const reportListCache = createMemoryTtlLruCache<ReportsListResponse>({
  maxEntries: REPORT_LIST_CACHE_MAX_ENTRIES,
});

const reportDetailCache = createMemoryTtlLruCache<{
  key: string;
  bucketId: string;
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
    `runKind=${options.runKind ?? ""}`,
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
  const { type, runKind, q, limit, searchWindow } = options;

  if (runKind !== undefined && type !== "decision-board") {
    throw new TypeError("runKind requires type=decision-board");
  }

  if (!q) {
    const { items, hasMore } = await fetchReportIndexPage({
      type,
      runKind,
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
        runKind,
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
    runKind: options.runKind,
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

export class InvalidDecisionBoardReportError extends Error {
  readonly status = 422;

  constructor() {
    super("Decision Board report failed validation");
    this.name = "InvalidDecisionBoardReportError";
  }
}

const PRIVATE_DECISION_BOARD_FIELDS = new Set([
  "account",
  "accountid",
  "accountnumber",
  "articlefulltext",
  "articletext",
  "credential",
  "currentprice",
  "entryprice",
  "exception",
  "notes",
  "pl",
  "pnl",
  "private",
  "providererror",
  "providerexception",
  "quantity",
  "rawarticle",
  "secret",
  "tags",
  "token",
  "traceback",
]);

function containsPrivateDecisionBoardField(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some(containsPrivateDecisionBoardField);
  }
  if (!value || typeof value !== "object") {
    return false;
  }
  return Object.entries(value).some(
    ([key, child]) =>
      PRIVATE_DECISION_BOARD_FIELDS.has(
        key.toLowerCase().replace(/[^a-z0-9]/g, ""),
      ) || containsPrivateDecisionBoardField(child),
  );
}

async function validateDecisionBoardDetail(
  report: Record<string, unknown>,
  parsedKey: NonNullable<ReturnType<typeof parseReportStorageKey>>,
): Promise<DecisionBoardEnvelopeV0> {
  try {
    const validated = await parseVerifiedDecisionBoardReport(report);
    if (
      containsPrivateDecisionBoardField(validated) ||
      validated.run_kind !== parsedKey.runKind ||
      validated.run_id !== parsedKey.runId ||
      validated.idempotency_key !== parsedKey.idempotencyKey
    ) {
      throw new InvalidDecisionBoardReportError();
    }
    return validated;
  } catch (error) {
    if (error instanceof InvalidDecisionBoardReportError) {
      throw error;
    }
    throw new InvalidDecisionBoardReportError();
  }
}

async function readReportDetailUncached(
  key: string,
  bucketId?: string,
): Promise<{
  key: string;
  bucketId: string;
  report: Record<string, unknown>;
}> {
  const parsedKey = parseReportStorageKey(key);
  if (!parsedKey) {
    throw new InvalidReportKeyError();
  }
  const env = getSupabaseEnv();
  const indexEntry = await fetchReportIndexEntry(key, bucketId);
  if ((bucketId || parsedKey.type === "decision-board") && !indexEntry) {
    throw new SupabaseApiError("Report not found", 404);
  }
  const bucket = indexEntry?.bucket_id ?? env.SUPABASE_REPORTS_BUCKET;
  const downloaded = await downloadStorageJson(bucket, key);
  const report =
    parsedKey.type === "decision-board"
      ? await validateDecisionBoardDetail(downloaded, parsedKey)
      : downloaded;
  return { key, bucketId: bucket, report };
}

export async function readReportDetail(
  key: string,
  options?: { refresh?: boolean; bucketId?: string },
): Promise<{
  key: string;
  bucketId: string;
  report: Record<string, unknown>;
}> {
  const parsedKey = parseReportStorageKey(key);
  if (!parsedKey) {
    throw new InvalidReportKeyError();
  }
  if (parsedKey.type === "decision-board" && parsedKey.key !== key) {
    throw new InvalidReportKeyError();
  }

  const refresh = options?.refresh === true;
  const bucketId = options?.bucketId?.trim() || undefined;
  if (!isReportsCacheEnabled()) {
    return readReportDetailUncached(parsedKey.key, bucketId);
  }

  return reportDetailCache.getOrLoad({
    key: `bucket=${bucketId ?? ""}&key=${parsedKey.key}&identity=${parsedKey.idempotencyKey ?? "legacy"}`,
    ttlMs: REPORT_DETAIL_CACHE_TTL_MS,
    refresh,
    load: () => readReportDetailUncached(parsedKey.key, bucketId),
  });
}

export function __resetReportsCacheForTests(): void {
  reportListCache.clear();
  reportDetailCache.clear();
}
