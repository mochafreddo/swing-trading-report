import styles from "../holdings-client.module.css";

import { isActiveHoldingQuantity } from "@/lib/holding-activity";
import type { HoldingRecord } from "@/lib/types";

interface HoldingsTableProps {
  items: HoldingRecord[];
  visibleItems: HoldingRecord[];
  activeCount: number;
  inactiveCount: number;
  showInactive: boolean;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  onRefresh: () => void | Promise<void>;
  onToggleShowInactive: (nextValue: boolean) => void;
  onEdit: (row: HoldingRecord) => void;
  onAddBuy: (row: HoldingRecord) => void;
  onDelete: (ticker: string) => void | Promise<void>;
  onLoadMore: () => void | Promise<void>;
}

export function HoldingsTable({
  items,
  visibleItems,
  activeCount,
  inactiveCount,
  showInactive,
  loading,
  loadingMore,
  hasMore,
  error,
  onRefresh,
  onToggleShowInactive,
  onEdit,
  onAddBuy,
  onDelete,
  onLoadMore,
}: HoldingsTableProps) {
  return (
    <section className="panel" aria-busy={loading}>
      <div className={styles.headerRow}>
        <div>
          <h2 className="panelTitle">Holdings</h2>
          <p className="subtle">
            정렬: updated_at desc · 활성 {activeCount} / 비활성 {inactiveCount}{" "}
            · 로드 {items.length}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void onRefresh()}
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
            onChange={(event) => onToggleShowInactive(event.target.checked)}
          />
          비활성 포함 표시 (quantity&lt;=0)
        </label>
        {!showInactive && inactiveCount > 0 && (
          <p className="subtle">비활성 {inactiveCount}개 숨김</p>
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
                    className={
                      showInactive && inactive ? styles.inactiveRow : undefined
                    }
                  >
                    <td data-label="Ticker">{row.ticker}</td>
                    <td data-label="Qty">
                      {row.quantity}
                      {showInactive && inactive && (
                        <span className={styles.inactiveBadge}>비활성</span>
                      )}
                    </td>
                    <td data-label="Entry">{row.entry_price}</td>
                    <td data-label="Date">{row.entry_date ?? "-"}</td>
                    <td data-label="Notes" className={styles.notesCell}>
                      {row.notes ?? "-"}
                    </td>
                    <td data-label="Tags">{row.tags.join(", ") || "-"}</td>
                    <td data-label="Updated">{row.updated_at}</td>
                    <td data-label="Action">
                      <div className={styles.inlineActions}>
                        <button type="button" onClick={() => onEdit(row)}>
                          Edit
                        </button>
                        <button type="button" onClick={() => onAddBuy(row)}>
                          Add Buy
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            if (
                              window.confirm(
                                `${row.ticker}을(를) 삭제하시겠습니까?`,
                              )
                            ) {
                              void onDelete(row.ticker);
                            }
                          }}
                          className={styles.dangerButton}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {!loading && hasMore && (
        <div className={styles.loadMoreRow}>
          <button
            type="button"
            onClick={() => void onLoadMore()}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </section>
  );
}
