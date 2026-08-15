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
import { runJournalV0Schema } from "@/lib/decision-board-journal-schema";
import type {
  DecisionBoardJournalStatus,
  ReportListItem,
  ReportsListResponse,
  ReportSearchWarning,
  DecisionBoardRunKind,
} from "@/lib/types";

import {
  asRecord,
  asRecordArray,
  parseDecisionBoardRunKind,
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

type ReportDetailResponse = {
  key: string;
  bucketId: string;
  report: ReportJson;
};

interface ReportsListRequestPathOptions {
  type: ReportsFilterType;
  runKind?: DecisionBoardRunKind;
  limit: number;
  query: string;
  refresh?: boolean;
}

interface ReportDetailRequestPathOptions {
  key: string;
  bucketId?: string | null;
  refresh?: boolean;
}

export function parseDecisionBoardJournalStatusPayload(
  value: unknown,
): DecisionBoardJournalStatus | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (record.state === "UNAVAILABLE") {
    if (
      Object.keys(record).some(
        (key) => !["state", "reason", "records"].includes(key),
      ) ||
      (record.reason !== "NOT_CONFIGURED" &&
        record.reason !== "UNSAFE_OR_INVALID") ||
      !Array.isArray(record.records) ||
      record.records.length !== 0
    ) {
      return null;
    }
    return {
      state: "UNAVAILABLE",
      reason: record.reason,
      records: [],
    };
  }
  if (
    record.state !== "AVAILABLE" ||
    Object.keys(record).some((key) => !["state", "records"].includes(key)) ||
    !Array.isArray(record.records) ||
    record.records.length > 100
  ) {
    return null;
  }
  const records = [];
  for (const candidate of record.records) {
    const parsed = runJournalV0Schema.safeParse(candidate);
    if (
      !parsed.success ||
      (parsed.data.status !== "MISSED_EXPECTED" &&
        parsed.data.status !== "STALE_INCOMPLETE")
    ) {
      return null;
    }
    records.push(parsed.data);
  }
  return { state: "AVAILABLE", records };
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
  if (options.type === "decision-board" && options.runKind) {
    params.set("runKind", options.runKind);
  }
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
  if (options.bucketId) {
    params.set("bucket", options.bucketId);
  }
  if (options.refresh) {
    params.set("refresh", "1");
  }
  return `/api/reports/detail?${params.toString()}`;
}

interface ReportsStateQueryInput {
  reportType: ReportsFilterType;
  runKind: DecisionBoardRunKind | null;
  appliedQuery: string;
  selectedKey: string | null;
  selectedBucketId: string | null;
  showRaw: boolean;
}

export function buildReportsStateQueryString(
  input: ReportsStateQueryInput,
): string {
  const params = new URLSearchParams();
  if (input.reportType !== "all") {
    params.set("type", input.reportType);
  }
  if (input.reportType === "decision-board" && input.runKind) {
    params.set("runKind", input.runKind);
  }
  if (input.appliedQuery) {
    params.set("q", input.appliedQuery);
  }
  if (input.selectedKey) {
    params.set("key", input.selectedKey);
    if (input.selectedBucketId) {
      params.set("bucket", input.selectedBucketId);
    }
  }
  if (input.showRaw) {
    params.set("raw", "1");
  }
  return params.toString();
}

