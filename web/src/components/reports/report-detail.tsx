import { Fragment, useState } from "react";

import styles from "../reports-client.module.css";

import { formatSummaryKeyForDisplay } from "@/lib/report-summary-label";

import {
  buildBuyCandidateViewModel,
  type ChipTone,
} from "./buy-candidate-view-model";
import { asRecord, formatPnlPercent, readNumber } from "./helpers";
import type { ReportJson } from "./types";

interface ReportDetailProps {
  detail: ReportJson | null;
  loadingDetail: boolean;
  error: string | null;
  showRaw: boolean;
  summary: ReportJson | null;
  buyRows: ReportJson[];
  sellRows: ReportJson[];
  entryRows: ReportJson[];
  aiBriefRows: ReportJson[];
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

function readString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function readNumberLike(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
}

function formatIssue(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const ticker = readString(record.ticker);
  const severity = readString(record.severity);
  const code = readString(record.code);
  const message = readString(record.message);
  const prefix = [ticker, severity, code].filter(Boolean).join(" ");
  if (message && prefix) {
    return `${prefix}: ${message}`;
  }
  return message ?? (prefix || null);
}

function asIssueArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => formatIssue(item))
    .filter((item): item is string => Boolean(item));
}

function formatSources(value: unknown): string {
  if (!Array.isArray(value)) {
    return "-";
  }
  const sources = value
    .map((source) => {
      const record = asRecord(source);
      if (!record) {
        return null;
      }
      const title = readString(record.title);
      const url = readString(record.url);
      if (title && url) {
        return `${title} (${url})`;
      }
      return title ?? url;
    })
    .filter((item): item is string => Boolean(item));
  return sources.join(" · ") || "-";
}

function formatNullableNumber(value: unknown): string {
  const parsed = readNumberLike(value);
  if (parsed === null) {
    return "-";
  }
  return String(parsed);
}

