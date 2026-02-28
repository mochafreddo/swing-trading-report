"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import styles from "./holdings-client.module.css";

import { partitionHoldingsByActivity } from "@/lib/holding-activity";

import { HoldingsFormPanel } from "@/components/holdings/holdings-form-panel";
import { HoldingsTable } from "@/components/holdings/holdings-table";
import { readApiError } from "@/components/holdings/helpers";
import { useHoldingsForm } from "@/components/holdings/use-holdings-form";
import {
  type HoldingsInitialState,
  useHoldingsQuery,
} from "@/components/holdings/use-holdings-query";

interface HoldingsClientProps {
  initialState?: HoldingsInitialState;
}

interface TickerLookupResult {
  ticker: string;
  name: string | null;
}

interface TickerSearchApiPayload {
  results?: unknown;
}

interface RecentCandidatesApiPayload {
  report?: {
    key?: unknown;
    reportDate?: unknown;
  } | null;
  candidates?: unknown;
}

function parseTickerLookupResults(payload: unknown): TickerLookupResult[] {
  if (!Array.isArray(payload)) {
    return [];
  }
  const results: TickerLookupResult[] = [];
  for (const item of payload) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      continue;
    }
    const raw = item as { ticker?: unknown; name?: unknown };
    const ticker =
      typeof raw.ticker === "string" ? raw.ticker.trim().toUpperCase() : "";
    if (!ticker) {
      continue;
    }
    const name = typeof raw.name === "string" ? raw.name.trim() : "";
    results.push({
      ticker,
      name: name || null,
    });
  }
  return results;
}