async function fetchReportsListCached(
  reportType: ReportsFilterType,
  runKind: DecisionBoardRunKind | null,
  appliedQuery: string,
  refresh = false,
): Promise<ReportsListResponse> {
  const cacheKey = `${buildListCacheKey(reportType, appliedQuery)}&runKind=${runKind ?? ""}`;

  return reportListCache.getOrLoad({
    key: cacheKey,
    ttlMs: resolveListCacheTtlMs(appliedQuery),
    refresh,
    load: async () => {
      const path = buildReportsListRequestPath({
        type: reportType,
        ...(runKind ? { runKind } : {}),
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
  bucketId: string | null,
  refresh = false,
): Promise<ReportDetailResponse> {
  return reportDetailCache.getOrLoad({
    key: `bucket=${bucketId ?? ""}&key=${key}`,
    ttlMs: REPORT_DETAIL_CACHE_TTL_MS,
    refresh,
    load: async () => {
      const path = buildReportDetailRequestPath({
        key,
        bucketId,
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
  const initialUrlReportType = parseReportType(searchParams.get("type"));
  const initialUrlRunKind =
    initialUrlReportType === "decision-board"
      ? (parseDecisionBoardRunKind(searchParams.get("runKind")) ?? "ENTRY")
      : null;
  const initialUrlKey = resolveSelectedKeyFromUrl({
    previousSelectedKey: null,
    nextKeyRaw: searchParams.get("key"),
    reportType: initialUrlReportType,
    runKind: initialUrlRunKind,
  });
  const initialUrlBucketId = (searchParams.get("bucket") ?? "").trim() || null;
  const [reportType, setReportTypeState] = useState<ReportsFilterType>(
    () => initialState?.reportType ?? initialUrlReportType,
  );
  const [runKind, setRunKindState] = useState<DecisionBoardRunKind | null>(
    () => {
      if (initialState) {
        return initialState.runKind;
      }
      return initialUrlRunKind;
    },
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
    initialState ? initialState.selectedKey : initialUrlKey,
  );
  const [selectedBucketId, setSelectedBucketIdState] = useState<string | null>(
    () => (initialState ? initialState.selectedBucketId : initialUrlBucketId),
  );
  const [detail, setDetail] = useState<ReportJson | null>(
    () => initialState?.detail ?? null,
  );
  const [detailKey, setDetailKey] = useState<string | null>(
    () => initialState?.detailKey ?? null,
  );
  const [detailBucketId, setDetailBucketId] = useState<string | null>(
    () => initialState?.detailBucketId ?? null,
  );
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRawState] = useState(
    () => initialState?.showRaw ?? searchParams.get("raw") === "1",
  );
  const [journalStatus, setJournalStatus] =
    useState<DecisionBoardJournalStatus>(
      () =>
        initialState?.journalStatus ?? {
          state: "UNAVAILABLE",
          reason: "NOT_CONFIGURED",
          records: [],
        },
    );
  const [refreshToken, setRefreshToken] = useState(0);
  const currentUrlKeyRef = useRef(initialUrlKey);
  const currentUrlBucketIdRef = useRef(initialUrlBucketId);
  const selectedKeyRef = useRef(selectedKey);
  const selectedBucketIdRef = useRef(selectedBucketId);
  const pendingUrlSync = useRef(
    Boolean(initialState) &&
      (initialState?.reportType !== parseReportType(searchParams.get("type")) ||
        initialState?.runKind !==
          (parseReportType(searchParams.get("type")) === "decision-board"
            ? (parseDecisionBoardRunKind(searchParams.get("runKind")) ??
              "ENTRY")
            : null) ||
        initialState?.appliedQuery !== (searchParams.get("q") ?? "").trim() ||
        initialState?.selectedKey !== initialUrlKey ||
        initialState?.selectedBucketId !== initialUrlBucketId ||
        initialState?.showRaw !== (searchParams.get("raw") === "1")),
  );
  const preserveSelectionWhenUrlKeyMissing = useRef(
    Boolean(initialState?.selectedKey && !searchParams.get("key")),
  );
  const skipInitialListFetch = useRef(Boolean(initialState));
  const skipInitialJournalFetch = useRef(
    Boolean(initialState && initialState.reportType === "decision-board"),
  );
  const consumedListRefreshToken = useRef(0);
  const consumedDetailRefreshToken = useRef(0);
  const skipInitialDetailFetchKey = useRef<string | null>(
    initialState?.detail &&
      initialState.detailKey &&
      (initialState.selectedBucketId === null ||
        initialState.detailBucketId === initialState.selectedBucketId) &&
      initialState.detailKey === initialState.selectedKey
      ? initialState.selectedKey
      : null,
  );

  useEffect(() => {
    selectedKeyRef.current = selectedKey;
    selectedBucketIdRef.current = selectedBucketId;
  });

  const desiredQueryString = useMemo(
    () =>
      buildReportsStateQueryString({
        reportType,
        runKind,
        appliedQuery,
        selectedKey,
        selectedBucketId,
        showRaw,
      }),
    [appliedQuery, reportType, runKind, selectedBucketId, selectedKey, showRaw],
  );

  const currentQueryString = useMemo(
    () =>
      buildReportsStateQueryString({
        reportType: parseReportType(searchParams.get("type")),
        runKind:
          parseReportType(searchParams.get("type")) === "decision-board"
            ? (parseDecisionBoardRunKind(searchParams.get("runKind")) ??
              "ENTRY")
            : null,
        appliedQuery: (searchParams.get("q") ?? "").trim(),
        selectedKey: searchParams.get("key"),
        selectedBucketId: (searchParams.get("bucket") ?? "").trim() || null,
        showRaw: searchParams.get("raw") === "1",
      }),
    [searchParams],
  );

  /* eslint-disable react-hooks/set-state-in-effect -- URL search params are an external source; this reconciles browser navigation with optimistic local report state. */
  useEffect(() => {
    const nextType = parseReportType(searchParams.get("type"));
    const nextRunKind =
      nextType === "decision-board"
        ? (parseDecisionBoardRunKind(searchParams.get("runKind")) ?? "ENTRY")
        : null;
    const nextQuery = searchParams.get("q") ?? "";
    const nextAppliedQuery = nextQuery.trim();
    const nextKeyRaw = searchParams.get("key");
    const nextBucketId = (searchParams.get("bucket") ?? "").trim() || null;
    const nextShowRaw = searchParams.get("raw") === "1";
    const preserveWhenKeyMissing = preserveSelectionWhenUrlKeyMissing.current;
    const nextKey = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw,
      reportType: nextType,
      runKind: nextRunKind,
    });
    currentUrlKeyRef.current = nextKey;
    currentUrlBucketIdRef.current = nextBucketId;
    const hasLoadedEmptyResultSet = total === 0 && items.length === 0;
    const hasPrefetchedUrlDetail =
      nextKey !== null &&
      detailKey === nextKey &&
      (nextBucketId === null || detailBucketId === nextBucketId);
    const hasInvalidUrlKey =
      Boolean(nextKey) && hasLoadedEmptyResultSet && !hasPrefetchedUrlDetail;

    preserveSelectionWhenUrlKeyMissing.current = false;
    pendingUrlSync.current = preserveWhenKeyMissing || hasInvalidUrlKey;

    setReportTypeState((prev) => (prev === nextType ? prev : nextType));
    setRunKindState((prev) => (prev === nextRunKind ? prev : nextRunKind));
    setQueryState((prev) => (prev === nextQuery ? prev : nextQuery));
    setAppliedQueryState((prev) =>
      prev === nextAppliedQuery ? prev : nextAppliedQuery,
    );
    setSelectedKeyState((prev) => {
      if (hasInvalidUrlKey) {
        return null;
      }
      return resolveSelectedKeyFromUrl({
        previousSelectedKey: prev,
        nextKeyRaw,
        reportType: nextType,
        runKind: nextRunKind,
        availableKeys: items.map((item) => item.key),
        preserveSelectionWhenKeyMissing: preserveWhenKeyMissing,
      });
    });
    setSelectedBucketIdState((prev) => {
      if (hasInvalidUrlKey) {
        return null;
      }
      if (nextKey) {
        if (nextBucketId) {
          return prev === nextBucketId ? prev : nextBucketId;
        }
        const matchingItems = items.filter((item) => item.key === nextKey);
        if (matchingItems.length === 1) {
          return prev === matchingItems[0].bucketId
            ? prev
            : matchingItems[0].bucketId;
        }
        return prev === null ? prev : null;
      }
      if (preserveWhenKeyMissing) {
        return prev;
      }
      return prev === null ? prev : null;
    });
    setShowRawState((prev) => (prev === nextShowRaw ? prev : nextShowRaw));
  }, [detailBucketId, detailKey, items, searchParams, total]);
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
      setItems([]);
      setTotal(null);
      setSearched(0);
      setTruncated(false);
      setWarnings([]);

      try {
        const typed = await fetchReportsListCached(
          reportType,
          runKind,
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

        const firstItem = typed.items[0] ?? null;
        const firstKey = firstItem?.key ?? null;
        const firstBucketId = firstItem?.bucketId ?? null;
        setSelectedKeyState((prev) => {
          const explicitUrlKey = currentUrlKeyRef.current;
          if (explicitUrlKey) {
            return prev === explicitUrlKey ? prev : explicitUrlKey;
          }
          if (prev && typed.items.some((item) => item.key === prev)) {
            return prev;
          }
          if (prev !== firstKey) {
            pendingUrlSync.current = true;
          }
          return firstKey;
        });
        setSelectedBucketIdState((prev) => {
          const explicitUrlKey = currentUrlKeyRef.current;
          const explicitUrlBucketId = currentUrlBucketIdRef.current;
          if (explicitUrlKey) {
            if (explicitUrlBucketId) {
              return prev === explicitUrlBucketId ? prev : explicitUrlBucketId;
            }
            const matches = typed.items.filter(
              (item) => item.key === explicitUrlKey,
            );
            const bucketId = matches.length === 1 ? matches[0].bucketId : null;
            return prev === bucketId ? prev : bucketId;
          }

          const currentSelectedKey = selectedKeyRef.current;
          const currentSelectedBucketId = selectedBucketIdRef.current;
          if (
            currentSelectedKey &&
            currentSelectedBucketId &&
            typed.items.some(
              (item) =>
                item.key === currentSelectedKey &&
                item.bucketId === currentSelectedBucketId,
            )
          ) {
            return prev === currentSelectedBucketId
              ? prev
              : currentSelectedBucketId;
          }

          if (prev !== firstBucketId) {
            pendingUrlSync.current = true;
          }
          return firstBucketId;
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
  }, [appliedQuery, reportType, refreshToken, runKind]);

  useEffect(() => {
    if (reportType !== "decision-board") {
      return;
    }
    if (skipInitialJournalFetch.current) {
      skipInitialJournalFetch.current = false;
      return;
    }
    let cancelled = false;
    const loadJournal = async () => {
      try {
        const response = await fetch("/api/reports/decision-board-journal", {
          cache: "no-store",
        });
        const payload = parseDecisionBoardJournalStatusPayload(
          await response.json(),
        );
        if (!cancelled) {
          setJournalStatus(
            response.ok && payload
              ? payload
              : {
                  state: "UNAVAILABLE",
                  reason: "UNSAFE_OR_INVALID",
                  records: [],
                },
          );
        }
      } catch {
        if (!cancelled) {
          setJournalStatus({
            state: "UNAVAILABLE",
            reason: "UNSAFE_OR_INVALID",
            records: [],
          });
        }
      }
    };
    void loadJournal();
    return () => {
      cancelled = true;
    };
  }, [refreshToken, reportType]);

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
          selectedBucketId,
          forceRefresh,
        );
        if (cancelled) {
          return;
        }
        setDetail(typedPayload.report);
        setDetailKey(typedPayload.key);
        setDetailBucketId(typedPayload.bucketId);
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
        setDetailKey(null);
        setDetailBucketId(null);
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
  }, [refreshToken, selectedBucketId, selectedKey]);

  const selectedKeyInCurrentScope =
    selectedKey !== null &&
    resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: selectedKey,
      reportType,
      runKind,
    }) === selectedKey;
  const selectedDetail =
    selectedKeyInCurrentScope &&
    selectedKey &&
    detailKey === selectedKey &&
    (selectedBucketId === null || detailBucketId === selectedBucketId)
      ? detail
      : null;
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
    currentUrlKeyRef.current = null;
    currentUrlBucketIdRef.current = null;
    selectedKeyRef.current = null;
    selectedBucketIdRef.current = null;
    setReportTypeState(value);
    setRunKindState(value === "decision-board" ? "ENTRY" : null);
    setSelectedKeyState(null);
    setSelectedBucketIdState(null);
    setDetail(null);
    setDetailKey(null);
    setDetailBucketId(null);
  }, []);

  const setRunKind = useCallback((value: DecisionBoardRunKind) => {
    pendingUrlSync.current = true;
    currentUrlKeyRef.current = null;
    currentUrlBucketIdRef.current = null;
    selectedKeyRef.current = null;
    selectedBucketIdRef.current = null;
    setRunKindState(value);
    setSelectedKeyState(null);
    setSelectedBucketIdState(null);
    setDetail(null);
    setDetailKey(null);
    setDetailBucketId(null);
  }, []);

  const setQuery = useCallback((value: string) => {
    setQueryState(value);
  }, []);

  const setSelectedKey = useCallback((value: string, bucketId?: string) => {
    pendingUrlSync.current = true;
    setSelectedKeyState(value);
    setSelectedBucketIdState(bucketId ?? null);
  }, []);

  return {
    reportType,
    runKind,
    query,
    appliedQuery,
    items,
    total,
    searched,
    truncated,
    searchWindow,
    warnings,
    selectedKey,
    selectedBucketId,
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
    journalStatus,
    setReportType,
    setRunKind,
    setQuery,
    setSelectedKey,
    refreshReports,
    toggleShowRaw,
  };
}
