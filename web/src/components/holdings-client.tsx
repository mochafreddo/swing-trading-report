"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  addBuyToHoldingAction,
  deleteHoldingAction,
  saveHoldingAction,
} from "@/app/actions/holdings";

import styles from "./holdings-client.module.css";

import { partitionHoldingsByActivity } from "@/lib/holding-activity";
import type { HoldingRecord } from "@/lib/types";

import {
  type AddBuyFormState,
  type AddBuyPreview,
  HoldingsAddBuyPanel,
} from "@/components/holdings/holdings-add-buy-panel";
import {
  getAddBuyPrecheckError,
  inferRequiredCurrency,
} from "@/components/holdings/add-buy-precheck";
import {
  createAddBuyIdempotencyKey,
  resolveAddBuySubmitError,
} from "@/components/holdings/add-buy-idempotency";
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

function formatTodayLocalDate(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function createEmptyAddBuyForm(): AddBuyFormState {
  return {
    buy_quantity: "",
    buy_price: "",
    buy_date: formatTodayLocalDate(),
  };
}

function parsePositiveNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function roundTo(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function resolveNextEntryDate(
  currentEntryDate: string | null,
  buyDateInput: string,
): string | null {
  const buyDate = buyDateInput.trim();
  if (!buyDate) {
    return currentEntryDate;
  }
  if (!currentEntryDate) {
    return buyDate;
  }
  return buyDate < currentEntryDate ? buyDate : currentEntryDate;
}

function buildAddBuyPreview(
  target: HoldingRecord | null,
  form: AddBuyFormState,
): AddBuyPreview | null {
  if (!target) {
    return null;
  }
  const buyQuantity = parsePositiveNumber(form.buy_quantity);
  const buyPrice = parsePositiveNumber(form.buy_price);
  if (buyQuantity == null || buyPrice == null) {
    return null;
  }

  const nextQuantity = target.quantity + buyQuantity;
  if (!Number.isFinite(nextQuantity) || nextQuantity <= 0) {
    return null;
  }

  const nextEntryPrice =
    target.quantity === 0
      ? buyPrice
      : (target.quantity * target.entry_price + buyQuantity * buyPrice) /
        nextQuantity;

  return {
    next_quantity: roundTo(nextQuantity, 6),
    next_entry_price: roundTo(nextEntryPrice, 4),
    next_entry_date: resolveNextEntryDate(target.entry_date, form.buy_date),
    next_entry_currency:
      target.entry_currency?.trim().toUpperCase() ||
      inferRequiredCurrency(target.ticker),
  };
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
  const [addBuyTicker, setAddBuyTicker] = useState<string | null>(null);
  const [addBuyForm, setAddBuyForm] = useState<AddBuyFormState>(() =>
    createEmptyAddBuyForm(),
  );
  const [addBuyIdempotencyKey, setAddBuyIdempotencyKey] = useState<string>(() =>
    createAddBuyIdempotencyKey(),
  );
  const [addBuySubmitting, setAddBuySubmitting] = useState(false);
  const [addBuyError, setAddBuyError] = useState<string | null>(null);
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
  } = useHoldingsForm({ refresh, saveHolding: saveHoldingAction, setError });
  const partitioned = useMemo(
    () => partitionHoldingsByActivity(items),
    [items],
  );
  const visibleItems = showInactive ? items : partitioned.active;
  const addBuyTarget = useMemo(
    () => items.find((item) => item.ticker === addBuyTicker) ?? null,
    [addBuyTicker, items],
  );
  const addBuyPrecheckError = useMemo(
    () => getAddBuyPrecheckError(addBuyTarget),
    [addBuyTarget],
  );
  const addBuyPreview = useMemo(
    () =>
      addBuyPrecheckError ? null : buildAddBuyPreview(addBuyTarget, addBuyForm),
    [addBuyForm, addBuyPrecheckError, addBuyTarget],
  );

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
        const result = await deleteHoldingAction(ticker);
        if (!result.ok) {
          throw new Error(result.error || "Delete failed");
        }
        if (editingTicker === ticker) {
          cancelEdit();
        }
        if (addBuyTicker === ticker) {
          setAddBuyTicker(null);
          setAddBuyForm(createEmptyAddBuyForm());
          setAddBuyIdempotencyKey(createAddBuyIdempotencyKey());
          setAddBuyError(null);
        }
        await refresh();
      } catch (deleteError) {
        setError(
          deleteError instanceof Error ? deleteError.message : "Delete failed",
        );
      }
    },
    [addBuyTicker, cancelEdit, editingTicker, refresh, setError],
  );

  const beginAddBuy = useCallback(
    (row: HoldingRecord) => {
      setAddBuyTicker(row.ticker);
      setAddBuyForm(createEmptyAddBuyForm());
      setAddBuyIdempotencyKey(createAddBuyIdempotencyKey());
      setAddBuyError(null);
      setError(null);
    },
    [setError],
  );

  const updateAddBuyField = useCallback(
    (field: keyof AddBuyFormState, value: string) => {
      setAddBuyForm((prev) => ({ ...prev, [field]: value }));
      setAddBuyIdempotencyKey(createAddBuyIdempotencyKey());
    },
    [],
  );

  const cancelAddBuy = useCallback(() => {
    setAddBuyTicker(null);
    setAddBuyForm(createEmptyAddBuyForm());
    setAddBuyIdempotencyKey(createAddBuyIdempotencyKey());
    setAddBuyError(null);
  }, []);

  const submitAddBuy = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!addBuyTicker) {
        setAddBuyError("Add Buy 대상 티커를 선택하세요.");
        return;
      }
      if (addBuyPrecheckError) {
        return;
      }

      const buyQuantity = parsePositiveNumber(addBuyForm.buy_quantity);
      const buyPrice = parsePositiveNumber(addBuyForm.buy_price);
      if (buyQuantity == null || buyPrice == null) {
        setAddBuyError("Buy Quantity/Price는 0보다 큰 숫자여야 합니다.");
        return;
      }
      const idempotencyKey = addBuyIdempotencyKey.trim();
      if (!idempotencyKey) {
        setAddBuyError("Idempotency key 생성에 실패했습니다. 다시 시도하세요.");
        return;
      }

      setAddBuySubmitting(true);
      setAddBuyError(null);
      setError(null);
      try {
        const payload: {
          buy_quantity: number;
          buy_price: number;
          buy_date?: string;
        } = {
          buy_quantity: buyQuantity,
          buy_price: buyPrice,
        };
        const buyDate = addBuyForm.buy_date.trim();
        if (buyDate) {
          payload.buy_date = buyDate;
        }

        const result = await addBuyToHoldingAction({
          ticker: addBuyTicker,
          idempotencyKey,
          payload,
        });
        if (!result.ok) {
          const message = result.error || "Add buy failed";
          const code = result.code;
          throw Object.assign(new Error(message), {
            code,
          });
        }

        setAddBuyTicker(null);
        setAddBuyForm(createEmptyAddBuyForm());
        setAddBuyIdempotencyKey(createAddBuyIdempotencyKey());
        await refresh();
      } catch (addBuySubmitError) {
        const resolvedError = resolveAddBuySubmitError(addBuySubmitError);
        if (resolvedError.shouldRotateIdempotencyKey) {
          setAddBuyIdempotencyKey(createAddBuyIdempotencyKey());
        }
        setAddBuyError(resolvedError.message);
      } finally {
        setAddBuySubmitting(false);
      }
    },
    [
      addBuyForm,
      addBuyIdempotencyKey,
      addBuyPrecheckError,
      addBuyTicker,
      refresh,
      setError,
    ],
  );

  return (
    <section className={styles.wrapper}>
      <div className={styles.sidebar}>
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
        <HoldingsAddBuyPanel
          target={addBuyTarget}
          form={addBuyForm}
          submitting={addBuySubmitting}
          error={addBuyError}
          precheckError={addBuyPrecheckError}
          preview={addBuyPreview}
          onFieldChange={updateAddBuyField}
          onSubmit={submitAddBuy}
          onCancel={cancelAddBuy}
        />
      </div>
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
        onAddBuy={beginAddBuy}
        onDelete={removeHolding}
        onLoadMore={loadMore}
      />
    </section>
  );
}
