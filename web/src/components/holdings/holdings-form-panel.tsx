import type { FormEvent } from "react";

import styles from "../holdings-client.module.css";

import type { HoldingFormState } from "./form-state";

interface TickerLookupItem {
  ticker: string;
  name: string | null;
}

interface HoldingsFormPanelProps {
  modeLabel: string;
  submitting: boolean;
  editingTicker: string | null;
  hasUnsavedChanges: boolean;
  form: HoldingFormState;
  tickerLookupQuery: string;
  tickerLookupResults: TickerLookupItem[];
  tickerLookupLoading: boolean;
  tickerLookupError: string | null;
  recentCandidates: TickerLookupItem[];
  recentCandidatesReportKey: string | null;
  recentCandidatesReportDate: string | null;
  recentCandidatesLoading: boolean;
  recentCandidatesError: string | null;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onCancelEdit: () => void;
  onFieldChange: (field: keyof HoldingFormState, value: string) => void;
  onTickerLookupQueryChange: (value: string) => void;
  onSelectTicker: (ticker: string) => void;
}

export function HoldingsFormPanel({
  modeLabel,
  submitting,
  editingTicker,
  hasUnsavedChanges,
  form,
  tickerLookupQuery,
  tickerLookupResults,
  tickerLookupLoading,
  tickerLookupError,
  recentCandidates,
  recentCandidatesReportKey,
  recentCandidatesReportDate,
  recentCandidatesLoading,
  recentCandidatesError,
  onSubmit,
  onCancelEdit,
  onFieldChange,
  onTickerLookupQueryChange,
  onSelectTicker,
}: HoldingsFormPanelProps) {
  return (
    <aside className="panel">
      <h2 className="panelTitle">{modeLabel}</h2>
      <p className="subtle">Supabase holdings 테이블 반영</p>
      {hasUnsavedChanges && (
        <p className={styles.unsavedNotice} role="status" aria-live="polite">
          저장되지 않은 변경사항이 있습니다.
        </p>
      )}
      <p className="visuallyHidden" role="status" aria-live="polite">
        {submitting
          ? "보유 종목 저장 중"
          : editingTicker
            ? "보유 종목 편집 모드"
            : "보유 종목 생성 모드"}
      </p>

      <form onSubmit={onSubmit} className={styles.form} aria-busy={submitting}>
        <label>
          Ticker
          <input
            name="ticker"
            autoComplete="off"
            value={form.ticker}
            onChange={(event) =>
              onFieldChange("ticker", event.target.value.toUpperCase())
            }
            placeholder="AAPL.NAS"
            required
          />
        </label>
        <label>
          Ticker Search
          <input
            name="tickerLookup"
            autoComplete="off"
            value={tickerLookupQuery}
            onChange={(event) => onTickerLookupQueryChange(event.target.value)}
            placeholder="코스트코 / COST / 애브비"
          />
        </label>
        {tickerLookupLoading && <p className="subtle">검색 중…</p>}
        {tickerLookupError && (
          <p className={styles.error} role="status" aria-live="polite">
            {tickerLookupError}
          </p>
        )}
        {tickerLookupResults.length > 0 && (
          <ul className={styles.lookupList}>
            {tickerLookupResults.map((item) => (
              <li key={item.ticker}>
                <button
                  type="button"
                  className={styles.lookupItemButton}
                  onClick={() => onSelectTicker(item.ticker)}
                >
                  <span className={styles.lookupTicker}>{item.ticker}</span>
                  <span className={styles.lookupName}>
                    {item.name ?? "이름 없음"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <section className={styles.lookupPanel}>
          <div className={styles.lookupPanelHeader}>
            <h3 className={styles.lookupPanelTitle}>최근 Buy 후보</h3>
            {recentCandidatesReportKey && (
              <a
                href={`/reports?key=${encodeURIComponent(recentCandidatesReportKey)}`}
                className={styles.lookupPanelLink}
              >
                리포트 보기
              </a>
            )}
          </div>
          {recentCandidatesReportDate && (
            <p className="subtle">{recentCandidatesReportDate} 리포트 기준</p>
          )}
          {recentCandidatesLoading && <p className="subtle">로딩 중…</p>}
          {recentCandidatesError && (
            <p className={styles.error} role="status" aria-live="polite">
              {recentCandidatesError}
            </p>
          )}
          {!recentCandidatesLoading &&
            !recentCandidatesError &&
            recentCandidates.length <= 0 && (
              <p className="subtle">표시할 후보가 없습니다.</p>
            )}
          {!recentCandidatesLoading && recentCandidates.length > 0 && (
            <ul className={styles.lookupList}>
              {recentCandidates.map((item) => (
                <li key={`recent-${item.ticker}`}>
                  <button
                    type="button"
                    className={styles.lookupItemButton}
                    onClick={() => onSelectTicker(item.ticker)}
                  >
                    <span className={styles.lookupTicker}>{item.ticker}</span>
                    <span className={styles.lookupName}>
                      {item.name ?? "이름 없음"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className={styles.rowTwo}>
          <label>
            Quantity
            <input
              name="quantity"
              autoComplete="off"
              value={form.quantity}
              onChange={(event) =>
                onFieldChange("quantity", event.target.value)
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
                onFieldChange("entry_price", event.target.value)
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
                onFieldChange("entry_currency", event.target.value)
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
                onFieldChange("entry_date", event.target.value)
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
            onChange={(event) => onFieldChange("strategy", event.target.value)}
            placeholder="optional"
          />
        </label>

        <label>
          Tags (comma separated)
          <input
            name="tags"
            autoComplete="off"
            value={form.tags}
            onChange={(event) => onFieldChange("tags", event.target.value)}
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
                onFieldChange("stop_override", event.target.value)
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
                onFieldChange("target_override", event.target.value)
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
            onChange={(event) => onFieldChange("notes", event.target.value)}
            rows={4}
          />
        </label>

        <div className={styles.formActions}>
          <button type="submit" disabled={submitting}>
            {editingTicker ? "Update" : "Create"}
          </button>
          {editingTicker && (
            <button
              type="button"
              onClick={onCancelEdit}
              className={styles.ghostButton}
            >
              Cancel
            </button>
          )}
        </div>
      </form>
    </aside>
  );
}
