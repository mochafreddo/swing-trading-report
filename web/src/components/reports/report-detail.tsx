import styles from "../reports-client.module.css";

import { formatSummaryKeyForDisplay } from "@/lib/report-summary-label";

import { formatPnlPercent, readNumber } from "./helpers";
import type { ReportJson } from "./types";

interface ReportDetailProps {
  detail: ReportJson | null;
  loadingDetail: boolean;
  error: string | null;
  showRaw: boolean;
  summary: ReportJson | null;
  buyRows: ReportJson[];
  sellRows: ReportJson[];
  rawDetailJson: string;
  onToggleRaw: () => void;
}

function formatSummaryValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

export function ReportDetail({
  detail,
  loadingDetail,
  error,
  showRaw,
  summary,
  buyRows,
  sellRows,
  rawDetailJson,
  onToggleRaw,
}: ReportDetailProps) {
  return (
    <section className="panel" aria-busy={loadingDetail}>
      <div className={styles.detailHeaderRow}>
        <div>
          <h2 className="panelTitle">Report Detail</h2>
          <p className="subtle">구조화 보기 + Raw JSON</p>
        </div>
        <button
          type="button"
          className={styles.toggleButton}
          onClick={onToggleRaw}
          disabled={!detail}
          aria-pressed={showRaw}
          aria-controls="report-raw-json"
        >
          {showRaw ? "Raw 숨기기" : "Raw 보기"}
        </button>
      </div>

      <p className="visuallyHidden" role="status" aria-live="polite">
        {loadingDetail
          ? "리포트 상세 로딩 중"
          : detail
            ? "리포트 상세 로딩 완료"
            : "리포트를 선택하세요"}
      </p>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {loadingDetail && (
        <p className="subtle" role="status" aria-live="polite">
          상세 로딩 중…
        </p>
      )}
      {!loadingDetail && !detail && (
        <p className="subtle">리포트를 선택하세요.</p>
      )}

      {detail && (
        <>
          <dl className={styles.metaGrid}>
            <div>
              <dt>schema</dt>
              <dd>{String(detail.schema ?? "-")}</dd>
            </div>
            <div>
              <dt>type</dt>
              <dd>{String(detail.type ?? "-")}</dd>
            </div>
            <div>
              <dt>generated_at</dt>
              <dd>{String(detail.generated_at ?? "-")}</dd>
            </div>
            <div>
              <dt>provider</dt>
              <dd>{String(detail.provider ?? "-")}</dd>
            </div>
          </dl>

          {summary && (
            <div className={styles.summaryBoxes}>
              {Object.entries(summary).map(([key, value]) => (
                <article key={key} className={styles.summaryBox}>
                  <h3 className={styles.summaryKey}>
                    {formatSummaryKeyForDisplay(key)}
                  </h3>
                  <p className={styles.summaryValue}>
                    {formatSummaryValue(value)}
                  </p>
                </article>
              ))}
            </div>
          )}

          {buyRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Candidates ({buyRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Name</th>
                    <th>Price</th>
                    <th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {buyRows.slice(0, 20).map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td>{String(row.ticker ?? "-")}</td>
                      <td>{String(row.name ?? "-")}</td>
                      <td>{String(row.price ?? "-")}</td>
                      <td>{readNumber(row.score) ?? "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {sellRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Evaluated ({sellRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Action</th>
                    <th>Last</th>
                    <th>PnL%</th>
                  </tr>
                </thead>
                <tbody>
                  {sellRows.slice(0, 20).map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td>{String(row.ticker ?? "-")}</td>
                      <td>{String(row.action ?? "-")}</td>
                      <td>{readNumber(row.last_price) ?? "-"}</td>
                      <td>{formatPnlPercent(row.pnl_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {showRaw && (
            <pre id="report-raw-json" className={styles.raw}>
              {rawDetailJson}
            </pre>
          )}
        </>
      )}
    </section>
  );
}