export function HoldingsClient({ initialState }: HoldingsClientProps) {
  const [showInactive, setShowInactive] = useState(false);
  const [tickerLookupQuery, setTickerLookupQuery] = useState("");
  const [tickerLookupResults, setTickerLookupResults] = useState<
    TickerLookupResult[]
  >([]);
  const [tickerLookupLoading, setTickerLookupLoading] = useState(false);
  const [tickerLookupError, setTickerLookupError] = useState<string | null>(
    null,
  );
  const [recentCandidates, setRecentCandidates] = useState<
    TickerLookupResult[]
  >([]);
  const [recentCandidatesLoading, setRecentCandidatesLoading] = useState(false);
  const [recentCandidatesError, setRecentCandidatesError] = useState<
    string | null
  >(null);
  const [recentCandidatesReportKey, setRecentCandidatesReportKey] = useState<
    string | null
  >(null);
  const [recentCandidatesReportDate, setRecentCandidatesReportDate] = useState<
    string | null
  >(null);
  const {
    items,
    loading,
    loadingMore,
    hasMore,
    error,
    setError,
    refresh,
    loadMore,
  } = useHoldingsQuery(initialState);
  const {
    submitting,
    editingTicker,
    form,
    modeLabel,
    hasUnsavedChanges,
    updateField,
    onSubmit,
    beginEdit,
    cancelEdit,
  } = useHoldingsForm({ refresh, setError });
  const partitioned = useMemo(
    () => partitionHoldingsByActivity(items),
    [items],
  );
  const visibleItems = showInactive ? items : partitioned.active;

  const applyTickerFromLookup = useCallback(
    (ticker: string) => {
      updateField("ticker", ticker);
      setTickerLookupQuery("");
      setTickerLookupResults([]);
      setTickerLookupError(null);
    },
    [updateField],
  );

  useEffect(() => {
    const query = tickerLookupQuery.trim();
    if (!query) {
      setTickerLookupResults([]);
      setTickerLookupLoading(false);
      setTickerLookupError(null);
      return;
    }

    const controller = new AbortController();
    const timerId = window.setTimeout(() => {
      void (async () => {
        setTickerLookupLoading(true);
        setTickerLookupError(null);
        try {
          const params = new URLSearchParams({
            q: query,
            limit: "8",
          });
          const response = await fetch(
            `/api/tickers/search?${params.toString()}`,
            {
              signal: controller.signal,
              cache: "no-store",
            },
          );
          const payload = (await response.json()) as TickerSearchApiPayload;
          if (!response.ok) {
            throw new Error(readApiError(payload) || "Ticker search failed");
          }
          setTickerLookupResults(parseTickerLookupResults(payload.results));
        } catch (searchError) {
          if (controller.signal.aborted) {
            return;
          }
          setTickerLookupResults([]);
          setTickerLookupError(
            searchError instanceof Error
              ? searchError.message
              : "Ticker search failed",
          );
        } finally {
          if (!controller.signal.aborted) {
            setTickerLookupLoading(false);
          }
        }
      })();
    }, 220);

    return () => {
      controller.abort();
      window.clearTimeout(timerId);
    };
  }, [tickerLookupQuery]);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      setRecentCandidatesLoading(true);
      setRecentCandidatesError(null);
      try {
        const params = new URLSearchParams({
          limitReports: "10",
          limitCandidates: "20",
        });
        const response = await fetch(
          `/api/tickers/recent-candidates?${params.toString()}`,
          {
            signal: controller.signal,
            cache: "no-store",
          },
        );
        const payload = (await response.json()) as RecentCandidatesApiPayload;
        if (!response.ok) {
          throw new Error(
            readApiError(payload) || "Failed to load recent buy candidates",
          );
        }
        setRecentCandidates(parseTickerLookupResults(payload.candidates));
        setRecentCandidatesReportKey(
          payload.report && typeof payload.report.key === "string"
            ? payload.report.key
            : null,
        );
        setRecentCandidatesReportDate(
          payload.report && typeof payload.report.reportDate === "string"
            ? payload.report.reportDate
            : null,
        );
      } catch (recentError) {
        if (controller.signal.aborted) {
          return;
        }
        setRecentCandidates([]);
        setRecentCandidatesReportKey(null);
        setRecentCandidatesReportDate(null);
        setRecentCandidatesError(
          recentError instanceof Error
            ? recentError.message
            : "Failed to load recent buy candidates",
        );
      } finally {
        if (!controller.signal.aborted) {
          setRecentCandidatesLoading(false);
        }
      }
    })();

    return () => controller.abort();
  }, []);

  const removeHolding = useCallback(
    async (ticker: string) => {
      const confirmDelete = window.confirm(
        `${ticker} 을(를) 삭제하시겠습니까?`,
      );
      if (!confirmDelete) {
        return;
      }

      setError(null);
      try {
        const response = await fetch(
          `/api/holdings/${encodeURIComponent(ticker)}`,
          {
            method: "DELETE",
          },
        );
        const payload = (await response.json()) as unknown;
        if (!response.ok) {
          throw new Error(readApiError(payload) || "Delete failed");
        }
        if (editingTicker === ticker) {
          cancelEdit();
        }
        await refresh();
      } catch (deleteError) {
        setError(
          deleteError instanceof Error ? deleteError.message : "Delete failed",
        );
      }
    },
    [cancelEdit, editingTicker, refresh, setError],
  );

  return (
    <section className={styles.wrapper}>
      <HoldingsFormPanel
        modeLabel={modeLabel}
        submitting={submitting}
        editingTicker={editingTicker}
        hasUnsavedChanges={hasUnsavedChanges}
        form={form}
        tickerLookupQuery={tickerLookupQuery}
        tickerLookupResults={tickerLookupResults}
        tickerLookupLoading={tickerLookupLoading}
        tickerLookupError={tickerLookupError}
        recentCandidates={recentCandidates}
        recentCandidatesReportKey={recentCandidatesReportKey}
        recentCandidatesReportDate={recentCandidatesReportDate}
        recentCandidatesLoading={recentCandidatesLoading}
        recentCandidatesError={recentCandidatesError}
        onSubmit={onSubmit}
        onCancelEdit={cancelEdit}
        onFieldChange={updateField}
        onTickerLookupQueryChange={setTickerLookupQuery}
        onSelectTicker={applyTickerFromLookup}
      />
      <HoldingsTable
        items={items}
        visibleItems={visibleItems}
        activeCount={partitioned.activeCount}
        inactiveCount={partitioned.inactiveCount}
        showInactive={showInactive}
        loading={loading}
        loadingMore={loadingMore}
        hasMore={hasMore}
        error={error}
        onRefresh={refresh}
        onToggleShowInactive={setShowInactive}
        onEdit={beginEdit}
        onDelete={removeHolding}
        onLoadMore={loadMore}
      />
    </section>
  );
}
