import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  REPORT_DETAIL_CACHE_MAX_ENTRIES,
  REPORT_DETAIL_CACHE_TTL_MS,
  REPORT_LIST_CACHE_MAX_ENTRIES,
  REPORT_LIST_CACHE_TTL_MS,
  REPORT_SEARCH_CACHE_TTL_MS,
} from "@/lib/reports-cache-config";
import { createMemoryTtlLruCache } from "@/lib/memory-ttl-lru-cache";
import type {
  ReportListItem,
  ReportsListResponse,
  ReportSearchWarning,
} from "@/lib/types";

import {
  asRecord,
  asRecordArray,
  parseReportType,
  readApiError,
} from "./helpers";
import { resolveSelectedKeyFromUrl } from "./selected-key-sync";
import type {
  ReportJson,
  ReportsFilterType,
  ReportsInitialState,
} from "./types";

const PAGE_LIMIT = 30;

type ReportDetailResponse = { key: string; report: ReportJson };

interface ReportsListRequestPathOptions {
  type: ReportsFilterType;
  limit: number;
  query: string;
  refresh?: boolean;
}

interface ReportDetailRequestPathOptions {
  key: string;
  refresh?: boolean;
}

const reportListCache = createMemoryTtlLruCache<ReportsListResponse>({
  maxEntries: REPORT_LIST_CACHE_MAX_ENTRIES,
});

const reportDetailCache = createMemoryTtlLruCache<ReportDetailResponse>({
  maxEntries: REPORT_DETAIL_CACHE_MAX_ENTRIES,
});

function resolveListCacheTtlMs(query: string): number {
  return query.trim() ? REPORT_SEARCH_CACHE_TTL_MS : REPORT_LIST_CACHE_TTL_MS;
}

function buildListCacheKey(
  reportType: ReportsFilterType,
  appliedQuery: string,
): string {
  const normalizedQuery = appliedQuery.trim().toLowerCase();
  return `type=${reportType}&q=${normalizedQuery}&limit=${PAGE_LIMIT}`;
}

export function buildReportsListRequestPath(
  options: ReportsListRequestPathOptions,
): string {
  const params = new URLSearchParams({
    type: options.type,
    limit: String(options.limit),
  });
  if (options.query) {
    params.set("q", options.query);
  }
  if (options.refresh) {
    params.set("refresh", "1");
  }
  return `/api/reports?${params.toString()}`;
}

export function buildReportDetailRequestPath(
  options: ReportDetailRequestPathOptions,
): string {
  const params = new URLSearchParams({ key: options.key });
  if (options.refresh) {
    params.set("refresh", "1");
  }
  return `/api/reports/detail?${params.toString()}`;
}

interface ReportsStateQueryInput {
  reportType: ReportsFilterType;
  appliedQuery: string;
  selectedKey: string | null;
  showRaw: boolean;
}

function buildReportsStateQueryString(input: ReportsStateQueryInput): string {
  const params = new URLSearchParams();
  if (input.reportType !== "all") {
    params.set("type", input.reportType);
  }
  if (input.appliedQuery) {
    params.set("q", input.appliedQuery);
  }
  if (input.selectedKey) {
    params.set("key", input.selectedKey);
  }
  if (input.showRaw) {
    params.set("raw", "1");
  }
  return params.toString();
}

async function fetchReportsListCached(
  reportType: ReportsFilterType,
  appliedQuery: string,
  refresh = false,
): Promise<ReportsListResponse> {
  const cacheKey = buildListCacheKey(reportType, appliedQuery);

  return reportListCache.getOrLoad({
    key: cacheKey,
    ttlMs: resolveListCacheTtlMs(appliedQuery),
    refresh,
    load: async () => {
      const path = buildReportsListRequestPath({
        type: reportType,
        limit: PAGE_LIMIT,
        query: appliedQuery,
        refresh,
      });
      const response = await fetch(path, {
        cache: "no-store",
      });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(readApiError(payload) || "Failed to load reports");
      }

      return payload as ReportsListResponse;
    },
  });
}

async function fetchReportDetailCached(
  key: string,
  refresh = false,
): Promise<ReportDetailResponse> {
  return reportDetailCache.getOrLoad({
    key,
    ttlMs: REPORT_DETAIL_CACHE_TTL_MS,
    refresh,
    load: async () => {
      const path = buildReportDetailRequestPath({
        key,
        refresh,
      });
      const response = await fetch(path, {
        cache: "no-store",
      });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(
          readApiError(payload) || "Failed to load report detail",
        );
      }
      return payload as ReportDetailResponse;
    },
  });
}

