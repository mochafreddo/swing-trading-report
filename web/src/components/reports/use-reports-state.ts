import { useCallback, useEffect, useMemo, useState } from "react";
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
import type { ReportJson, ReportsFilterType } from "./types";

const PAGE_LIMIT = 30;

export function useReportsState() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [reportType, setReportType] = useState<ReportsFilterType>(() =>
    parseReportType(searchParams.get("type")),
  );
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [appliedQuery, setAppliedQuery] = useState(() =>
    (searchParams.get("q") ?? "").trim(),
  );
  const [items, setItems] = useState<ReportListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [searched, setSearched] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [searchWindow, setSearchWindow] = useState(100);
  const [warnings, setWarnings] = useState<ReportSearchWarning[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(() =>
    searchParams.get("key"),
  );
  const [detail, setDetail] = useState<ReportJson | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRaw, setShowRaw] = useState(() => searchParams.get("raw") === "1");

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
    const nextKey = searchParams.get("key");
    const nextShowRaw = searchParams.get("raw") === "1";

    setReportType((prev) => (prev === nextType ? prev : nextType));
    setQuery((prev) => (prev === nextQuery ? prev : nextQuery));
    setAppliedQuery((prev) =>
      prev === nextAppliedQuery ? prev : nextAppliedQuery,
    );
    setSelectedKey((prev) => (prev === nextKey ? prev : nextKey));
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

        setDetail((payload as { report: ReportJson }).report);
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
    () => (detail ? JSON.stringify(detail, null, 2) : ""),
    [detail],
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
