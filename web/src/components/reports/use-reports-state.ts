import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

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
const LIST_CACHE_TTL_MS = 5_000;
const SEARCH_CACHE_TTL_MS = 10_000;
const DETAIL_CACHE_TTL_MS = 60 * 60 * 1000;
const LIST_CACHE_MAX_ENTRIES = 100;
const DETAIL_CACHE_MAX_ENTRIES = 200;

interface TimedCacheEntry<T> {
  value: T;
  expiresAt: number;
}

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

const reportListCache = new Map<string, TimedCacheEntry<ReportsListResponse>>();
const reportListInFlight = new Map<string, Promise<ReportsListResponse>>();
const reportDetailCache = new Map<
  string,
  TimedCacheEntry<ReportDetailResponse>
>();
const reportDetailInFlight = new Map<string, Promise<ReportDetailResponse>>();

function readTimedCache<T>(
  cache: Map<string, TimedCacheEntry<T>>,
  key: string,
): T | null {
  const entry = cache.get(key);
  if (!entry) {
    return null;
  }
  if (entry.expiresAt <= Date.now()) {
    cache.delete(key);
    return null;
  }
  return entry.value;
}

function writeTimedCache<T>(
  cache: Map<string, TimedCacheEntry<T>>,
  key: string,
  value: T,
  ttlMs: number,
  maxEntries: number,
): void {
  cache.set(key, {
    value,
    expiresAt: Date.now() + ttlMs,
  });
  while (cache.size > maxEntries) {
    const oldestKey = cache.keys().next().value;
    if (typeof oldestKey !== "string") {
      break;
    }
    cache.delete(oldestKey);
  }
}

