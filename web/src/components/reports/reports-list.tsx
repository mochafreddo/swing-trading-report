import styles from "../reports-client.module.css";

import type {
  DecisionBoardRunKind,
  ReportListItem,
  ReportSearchWarning,
} from "@/lib/types";

import { formatDateLabel } from "./helpers";
import type { ReportsFilterType } from "./types";

interface ReportsListProps {
  reportType: ReportsFilterType;
  runKind: DecisionBoardRunKind | null;
  query: string;
  appliedQuery: string;
  items: ReportListItem[];
  total: number | null;
  searched: number;
  truncated: boolean;
  searchWindow: number;
  warnings: ReportSearchWarning[];
  selectedKey: string | null;
  selectedBucketId: string | null;
  loadingList: boolean;
  refreshing: boolean;
  onReportTypeChange: (value: ReportsFilterType) => void;
  onRunKindChange: (value: DecisionBoardRunKind) => void;
  onQueryChange: (value: string) => void;
  onSelectKey: (key: string, bucketId?: string) => void;
  onRefresh: () => void;
}

export function ReportsList({
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
  loadingList,
  refreshing,
  onReportTypeChange,
  onRunKindChange,
  onQueryChange,
  onSelectKey,
  onRefresh,
}: ReportsListProps) {
  return (
    <>
      <header className={`panel ${styles.sidebarPanel}`}>
        <div className={styles.listHeaderRow}>
          <h2 className="panelTitle">Reports</h2>
          <button
            type="button"
            className={styles.toggleButton}
            onClick={onRefresh}
            disabled={refreshing}
          >
            {refreshing ? "새로고침 중…" : "새로고침"}
          </button>
        </div>
        <p className="subtle">Supabase Storage 리포트 탐색</p>

        <div className={styles.controls}>
          <label>
            Type
            <select
              name="reportType"
              autoComplete="off"
              value={reportType}
              onChange={(event) =>
                onReportTypeChange(event.target.value as ReportsFilterType)
              }
            >
              <option value="all">All</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
              <option value="entry">Entry</option>
              <option value="ai-brief">AI Brief</option>
              <option value="ai-brief-skip">AI Brief Skip</option>
              <option value="sell-ai-brief">Sell AI Brief</option>
              <option value="decision-board">Decision Board</option>
            </select>
          </label>

          {reportType === "decision-board" && (
            <label>
              Lane
              <select
                name="runKind"
                autoComplete="off"
                value={runKind ?? "ENTRY"}
                onChange={(event) =>
                  onRunKindChange(event.target.value as DecisionBoardRunKind)
                }
              >
                <option value="ENTRY">ENTRY</option>
                <option value="HOLDING">HOLDING</option>
              </select>
            </label>
          )}

          <label>
            Ticker 검색
            <input
              name="reportQuery"
              autoComplete="off"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="예: AAPL"
              spellCheck={false}
            />
          </label>
        </div>

        <p className="subtle">
          {total === null ? `shown=${items.length}` : `total=${total}`}
          {appliedQuery && (
            <>
              {" · "}searched={searched}
              {truncated ? `/${searchWindow} window` : ""}
            </>
          )}
        </p>
        {appliedQuery && truncated && (
          <p className="subtle">
            검색 범위 제한: 최신 {searchWindow}개 리포트만 검색됨
          </p>
        )}
        {warnings.map((warning) => (
          <p key={`${warning.code}:${warning.message}`} className="subtle">
            {warning.message}
          </p>
        ))}
      </header>

      <ul className={styles.list} aria-busy={loadingList}>
        {loadingList && (
          <li
            className={`panel subtle ${styles.listMessage}`}
            role="status"
            aria-live="polite"
          >
            목록 로딩 중…
          </li>
        )}
        {!loadingList && items.length === 0 && (
          <li
            className={`panel subtle ${styles.listMessage}`}
            role="status"
            aria-live="polite"
          >
            조건에 맞는 리포트가 없습니다.
          </li>
        )}
        {!loadingList &&
          items.map((item) => {
            const isSelected =
              selectedKey === item.key && selectedBucketId === item.bucketId;
            return (
              <li key={`${item.bucketId}:${item.key}`}>
                <button
                  type="button"
                  className={`${styles.itemButton} ${
                    isSelected ? styles.active : ""
                  }`.trim()}
                  onClick={() => onSelectKey(item.key, item.bucketId)}
                  aria-pressed={isSelected}
                >
                  <span className={styles.itemPrimary}>
                    {formatDateLabel(item)}
                  </span>
                  <span className={styles.badge}>
                    {item.type.toUpperCase()}
                  </span>
                  {item.runKind && (
                    <span className={styles.badge}>{item.runKind}</span>
                  )}
                  {item.runId && (
                    <span className={styles.itemRunId}>{item.runId}</span>
                  )}
                  {item.bucketId !== "reports" && (
                    <span className={styles.badge}>{item.bucketId}</span>
                  )}
                  <span className={styles.itemKey}>{item.key}</span>
                </button>
              </li>
            );
          })}
      </ul>
    </>
  );
}