export function useReportsState(initialState?: ReportsInitialState) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const initialUrlKey = (searchParams.get("key") ?? "").trim() || null;
  const [reportType, setReportTypeState] = useState<ReportsFilterType>(
    () => initialState?.reportType ?? parseReportType(searchParams.get("type")),
  );
  const [query, setQueryState] = useState(
    () => initialState?.query ?? searchParams.get("q") ?? "",
  );
  const [appliedQuery, setAppliedQueryState] = useState(
    () => initialState?.appliedQuery ?? (searchParams.get("q") ?? "").trim(),
  );
  const [items, setItems] = useState<ReportListItem[]>(
    () => initialState?.items ?? [],
  );
  const [total, setTotal] = useState<number | null>(
    () => initialState?.total ?? null,
  );
  const [searched, setSearched] = useState(() => initialState?.searched ?? 0);
  const [truncated, setTruncated] = useState(
    () => initialState?.truncated ?? false,
  );
  const [searchWindow, setSearchWindow] = useState(
    () => initialState?.searchWindow ?? 100,
  );
  const [warnings, setWarnings] = useState<ReportSearchWarning[]>(
    () => initialState?.warnings ?? [],
  );
  const [selectedKey, setSelectedKeyState] = useState<string | null>(() =>
    initialState ? initialState.selectedKey : searchParams.get("key"),
  );
  const [detail, setDetail] = useState<ReportJson | null>(
    () => initialState?.detail ?? null,
  );
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRawState] = useState(
    () => initialState?.showRaw ?? searchParams.get("raw") === "1",
  );
  const [refreshToken, setRefreshToken] = useState(0);
  const pendingUrlSync = useRef(
    Boolean(initialState) &&
      (initialState?.reportType !== parseReportType(searchParams.get("type")) ||
        initialState?.appliedQuery !== (searchParams.get("q") ?? "").trim() ||
        initialState?.selectedKey !== initialUrlKey ||
        initialState?.showRaw !== (searchParams.get("raw") === "1")),
  );
  const preserveSelectionWhenUrlKeyMissing = useRef(
    Boolean(initialState?.selectedKey && !searchParams.get("key")),
  );
  const skipInitialListFetch = useRef(Boolean(initialState));
  const consumedListRefreshToken = useRef(0);
  const consumedDetailRefreshToken = useRef(0);
  const skipInitialDetailFetchKey = useRef<string | null>(
    initialState?.detail &&
      initialState.detailKey &&
      initialState.detailKey === initialState.selectedKey
      ? initialState.selectedKey
      : null,
  );

  const desiredQueryString = useMemo(
    () =>
      buildReportsStateQueryString({
        reportType,
        appliedQuery,
        selectedKey,
        showRaw,
      }),
    [appliedQuery, reportType, selectedKey, showRaw],
  );

  const currentQueryString = useMemo(
    () =>
      buildReportsStateQueryString({
        reportType: parseReportType(searchParams.get("type")),
        appliedQuery: (searchParams.get("q") ?? "").trim(),
        selectedKey: searchParams.get("key"),
        showRaw: searchParams.get("raw") === "1",
      }),
    [searchParams],
  );

  /* eslint-disable react-hooks/set-state-in-effect -- URL search params are an external source; this reconciles browser navigation with optimistic local report state. */
  useEffect(() => {
    const nextType = parseReportType(searchParams.get("type"));
    const nextQuery = searchParams.get("q") ?? "";
    const nextAppliedQuery = nextQuery.trim();
    const nextKeyRaw = searchParams.get("key");
    const nextShowRaw = searchParams.get("raw") === "1";
    const preserveWhenKeyMissing = preserveSelectionWhenUrlKeyMissing.current;
    const nextKey = nextKeyRaw?.trim() || null;
    const hasLoadedEmptyResultSet = total === 0 && items.length === 0;
    const hasInvalidUrlKey =
      Boolean(nextKey) &&
      (hasLoadedEmptyResultSet ||
        (items.length > 0 && !items.some((item) => item.key === nextKey)));

    preserveSelectionWhenUrlKeyMissing.current = false;
    pendingUrlSync.current = preserveWhenKeyMissing || hasInvalidUrlKey;

    setReportTypeState((prev) => (prev === nextType ? prev : nextType));
    setQueryState((prev) => (prev === nextQuery ? prev : nextQuery));
    setAppliedQueryState((prev) =>
      prev === nextAppliedQuery ? prev : nextAppliedQuery,
    );
    setSelectedKeyState((prev) => {
      if (hasLoadedEmptyResultSet && nextKey) {
        return null;
      }
      return resolveSelectedKeyFromUrl({
        previousSelectedKey: prev,
        nextKeyRaw,
        availableKeys: items.map((item) => item.key),
        preserveSelectionWhenKeyMissing: preserveWhenKeyMissing,
      });
    });
    setShowRawState((prev) => (prev === nextShowRaw ? prev : nextShowRaw));
  }, [items, searchParams, total]);
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => {
    const nextAppliedQuery = query.trim();
    if (nextAppliedQuery === appliedQuery) {
      return;
    }
    const timerId = window.setTimeout(() => {
      pendingUrlSync.current = true;
      setAppliedQueryState(nextAppliedQuery);
    }, 300);
    return () => {
      window.clearTimeout(timerId);
    };
  }, [appliedQuery, query]);

  useEffect(() => {
    if (desiredQueryString === currentQueryString) {
      pendingUrlSync.current = false;
      return;
    }
    if (!pendingUrlSync.current) {
      return;
    }
    const targetUrl = desiredQueryString
      ? `${pathname}?${desiredQueryString}`
      : pathname;
    router.replace(targetUrl, { scroll: false });
  }, [currentQueryString, desiredQueryString, pathname, router]);

  useEffect(() => {
    if (skipInitialListFetch.current) {
      skipInitialListFetch.current = false;
      return;
    }

    let cancelled = false;
    const forceRefresh = refreshToken > consumedListRefreshToken.current;
    if (forceRefresh) {
      consumedListRefreshToken.current = refreshToken;
    }

    const load = async () => {
      setLoadingList(true);
      setError(null);
      setWarnings([]);

      try {
        const typed = await fetchReportsListCached(
          reportType,
          appliedQuery,
          forceRefresh,
        );
        if (cancelled) {
          return;
        }
        setItems(typed.items);
        setTotal(typed.total);
        setSearched(typed.searched);
        setTruncated(typed.truncated);
        setSearchWindow(typed.searchWindow);
        setWarnings(typed.warnings);

        const firstKey = typed.items[0]?.key ?? null;
        setSelectedKeyState((prev) => {
          if (prev && typed.items.some((item) => item.key === prev)) {
            return prev;
          }
          if (prev !== firstKey) {
            pendingUrlSync.current = true;
          }
          return firstKey;
        });
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        const message =
          loadError instanceof Error
            ? loadError.message
            : "Failed to load reports";
        setError(message);
      } finally {
        if (!cancelled) {
          setLoadingList(false);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [appliedQuery, reportType, refreshToken]);

  useEffect(() => {
    if (!selectedKey) {
      return;
    }

    if (skipInitialDetailFetchKey.current === selectedKey) {
      skipInitialDetailFetchKey.current = null;
      return;
    }

    let cancelled = false;
    const forceRefresh = refreshToken > consumedDetailRefreshToken.current;
    if (forceRefresh) {
      consumedDetailRefreshToken.current = refreshToken;
    }
    const loadDetail = async () => {
      setLoadingDetail(true);
      setError(null);

      try {
        const typedPayload = await fetchReportDetailCached(
          selectedKey,
          forceRefresh,
        );
        if (cancelled) {
          return;
        }
        setDetail(typedPayload.report);
      } catch (detailError) {
        if (cancelled) {
          return;
        }
        const message =
          detailError instanceof Error
            ? detailError.message
            : "Failed to load report detail";
        setError(message);
        setDetail(null);
      } finally {
        if (!cancelled) {
          setLoadingDetail(false);
        }
      }
    };

    void loadDetail();

    return () => {
      cancelled = true;
    };
  }, [refreshToken, selectedKey]);

  const selectedDetail = selectedKey ? detail : null;
  const summary = useMemo(
    () => asRecord(selectedDetail?.summary),
    [selectedDetail],
  );
  const buyRows = useMemo(
    () => asRecordArray(selectedDetail?.candidates),
    [selectedDetail],
  );
  const sellRows = useMemo(
    () => asRecordArray(selectedDetail?.evaluated),
    [selectedDetail],
  );
  const entryRows = useMemo(
    () => asRecordArray(selectedDetail?.entries),
    [selectedDetail],
  );
  const aiBriefRows = useMemo(
    () => asRecordArray(selectedDetail?.recommendations),
    [selectedDetail],
  );
  const rawDetailJson = useMemo(
    () =>
      showRaw && selectedDetail ? JSON.stringify(selectedDetail, null, 2) : "",
    [selectedDetail, showRaw],
  );

  const toggleShowRaw = useCallback(() => {
    pendingUrlSync.current = true;
    setShowRawState((prev) => !prev);
  }, []);

  const refreshReports = useCallback(() => {
    setRefreshToken((prev) => prev + 1);
  }, []);

  const setReportType = useCallback((value: ReportsFilterType) => {
    pendingUrlSync.current = true;
    setReportTypeState(value);
  }, []);

  const setQuery = useCallback((value: string) => {
    setQueryState(value);
  }, []);

  const setSelectedKey = useCallback((value: string) => {
    pendingUrlSync.current = true;
    setSelectedKeyState(value);
  }, []);

  return {
    reportType,
    query,
    appliedQuery,
    items,
    total,
    searched,
    truncated,
    searchWindow,
    warnings,
    selectedKey,
    detail: selectedDetail,
    loadingList,
    loadingDetail,
    error,
    showRaw,
    summary,
    buyRows,
    sellRows,
    entryRows,
    aiBriefRows,
    rawDetailJson,
    setReportType,
    setQuery,
    setSelectedKey,
    refreshReports,
    toggleShowRaw,
  };
}
