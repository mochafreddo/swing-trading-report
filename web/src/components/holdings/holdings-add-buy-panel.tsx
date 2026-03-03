import type { FormEvent } from "react";

import styles from "../holdings-client.module.css";

import type { HoldingRecord } from "@/lib/types";

export interface AddBuyFormState {
  buy_quantity: string;
  buy_price: string;
  buy_date: string;
}

export interface AddBuyPreview {
  next_quantity: number;
  next_entry_price: number;
  next_entry_date: string | null;
  next_entry_currency: string;
}

interface HoldingsAddBuyPanelProps {
  target: HoldingRecord | null;
  form: AddBuyFormState;
  submitting: boolean;
  error: string | null;
  precheckError: string | null;
  preview: AddBuyPreview | null;
  onFieldChange: (field: keyof AddBuyFormState, value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onCancel: () => void;
}

export function HoldingsAddBuyPanel({
  target,
  form,
  submitting,
  error,
  precheckError,
  preview,
  onFieldChange,
  onSubmit,
  onCancel,
}: HoldingsAddBuyPanelProps) {
  return (
    <aside className="panel">
      <h2 className="panelTitle">Add Buy</h2>
      {!target && (
        <p className="subtle">Holdings 표에서 Add Buy를 선택하세요.</p>
      )}
      {error && (
        <p className={styles.error} role="status" aria-live="polite">
          {error}
        </p>
      )}
      {precheckError && (
        <p className={styles.error} role="status" aria-live="polite">
          {precheckError}
        </p>
      )}
      {target && (
        <form
          onSubmit={onSubmit}
          className={styles.form}
          aria-busy={submitting}
        >
          <p className="subtle">Ticker: {target.ticker}</p>
          <div className={styles.rowTwo}>
            <p className="subtle">현재 수량: {target.quantity}</p>
            <p className="subtle">현재 평단: {target.entry_price}</p>
          </div>
          <div className={styles.rowTwo}>
            <p className="subtle">
              현재 통화: {target.entry_currency ?? "자동 설정 예정"}
            </p>
            <p className="subtle">현재 진입일: {target.entry_date ?? "-"}</p>
          </div>

          <div className={styles.rowTwo}>
            <label>
              Buy Quantity
              <input
                name="buy_quantity"
                autoComplete="off"
                value={form.buy_quantity}
                onChange={(event) =>
                  onFieldChange("buy_quantity", event.target.value)
                }
                type="number"
                inputMode="decimal"
                step="any"
                min="0.000001"
                required
              />
            </label>
            <label>
              Buy Price
              <input
                name="buy_price"
                autoComplete="off"
                value={form.buy_price}
                onChange={(event) =>
                  onFieldChange("buy_price", event.target.value)
                }
                type="number"
                inputMode="decimal"
                step="any"
                min="0.0001"
                required
              />
            </label>
          </div>

          <label>
            Buy Date
            <input
              name="buy_date"
              autoComplete="off"
              value={form.buy_date}
              onChange={(event) =>
                onFieldChange("buy_date", event.target.value)
              }
              type="date"
            />
          </label>

          {preview && (
            <section className={styles.lookupPanel}>
              <h3 className={styles.lookupPanelTitle}>반영 미리보기</h3>
              <p className="subtle">다음 수량: {preview.next_quantity}</p>
              <p className="subtle">다음 평단: {preview.next_entry_price}</p>
              <p className="subtle">
                다음 진입일: {preview.next_entry_date ?? "-"}
              </p>
              <p className="subtle">다음 통화: {preview.next_entry_currency}</p>
            </section>
          )}

          <div className={styles.formActions}>
            <button
              type="submit"
              disabled={submitting || Boolean(precheckError)}
            >
              {submitting ? "Saving…" : "Save Add Buy"}
            </button>
            <button
              type="button"
              className={styles.ghostButton}
              onClick={onCancel}
              disabled={submitting}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </aside>
  );
}