function formatRatioPercent(value: unknown): string {
  const parsed = readNumberLike(value);
  if (parsed === null) {
    return "-";
  }
  const pct = parsed * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function formatScoreValue(row: ReportJson): string {
  const scoreValue = readNumberLike(row.score_value);
  if (scoreValue !== null) {
    return scoreValue.toFixed(2).replace(/\.00$/, "");
  }
  const score = readNumberLike(row.score);
  if (score !== null) {
    return score.toFixed(2).replace(/\.00$/, "");
  }
  return "-";
}

function chipToneClass(tone: ChipTone): string {
  if (tone === "warning") {
    return styles.chipWarning;
  }
  if (tone === "neutral") {
    return styles.chipNeutral;
  }
  return styles.chipPositive;
}

export function ReportDetail({
  detail,
  loadingDetail,
  error,
  showRaw,
  summary,
  buyRows,
  sellRows,
  entryRows,
  aiBriefRows,
  rawDetailJson,
  onToggleRaw,
}: ReportDetailProps) {
  const [expandedBuyRowKey, setExpandedBuyRowKey] = useState<string | null>(
    null,
  );
  const reportType = readString(detail?.type);
  const isEntryReport = reportType === "entry";
  const isAiBriefReport =
    reportType === "ai_brief" || reportType === "ai-brief";
  const strategyMode = readString(detail?.strategy_mode);
  const evalContext = asRecord(detail?.eval_context);
  const evalMarket = readString(evalContext?.market);
  const evalSessionState = readString(evalContext?.session_state);
  const sourceBuyReport = readString(detail?.source_buy_report);
  const sourceEntryReport = readString(detail?.source_entry_report);
  const aiBriefMarket = readString(detail?.market);
  const modelProvider = readString(detail?.model_provider);
  const modelName = readString(detail?.model_name);
  const signalEvalDate = readString(detail?.signal_eval_date);
  const entrySessionDate = readString(detail?.entry_session_date);
  const signalEvalDateByMarket = asRecord(detail?.signal_eval_date_by_market);
  const entrySessionDateByMarket = asRecord(
    detail?.entry_session_date_by_market,
  );
  const systemIssues = asIssueArray(detail?.system_issues);
  const sourceIssues = asIssueArray(detail?.source_issues);
  const screenOuts = asStringArray(detail?.screen_outs);
  const combinedIssues = asStringArray(detail?.issues);
  const issueSections = [
    {
      key: "system",
      title: `System issues (${systemIssues.length})`,
      items: systemIssues,
    },
    {
      key: "source",
      title: `Source issues (${sourceIssues.length})`,
      items: sourceIssues,
    },
    {
      key: "screen-outs",
      title: `Screen outs (${screenOuts.length})`,
      items: screenOuts,
    },
    {
      key: "all",
      title: `Issues (${combinedIssues.length})`,
      items: combinedIssues,
    },
  ].filter((section) => section.items.length > 0);

  const handleToggleBuyRowDetail = (rowKey: string) => {
    setExpandedBuyRowKey((prev) => (prev === rowKey ? null : rowKey));
  };

  return (
    <section
      className={`panel ${styles.detailPanel}`}
      aria-busy={loadingDetail}
    >
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
            {isAiBriefReport && (
              <div>
                <dt>model_provider</dt>
                <dd>{modelProvider ?? "-"}</dd>
              </div>
            )}
            {isAiBriefReport && (
              <div>
                <dt>model_name</dt>
                <dd>{modelName ?? "-"}</dd>
              </div>
            )}
            <div>
              <dt>strategy_mode</dt>
              <dd>{strategyMode ?? "-"}</dd>
            </div>
            <div>
              <dt>market</dt>
              <dd>{evalMarket ?? aiBriefMarket ?? "-"}</dd>
            </div>
            <div>
              <dt>session_state</dt>
              <dd>{evalSessionState ?? "-"}</dd>
            </div>
            {isEntryReport && (
              <div>
                <dt>source_buy_report</dt>
                <dd>{sourceBuyReport ?? "-"}</dd>
              </div>
            )}
            {isAiBriefReport && (
              <div>
                <dt>source_entry_report</dt>
                <dd>{sourceEntryReport ?? "-"}</dd>
              </div>
            )}
            {isAiBriefReport && (
              <div>
                <dt>source_buy_report</dt>
                <dd>{sourceBuyReport ?? "-"}</dd>
              </div>
            )}
            {isEntryReport && (
              <div>
                <dt>signal_eval_date</dt>
                <dd>
                  {signalEvalDate ??
                    formatSummaryValue(signalEvalDateByMarket ?? "-")}
                </dd>
              </div>
            )}
            {isEntryReport && (
              <div>
                <dt>entry_session_date</dt>
                <dd>
                  {entrySessionDate ??
                    formatSummaryValue(entrySessionDateByMarket ?? "-")}
                </dd>
              </div>
            )}
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
          {reportType === "buy" && (
            <p className={styles.infoNote}>
              후보는 평가 캔들(EOD) 기준 발굴 결과이며, 다음 세션 체결을
              보장하지 않습니다.
            </p>
          )}
          {isEntryReport && (
            <p className={styles.infoNote}>
              Entry 리포트는 이전 buy 후보를 다음 세션 진입 관점으로 재평가한
              결과입니다.
            </p>
          )}
          {isAiBriefReport && (
            <p className={styles.infoNote}>
              AI Brief는 entry 리포트의 ENTER 후보를 모델 provider로 요약한 수동
              검토용 결과입니다.
            </p>
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
                    <th>근거</th>
                    <th>리스크</th>
                  </tr>
                </thead>
                <tbody>
                  {buyRows.map((row, idx) => {
                    const rowKey = `${String(row.ticker ?? "-")}-${idx}`;
                    const detailId = `buy-row-detail-${idx}`;
                    const isExpanded = expandedBuyRowKey === rowKey;
                    const viewModel = buildBuyCandidateViewModel(
                      row,
                      strategyMode,
                    );
                    return (
                      <Fragment key={rowKey}>
                        <tr>
                          <td data-label="Ticker">
                            {String(row.ticker ?? "-")}
                          </td>
                          <td data-label="Name">{String(row.name ?? "-")}</td>
                          <td data-label="Price">{String(row.price ?? "-")}</td>
                          <td data-label="Score">{formatScoreValue(row)}</td>
                          <td data-label="근거">
                            <div className={styles.reasonCell}>
                              <div className={styles.chipRow}>
                                {viewModel.reasonChips.map((chip) => (
                                  <span
                                    key={chip.label}
                                    className={`${styles.reasonChip} ${chipToneClass(
                                      chip.tone,
                                    )}`}
                                  >
                                    {chip.label}
                                  </span>
                                ))}
                              </div>
                              <p className={styles.reasonSummary}>
                                {viewModel.reasonSummary}
                              </p>
                              <button
                                type="button"
                                className={styles.rowDetailToggle}
                                onClick={() => handleToggleBuyRowDetail(rowKey)}
                                aria-expanded={isExpanded}
                                aria-controls={detailId}
                              >
                                {isExpanded ? "상세 접기" : "상세 보기"}
                              </button>
                            </div>
                          </td>
                          <td data-label="리스크" className={styles.riskCell}>
                            {viewModel.riskSummary}
                          </td>
                        </tr>
                        {isExpanded && (
                          <tr className={styles.expandedRow}>
                            <td colSpan={6}>
                              <div
                                id={detailId}
                                className={styles.expandedPanel}
                              >
                                {viewModel.detailSections.map((section) => (
                                  <section
                                    key={section.title}
                                    className={styles.expandedSection}
                                  >
                                    <h4>{section.title}</h4>
                                    <ul>
                                      {section.lines.map((line, lineIndex) => (
                                        <li
                                          key={`${section.title}-${lineIndex}`}
                                        >
                                          {line}
                                        </li>
                                      ))}
                                    </ul>
                                  </section>
                                ))}
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
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
                      <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
                      <td data-label="Action">{String(row.action ?? "-")}</td>
                      <td data-label="Last">
                        {readNumber(row.last_price) ?? "-"}
                      </td>
                      <td data-label="PnL%">{formatPnlPercent(row.pnl_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {entryRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Entries ({entryRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Action</th>
                    <th>Signal Close</th>
                    <th>Entry Price</th>
                    <th>Gap%</th>
                    <th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {entryRows.map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
                      <td data-label="Action">{String(row.action ?? "-")}</td>
                      <td data-label="Signal Close">
                        {formatNullableNumber(row.signal_close)}
                      </td>
                      <td data-label="Entry Price">
                        {formatNullableNumber(row.entry_price)}
                      </td>
                      <td data-label="Gap%">
                        {formatRatioPercent(row.gap_pct)}
                      </td>
                      <td data-label="Reasons">
                        {asStringArray(row.reasons).join(" · ") || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {aiBriefRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Recommendations ({aiBriefRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Rank</th>
                    <th>Confidence</th>
                    <th>Rationale</th>
                    <th>Checklist</th>
                    <th>Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {aiBriefRows.map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
                      <td data-label="Rank">{String(row.rank ?? "-")}</td>
                      <td data-label="Confidence">
                        {String(row.confidence ?? "-")}
                      </td>
                      <td data-label="Rationale">
                        {asStringArray(row.rationale).join(" · ") || "-"}
                      </td>
                      <td data-label="Checklist">
                        {asStringArray(row.checklist).join(" · ") || "-"}
                      </td>
                      <td data-label="Sources">{formatSources(row.sources)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {issueSections.length > 0 && (
            <div className={styles.issuesWrap}>
              <h3 className={styles.sectionTitle}>Issues</h3>
              <div className={styles.issuesGrid}>
                {issueSections.map((section) => (
                  <details key={section.key} className={styles.issueSection}>
                    <summary>{section.title}</summary>
                    <ul>
                      {section.items.map((item, index) => (
                        <li key={`${section.key}-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
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
