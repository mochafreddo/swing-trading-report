"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import styles from "./holdings-client.module.css";

import type { HoldingRecord } from "@/lib/types";

interface HoldingsResponse {
  items: HoldingRecord[];
}

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

function numberOrUndefined(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
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
    quantity: numberOrUndefined(form.quantity) ?? 0,
    entry_price: numberOrUndefined(form.entry_price) ?? 0,
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
    quantity: numberOrUndefined(form.quantity) ?? 0,
    entry_price: numberOrUndefined(form.entry_price) ?? 0,
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

export function HoldingsClient() {
  const [items, setItems] = useState<HoldingRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingTicker, setEditingTicker] = useState<string | null>(null);
  const [form, setForm] = useState<HoldingFormState>(EMPTY_FORM);

  const modeLabel = useMemo(
    () => (editingTicker ? `Edit ${editingTicker}` : "Create Holding"),
    [editingTicker]
  );

  const refresh = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/holdings", { cache: "no-store" });
      const payload = (await response.json()) as unknown;
      if (!response.ok) {
        throw new Error(readApiError(payload) || "Failed to load holdings");
      }
      setItems((payload as HoldingsResponse).items);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load holdings");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

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
      await refresh();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  };

  const beginEdit = (row: HoldingRecord) => {
    setEditingTicker(row.ticker);
    setForm(recordToForm(row));
  };

  const cancelEdit = () => {
    setEditingTicker(null);
    setForm(EMPTY_FORM);
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

        <form onSubmit={onSubmit} className={styles.form}>
          <label>
            Ticker
            <input
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
                value={form.quantity}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, quantity: event.target.value }))
                }
                inputMode="decimal"
                placeholder="0"
              />
            </label>
            <label>
              Entry Price
              <input
                value={form.entry_price}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, entry_price: event.target.value }))
                }
                inputMode="decimal"
                placeholder="0"
              />
            </label>
          </div>

          <div className={styles.rowTwo}>
            <label>
              Currency
              <input
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
                value={form.stop_override}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, stop_override: event.target.value }))
                }
                inputMode="decimal"
                placeholder="optional"
              />
            </label>
            <label>
              Target Override
              <input
                value={form.target_override}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, target_override: event.target.value }))
                }
                inputMode="decimal"
                placeholder="optional"
              />
            </label>
          </div>

          <label>
            Notes
            <textarea
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

      <section className="panel">
        <div className={styles.headerRow}>
          <div>
            <h2 className="panelTitle">Holdings</h2>
            <p className="subtle">정렬: updated_at desc</p>
          </div>
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            Refresh
          </button>
        </div>

        {error && <p className={styles.error}>{error}</p>}
        {loading && <p className="subtle">로딩 중...</p>}
        {!loading && items.length === 0 && (
          <p className="subtle">등록된 보유 종목이 없습니다.</p>
        )}

        {!loading && items.length > 0 && (
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
                {items.map((row) => (
                  <tr key={row.ticker}>
                    <td>{row.ticker}</td>
                    <td>{row.quantity}</td>
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
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