function resolveListCacheTtlMs(query: string): number {
  return query.trim() ? SEARCH_CACHE_TTL_MS : LIST_CACHE_TTL_MS;
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

async function fetchReportsListCached(
  reportType: ReportsFilterType,
  appliedQuery: string,
  refresh = false,
): Promise<ReportsListResponse> {
  const cacheKey = buildListCacheKey(reportType, appliedQuery);
  if (!refresh) {
    const cached = readTimedCache(reportListCache, cacheKey);
    if (cached) {
      return cached;
    }

    const inFlight = reportListInFlight.get(cacheKey);
    if (inFlight) {
      return inFlight;
    }
  }

  const load = async () => {
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

    const typed = payload as ReportsListResponse;
    writeTimedCache(
      reportListCache,
      cacheKey,
      typed,
      resolveListCacheTtlMs(appliedQuery),
      LIST_CACHE_MAX_ENTRIES,
    );
    return typed;
  };

  if (refresh) {
    return load();
  }

  const loadPromise = load();

  reportListInFlight.set(cacheKey, loadPromise);
  try {
    return await loadPromise;
  } finally {
    reportListInFlight.delete(cacheKey);
  }
}

async function fetchReportDetailCached(
  key: string,
  refresh = false,
): Promise<ReportDetailResponse> {
  if (!refresh) {
    const cached = readTimedCache(reportDetailCache, key);
    if (cached) {
      return cached;
    }

    const inFlight = reportDetailInFlight.get(key);
    if (inFlight) {
      return inFlight;
    }
  }

  const load = async () => {
    const path = buildReportDetailRequestPath({
      key,
      refresh,
    });
    const response = await fetch(path, {
      cache: "no-store",
    });
    const payload = (await response.json()) as unknown;
    if (!response.ok) {
      throw new Error(readApiError(payload) || "Failed to load report detail");
    }
    const typed = payload as ReportDetailResponse;
    writeTimedCache(
      reportDetailCache,
      key,
      typed,
      DETAIL_CACHE_TTL_MS,
      DETAIL_CACHE_MAX_ENTRIES,
    );
    return typed;
  };

  if (refresh) {
    return load();
  }

  const loadPromise = load();

  reportDetailInFlight.set(key, loadPromise);
  try {
    return await loadPromise;
  } finally {
    reportDetailInFlight.delete(key);
  }
}

export function useReportsState(initialState?: ReportsInitialState) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [reportType, setReportType] = useState<ReportsFilterType>(
    () => initialState?.reportType ?? parseReportType(searchParams.get("type")),
  );
  const [query, setQuery] = useState(
    () => initialState?.query ?? searchParams.get("q") ?? "",
  );
  const [appliedQuery, setAppliedQuery] = useState(
    () => initialState?.appliedQuery ?? (searchParams.get("q") ?? "").trim(),
  );
  const [items, setItems] = useState<ReportListItem[]>(
    () => initialState?.items ?? [],
  );
  const [total, setTotal] = useState(() => initialState?.total ?? 0);
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
  const [selectedKey, setSelectedKey] = useState<string | null>(
    () => initialState?.selectedKey ?? searchParams.get("key"),
  );
  const [detail, setDetail] = useState<ReportJson | null>(
    () => initialState?.detail ?? null,
  );
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(
    () => initialState?.showRaw ?? searchParams.get("raw") === "1",
  );
  const [refreshToken, setRefreshToken] = useState(0);
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

  const desiredQueryString = useMemo(() => {
    const params = new URLSearchParams();
    if (reportType !== "all") {
      params.set("type", reportType);
    }
    if (appliedQuery) {
      params.set("q", appliedQuery);
    }
    if (selectedKey) {
      params.set("key", selectedKey);
    }
    if (showRaw) {
      params.set("raw", "1");
    }
    return params.toString();
  }, [appliedQuery, reportType, selectedKey, showRaw]);

  const currentQueryString = useMemo(() => {
    const params = new URLSearchParams();
    const currentType = parseReportType(searchParams.get("type"));
    const currentQuery = (searchParams.get("q") ?? "").trim();
    const currentKey = searchParams.get("key");
    const currentRaw = searchParams.get("raw") === "1";
    if (currentType !== "all") {
      params.set("type", currentType);
    }
    if (currentQuery) {
      params.set("q", currentQuery);
    }
    if (currentKey) {
      params.set("key", currentKey);
    }
    if (currentRaw) {
      params.set("raw", "1");
    }
    return params.toString();
  }, [searchParams]);

  useEffect(() => {
    const nextType = parseReportType(searchParams.get("type"));
    const nextQuery = searchParams.get("q") ?? "";
    const nextAppliedQuery = nextQuery.trim();
    const nextKeyRaw = searchParams.get("key");
    const nextShowRaw = searchParams.get("raw") === "1";

    setReportType((prev) => (prev === nextType ? prev : nextType));
    setQuery((prev) => (prev === nextQuery ? prev : nextQuery));
    setAppliedQuery((prev) =>
      prev === nextAppliedQuery ? prev : nextAppliedQuery,
    );
    setSelectedKey((prev) =>
      resolveSelectedKeyFromUrl({
        previousSelectedKey: prev,
        nextKeyRaw,
      }),
    );
    setShowRaw((prev) => (prev === nextShowRaw ? prev : nextShowRaw));
  }, [searchParams]);

  useEffect(() => {
    const nextAppliedQuery = query.trim();
    if (nextAppliedQuery === appliedQuery) {
      return;
    }
    const timerId = window.setTimeout(() => {
      setAppliedQuery(nextAppliedQuery);
    }, 300);
    return () => {
      window.clearTimeout(timerId);
    };
  }, [appliedQuery, query]);

  useEffect(() => {
    if (desiredQueryString === currentQueryString) {
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
        setSelectedKey((prev) => {
          if (prev && typed.items.some((item) => item.key === prev)) {
            return prev;
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
      setDetail(null);
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

  const summary = useMemo(() => asRecord(detail?.summary), [detail]);
  const buyRows = useMemo(() => asRecordArray(detail?.candidates), [detail]);
  const sellRows = useMemo(() => asRecordArray(detail?.evaluated), [detail]);
  const rawDetailJson = useMemo(
    () => (showRaw && detail ? JSON.stringify(detail, null, 2) : ""),
    [detail, showRaw],
  );

  const toggleShowRaw = useCallback(() => {
    setShowRaw((prev) => !prev);
  }, []);

  const refreshReports = useCallback(() => {
    setRefreshToken((prev) => prev + 1);
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
    detail,
    loadingList,
    loadingDetail,
    error,
    showRaw,
    summary,
    buyRows,
    sellRows,
    rawDetailJson,
    setReportType,
    setQuery,
    setSelectedKey,
    refreshReports,
    toggleShowRaw,
  };
}
