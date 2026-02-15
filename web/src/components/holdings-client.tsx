"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import styles from "./holdings-client.module.css";

import {
  isActiveHoldingQuantity,
  partitionHoldingsByActivity
} from "@/lib/holding-activity";
import type { HoldingRecord, HoldingsListResponse } from "@/lib/types";

interface HoldingFormState {
  ticker: string;
  quantity: string;
  entry_price: string;
  entry_currency: string;
  entry_date: string;
  strategy: string;
  notes: string;
  tags: string;
  stop_override: string;
  target_override: string;
}

const EMPTY_FORM: HoldingFormState = {
  ticker: "",
  quantity: "",
  entry_price: "",
  entry_currency: "",
  entry_date: "",
  strategy: "",
  notes: "",
  tags: "",
  stop_override: "",
  target_override: ""
};

const HOLDINGS_PAGE_SIZE = 100;

function numberOrUndefined(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
}

function requiredNumber(value: string, label: string): number {
  const parsed = numberOrUndefined(value);
  if (parsed == null) {
    throw new Error(`${label} 값이 올바르지 않습니다.`);
  }
  return parsed;
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

function stringOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function recordToForm(record: HoldingRecord): HoldingFormState {
  return {
    ticker: record.ticker,
    quantity: String(record.quantity),
    entry_price: String(record.entry_price),
    entry_currency: record.entry_currency ?? "",
    entry_date: record.entry_date ?? "",
    strategy: record.strategy ?? "",
    notes: record.notes ?? "",
    tags: record.tags.join(", "),
    stop_override:
      record.stop_override == null ? "" : String(record.stop_override),
    target_override:
      record.target_override == null ? "" : String(record.target_override)
  };
}

function buildCreatePayload(form: HoldingFormState) {
  return {
    ticker: form.ticker,
    quantity: requiredNumber(form.quantity, "Quantity"),
    entry_price: requiredNumber(form.entry_price, "Entry Price"),
    entry_currency: stringOrNull(form.entry_currency),
    entry_date: stringOrNull(form.entry_date),
    strategy: stringOrNull(form.strategy),
    notes: stringOrNull(form.notes),
    tags: form.tags,
    stop_override: numberOrNull(form.stop_override),
    target_override: numberOrNull(form.target_override)
  };
}

function buildPatchPayload(form: HoldingFormState) {
  return {
    quantity: requiredNumber(form.quantity, "Quantity"),
    entry_price: requiredNumber(form.entry_price, "Entry Price"),
    entry_currency: stringOrNull(form.entry_currency),
    entry_date: stringOrNull(form.entry_date),
    strategy: stringOrNull(form.strategy),
    notes: stringOrNull(form.notes),
    tags: form.tags,
    stop_override: numberOrNull(form.stop_override),
    target_override: numberOrNull(form.target_override)
  };
}

function readApiError(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  const value = (payload as { error?: unknown }).error;
  return typeof value === "string" && value.trim() ? value : undefined;
}

function mergeHoldingsByTicker(
  current: HoldingRecord[],
  incoming: HoldingRecord[]
): HoldingRecord[] {
  const merged = [...current, ...incoming];
  const seen = new Set<string>();
  return merged.filter((item) => {
    if (seen.has(item.ticker)) {
      return false;
    }
    seen.add(item.ticker);
    return true;
  });
}

export function HoldingsClient() {
  const [items, setItems] = useState<HoldingRecord[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingTicker, setEditingTicker] = useState<string | null>(null);
  const [form, setForm] = useState<HoldingFormState>(EMPTY_FORM);
  const [baselineForm, setBaselineForm] = useState<HoldingFormState>(EMPTY_FORM);

  const modeLabel = useMemo(
    () => (editingTicker ? `Edit ${editingTicker}` : "Create Holding"),
    [editingTicker]
  );
  const partitioned = useMemo(
    () => partitionHoldingsByActivity(items),
    [items]
  );
  const visibleItems = showInactive ? items : partitioned.active;
  const hasUnsavedChanges = useMemo(
    () =>
      !submitting && JSON.stringify(form) !== JSON.stringify(baselineForm),
    [baselineForm, form, submitting]
  );

  const fetchPage = useCallback(
    async (cursor?: string | null): Promise<HoldingsListResponse> => {
      const params = new URLSearchParams({
        limit: String(HOLDINGS_PAGE_SIZE)
      });
      if (cursor) {
        params.set("cursor", cursor);
      }

      const response = await fetch(`/api/holdings?${params.toString()}`, {
        cache: "no-store"
      });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(readApiError(payload) || "Failed to load holdings");
      }

      return payload as HoldingsListResponse;
    },
    []
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadingMore(false);
    setError(null);

    try {
      const page = await fetchPage();
      setItems(page.items);
      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load holdings");
    } finally {
      setLoading(false);
    }
  }, [fetchPage]);

  const loadMore = useCallback(async () => {
    if (!hasMore || !nextCursor || loadingMore) {
      return;
    }

    setLoadingMore(true);
    setError(null);
    try {
      const page = await fetchPage(nextCursor);
      setItems((prev) => mergeHoldingsByTicker(prev, page.items));
      setHasMore(page.hasMore);
      setNextCursor(page.nextCursor);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load holdings");
    } finally {
      setLoadingMore(false);
    }
  }, [fetchPage, hasMore, loadingMore, nextCursor]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!hasUnsavedChanges) {
      return;
    }

    const message = "저장되지 않은 변경사항이 있습니다. 이 페이지를 떠나시겠습니까?";
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = message;
      return message;
    };
    const onDocumentClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const element =
        event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(element instanceof HTMLAnchorElement)) {
        return;
      }
      if (element.target && element.target !== "_self") {
        return;
      }

      const nextUrl = new URL(element.href, window.location.href);
      const currentUrl = new URL(window.location.href);
      const changingPage =
        nextUrl.pathname !== currentUrl.pathname ||
        nextUrl.search !== currentUrl.search ||
        nextUrl.hash !== currentUrl.hash;
      if (!changingPage) {
        return;
      }

      if (!window.confirm(message)) {
        event.preventDefault();
      }
    };

    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onDocumentClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onDocumentClick, true);
    };
  }, [hasUnsavedChanges]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const method = editingTicker ? "PATCH" : "POST";
      const endpoint = editingTicker
        ? `/api/holdings/${encodeURIComponent(editingTicker)}`
        : "/api/holdings";
      const payload = editingTicker
        ? buildPatchPayload(form)
        : buildCreatePayload(form);

      const response = await fetch(endpoint, {
        method,
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });

      const responseJson = (await response.json()) as unknown;

      if (!response.ok) {
        throw new Error(readApiError(responseJson) || "Save failed");
      }

      setEditingTicker(null);
      setForm(EMPTY_FORM);
      setBaselineForm(EMPTY_FORM);
      await refresh();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  };

  const beginEdit = (row: HoldingRecord) => {
    const nextForm = recordToForm(row);
    setEditingTicker(row.ticker);
    setForm(nextForm);
    setBaselineForm(nextForm);
  };

  const cancelEdit = () => {
    setEditingTicker(null);
    setForm(EMPTY_FORM);
    setBaselineForm(EMPTY_FORM);
  };

  const removeHolding = async (ticker: string) => {
    const confirmDelete = window.confirm(`${ticker} 을(를) 삭제하시겠습니까?`);
    if (!confirmDelete) {
      return;
    }

    setError(null);
    try {
      const response = await fetch(`/api/holdings/${encodeURIComponent(ticker)}`, {
        method: "DELETE"
      });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(readApiError(payload) || "Delete failed");
      }
      if (editingTicker === ticker) {
        cancelEdit();
      }
      await refresh();
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Delete failed");
    }
  };

  return (
    <section className={styles.wrapper}>
      <aside className="panel">
        <h2 className="panelTitle">{modeLabel}</h2>
        <p className="subtle">Supabase holdings 테이블 반영</p>
        {hasUnsavedChanges && (
          <p className={styles.unsavedNotice} role="status" aria-live="polite">
            저장되지 않은 변경사항이 있습니다.
          </p>
        )}
        <p className="visuallyHidden" role="status" aria-live="polite">
          {submitting ? "보유 종목 저장 중" : editingTicker ? "보유 종목 편집 모드" : "보유 종목 생성 모드"}
        </p>

        <form onSubmit={onSubmit} className={styles.form} aria-busy={submitting}>
          <label>
            Ticker
            <input
              name="ticker"
              autoComplete="off"
              value={form.ticker}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, ticker: event.target.value.toUpperCase() }))
              }
              disabled={Boolean(editingTicker)}
              placeholder="AAPL.US"
              required={!editingTicker}
            />
          </label>

          <div className={styles.rowTwo}>
            <label>
              Quantity
              <input
                name="quantity"
                autoComplete="off"
                value={form.quantity}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, quantity: event.target.value }))
                }
                type="number"
                inputMode="decimal"
                step="any"
                placeholder="0"
                required
              />
            </label>
            <label>
              Entry Price
              <input
                name="entryPrice"
                autoComplete="off"
                value={form.entry_price}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, entry_price: event.target.value }))
                }
                type="number"
                inputMode="decimal"
                step="any"
                placeholder="0"
                required
              />
            </label>
          </div>

          <div className={styles.rowTwo}>
            <label>
              Currency
              <input
                name="entryCurrency"
                autoComplete="off"
                value={form.entry_currency}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, entry_currency: event.target.value }))
                }
                placeholder="KRW or USD"
              />
            </label>
            <label>
              Entry Date
              <input
                name="entryDate"
                autoComplete="off"
                value={form.entry_date}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, entry_date: event.target.value }))
                }
                type="date"
              />
            </label>
          </div>

          <label>
            Strategy
            <input
              name="strategy"
              autoComplete="off"
              value={form.strategy}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, strategy: event.target.value }))
              }
              placeholder="optional"
            />
          </label>

          <label>
            Tags (comma separated)
            <input
              name="tags"
              autoComplete="off"
              value={form.tags}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, tags: event.target.value }))
              }
              placeholder="core, swing"
            />
          </label>

          <div className={styles.rowTwo}>
            <label>
              Stop Override
              <input
                name="stopOverride"
                autoComplete="off"
                value={form.stop_override}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, stop_override: event.target.value }))
                }
                type="number"
                inputMode="decimal"
                step="any"
                placeholder="optional"
              />
            </label>
            <label>
              Target Override
              <input
                name="targetOverride"
                autoComplete="off"
                value={form.target_override}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, target_override: event.target.value }))
                }
                type="number"
                inputMode="decimal"
                step="any"
                placeholder="optional"
              />
            </label>
          </div>

          <label>
            Notes
            <textarea
              name="notes"
              autoComplete="off"
              value={form.notes}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, notes: event.target.value }))
              }
              rows={4}
            />
          </label>

          <div className={styles.formActions}>
            <button type="submit" disabled={submitting}>
              {editingTicker ? "Update" : "Create"}
            </button>
            {editingTicker && (
              <button type="button" onClick={cancelEdit} className={styles.ghostButton}>
                Cancel
              </button>
            )}
          </div>
        </form>
      </aside>

      <section className="panel" aria-busy={loading}>
        <div className={styles.headerRow}>
          <div>
            <h2 className="panelTitle">Holdings</h2>
            <p className="subtle">
              정렬: updated_at desc · 활성 {partitioned.activeCount} / 비활성{" "}
              {partitioned.inactiveCount} · 로드 {items.length}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || loadingMore}
          >
            Refresh
          </button>
        </div>
        <div className={styles.filterRow}>
          <label className={styles.toggleLabel}>
            <input
              name="showInactive"
              type="checkbox"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            비활성 포함 표시 (quantity&lt;=0)
          </label>
          {!showInactive && partitioned.inactiveCount > 0 && (
            <p className="subtle">비활성 {partitioned.inactiveCount}개 숨김</p>
          )}
        </div>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        {loading && (
          <p className="subtle" role="status" aria-live="polite">
            로딩 중…
          </p>
        )}
        {!loading && visibleItems.length === 0 && (
          <p className="subtle">
            {items.length === 0
              ? "등록된 보유 종목이 없습니다."
              : "활성 보유 종목이 없습니다."}
          </p>
        )}

        {!loading && visibleItems.length > 0 && (
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Date</th>
                  <th>Notes</th>
                  <th>Tags</th>
                  <th>Updated</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((row) => {
                  const inactive = !isActiveHoldingQuantity(row.quantity);
                  return (
                  <tr
                    key={row.ticker}
                    className={showInactive && inactive ? styles.inactiveRow : undefined}
                  >
                    <td>{row.ticker}</td>
                    <td>
                      {row.quantity}
                      {showInactive && inactive && (
                        <span className={styles.inactiveBadge}>비활성</span>
                      )}
                    </td>
                    <td>{row.entry_price}</td>
                    <td>{row.entry_date ?? "-"}</td>
                    <td className={styles.notesCell}>{row.notes ?? "-"}</td>
                    <td>{row.tags.join(", ") || "-"}</td>
                    <td>{row.updated_at}</td>
                    <td>
                      <div className={styles.inlineActions}>
                        <button type="button" onClick={() => beginEdit(row)}>
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => void removeHolding(row.ticker)}
                          className={styles.dangerButton}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        )}
        {!loading && hasMore && (
          <div className={styles.loadMoreRow}>
            <button
              type="button"
              onClick={() => void loadMore()}
              disabled={loadingMore}
            >
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
      </section>
    </section>
  );
}
