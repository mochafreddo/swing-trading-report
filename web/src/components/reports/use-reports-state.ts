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
import type {
  ReportJson,
  ReportsFilterType,
  ReportsInitialState,
} from "./types";

const PAGE_LIMIT = 30;

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
  const skipInitialListFetch = useRef(Boolean(initialState));
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
    const nextKey = nextKeyRaw && nextKeyRaw.trim() ? nextKeyRaw : null;
    const nextShowRaw = searchParams.get("raw") === "1";

    setReportType((prev) => (prev === nextType ? prev : nextType));
    setQuery((prev) => (prev === nextQuery ? prev : nextQuery));
    setAppliedQuery((prev) =>
      prev === nextAppliedQuery ? prev : nextAppliedQuery,
    );
    setSelectedKey((prev) => {
      if (!nextKey) {
        return prev;
      }
      if (items.length > 0 && !items.some((item) => item.key === nextKey)) {
        return prev;
      }
      return prev === nextKey ? prev : nextKey;
    });
    setShowRaw((prev) => (prev === nextShowRaw ? prev : nextShowRaw));
  }, [items, searchParams]);

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

    const controller = new AbortController();

    const load = async () => {
      setLoadingList(true);
      setError(null);
      setWarnings([]);

      try {
        const params = new URLSearchParams({
          type: reportType,
          limit: String(PAGE_LIMIT),
        });
        if (appliedQuery) {
          params.set("q", appliedQuery);
        }

        const response = await fetch(`/api/reports?${params.toString()}`, {
          signal: controller.signal,
          cache: "no-store",
        });
        const payload = (await response.json()) as unknown;

        if (!response.ok) {
          throw new Error(readApiError(payload) || "Failed to load reports");
        }

        const typed = payload as ReportsListResponse;
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
        if (controller.signal.aborted) {
          return;
        }
        const message =
          loadError instanceof Error
            ? loadError.message
            : "Failed to load reports";
        setError(message);
      } finally {
        if (!controller.signal.aborted) {
          setLoadingList(false);
        }
      }
    };

    void load();

    return () => controller.abort();
  }, [appliedQuery, reportType]);

  useEffect(() => {
    if (!selectedKey) {
      setDetail(null);
      return;
    }

    if (skipInitialDetailFetchKey.current === selectedKey) {
      skipInitialDetailFetchKey.current = null;
      return;
    }

    const controller = new AbortController();
    const loadDetail = async () => {
      setLoadingDetail(true);
      setError(null);

      try {
        const params = new URLSearchParams({ key: selectedKey });
        const response = await fetch(
          `/api/reports/detail?${params.toString()}`,
          {
            signal: controller.signal,
            cache: "no-store",
          },
        );
        const payload = (await response.json()) as unknown;

        if (!response.ok) {
          throw new Error(
            readApiError(payload) || "Failed to load report detail",
          );
        }

        const typedPayload = payload as { key: string; report: ReportJson };
        setDetail(typedPayload.report);
      } catch (detailError) {
        if (controller.signal.aborted) {
          return;
        }
        const message =
          detailError instanceof Error
            ? detailError.message
            : "Failed to load report detail";
        setError(message);
        setDetail(null);
      } finally {
        if (!controller.signal.aborted) {
          setLoadingDetail(false);
        }
      }
    };

    void loadDetail();

    return () => controller.abort();
  }, [selectedKey]);

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
    toggleShowRaw,
  };
}
