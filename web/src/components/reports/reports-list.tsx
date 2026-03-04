import styles from "../reports-client.module.css";

import type { ReportListItem, ReportSearchWarning } from "@/lib/types";

import { formatDateLabel } from "./helpers";
import type { ReportsFilterType } from "./types";

interface ReportsListProps {
  reportType: ReportsFilterType;
  query: string;
  appliedQuery: string;
  items: ReportListItem[];
  total: number;
  searched: number;
  truncated: boolean;
  searchWindow: number;
  warnings: ReportSearchWarning[];
  selectedKey: string | null;
  loadingList: boolean;
  refreshing: boolean;
  onReportTypeChange: (value: ReportsFilterType) => void;
  onQueryChange: (value: string) => void;
  onSelectKey: (key: string) => void;
  onRefresh: () => void;
}

export function ReportsList({
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
  loadingList,
  refreshing,
  onReportTypeChange,
  onQueryChange,
  onSelectKey,
  onRefresh,
}: ReportsListProps) {
  return (
    <>
      <header className="panel">
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
            </select>
          </label>

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
          total={total}
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
          <li className="panel subtle" role="status" aria-live="polite">
            목록 로딩 중…
          </li>
        )}
        {!loadingList && items.length === 0 && (
          <li className="panel subtle" role="status" aria-live="polite">
            조건에 맞는 리포트가 없습니다.
          </li>
        )}
        {!loadingList &&
          items.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                className={`${styles.itemButton} ${
                  selectedKey === item.key ? styles.active : ""
                }`.trim()}
                onClick={() => onSelectKey(item.key)}
                aria-pressed={selectedKey === item.key}
              >
                <span className={styles.itemPrimary}>
                  {formatDateLabel(item)}
                </span>
                <span className={styles.badge}>{item.type.toUpperCase()}</span>
                <span className={styles.itemKey}>{item.key}</span>
              </button>
            </li>
          ))}
      </ul>
    </>
  );
}
