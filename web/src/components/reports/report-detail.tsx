import { Fragment, useState } from "react";

import styles from "../reports-client.module.css";

import { formatSummaryKeyForDisplay } from "@/lib/report-summary-label";
import { hasOwn } from "@/lib/object-utils";

import { resolveAiBriefState } from "./ai-brief-state";
import {
  buildBuyCandidateViewModel,
  type ChipTone,
} from "./buy-candidate-view-model";
import { asIssueArray, formatSources } from "./report-detail-formatters";
import { DOWNSIDE_RISK_SUFFIX, SELL_GUIDE_SUFFIX } from "./risk-guidance";
import {
  asRecord,
  asRecordArray,
  formatPnlPercent,
  formatRatioPercent,
  readNumber,
  readNumberLike,
  readString,
} from "./helpers";
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

const MONEY_FORMATTER = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatSummaryValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
}

function hasOwnField(value: unknown, field: string): boolean {
  return value !== null && typeof value === "object" && hasOwn(value, field);
}

function formatNullableNumber(value: unknown): string {
  const parsed = readNumberLike(value);
  if (parsed === null) {
    return "-";
  }
  return String(parsed);
}

function formatStringList(items: string[]): string {
  return items.length > 0 ? items.join(", ") : "-";
}

function formatSourceCoverage(covered: unknown, total: unknown): string {
  const coveredValue = readNumberLike(covered);
  const totalValue = readNumberLike(total);
  return `${coveredValue ?? "-"}/${totalValue ?? "-"}`;
}

function formatSourceFinalCoverage(final: ReportJson | null): string {
  if (!final) {
    return "-";
  }
  const recommendable = formatSourceCoverage(
    final.recommendable_covered,
    final.recommendable_total,
  );
  const watch = formatSourceCoverage(final.watch_covered, final.watch_total);
  return `recommendable=${recommendable} watch=${watch}`;
}

function formatSourceProviderStatuses(providers: ReportJson[]): string {
  const parts = providers
    .map((provider) => {
      const name = readString(provider.provider);
      if (!name) {
        return null;
      }
      const status = readString(provider.status) ?? "-";
      const coverage = formatSourceCoverage(provider.covered, provider.total);
      return `${name} ${status} ${coverage}`;
    })
    .filter((item): item is string => Boolean(item));
  return parts.length > 0 ? parts.join(" · ") : "-";
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

function formatEntryReadiness(row: ReportJson): string {
  const explicitReady = row.implementation_ready;
  const readiness = readString(row.investment_readiness);
  const reasons = asStringArray(row.investment_readiness_reasons);
  const status =
    readiness ?? (explicitReady === false ? "CONTEXT_REQUIRED" : null);
  if (!status) {
    return "-";
  }
  if (reasons.length === 0) {
    return status;
  }
  return `${status}: ${reasons.join(" · ")}`;
}

function formatOneDecimal(value: number): string {
  return value.toFixed(1).replace(/\.0$/, "");
}

function formatGuideValue(value: unknown): string {
  const formatted = formatNullableNumber(value);
  if (formatted === "-") {
    return "-";
  }
  return `${formatted} · ${SELL_GUIDE_SUFFIX}`;
}

function formatEntryExitCapacity(row: ReportJson): string {
  const capacity = asRecord(row.liquidity_exit_capacity);
  const warnings = asStringArray(row.liquidity_warnings);
  if (!capacity) {
    return warnings.length > 0 ? warnings.join(" · ") : "-";
  }

  const status = readString(capacity.status);
  let summary = status ?? "-";
  if (status === "available") {
    const advPercent = readNumberLike(capacity.position_adv_percent);
    const normalDays = readNumberLike(capacity.exit_days_normal);
    const stressedDays = readNumberLike(capacity.exit_days_stressed);
    if (advPercent !== null && normalDays !== null && stressedDays !== null) {
      summary = [
        `ADV ${formatOneDecimal(advPercent)}%`,
        `normal ${formatOneDecimal(normalDays)}d`,
        `stressed ${formatOneDecimal(stressedDays)}d`,
      ].join(" · ");
    }
  }
  if (warnings.length === 0) {
    return summary;
  }
  return `${summary}: ${warnings.join(" · ")}`;
}

function formatMoneyAmount(currency: string | null, value: number): string {
  const amount = MONEY_FORMATTER.format(value);
  return currency ? `${currency} ${amount}` : amount;
}

function formatEntryDownsideRisk(row: ReportJson): string {
  const downside = asRecord(row.downside_risk);
  if (!downside || readString(downside.status) !== "available") {
    return "-";
  }
  const amount = readNumberLike(downside.position_loss_amount);
  if (amount === null) {
    return "-";
  }
  const currency = readString(downside.currency);
  const positionLossPct = readNumberLike(downside.position_loss_pct);
  const portfolioLossPct = readNumberLike(downside.portfolio_loss_pct);
  const portfolioLossBps = readNumberLike(downside.portfolio_loss_bps);
  const fragments = [formatMoneyAmount(currency, amount)];
  if (positionLossPct !== null) {
    fragments.push(`${formatOneDecimal(positionLossPct)}% position`);
  }
  if (portfolioLossPct !== null && portfolioLossBps !== null) {
    fragments.push(
      `${formatOneDecimal(portfolioLossPct)}% portfolio / ${formatOneDecimal(
        portfolioLossBps,
      )}bps`,
    );
  }
  fragments.push(DOWNSIDE_RISK_SUFFIX);
  return fragments.join(" · ");
}

function formatEntryExposure(row: ReportJson): string {
  const buckets = asStringArray(row.portfolio_exposure_buckets);
  return buckets.length > 0 ? buckets.join(" · ") : "-";
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
  const isSellAiBriefReport =
    reportType === "sell_ai_brief" || reportType === "sell-ai-brief";
  const isModelBriefReport = isAiBriefReport || isSellAiBriefReport;
  const isAiBriefSkipReport =
    reportType === "ai_brief_skip" || reportType === "ai-brief-skip";
  const strategyMode = readString(detail?.strategy_mode);
  const evalContext = asRecord(detail?.eval_context);
  const evalMarket = readString(evalContext?.market);
  const evalSessionState = readString(evalContext?.session_state);
  const skipSessionState = readString(detail?.session_state);
  const expectedState = readString(detail?.expected_state);
  const skipState = readString(detail?.skip_state);
  const skipReason = readString(detail?.skip_reason);
  const sourceBuyReport = readString(detail?.source_buy_report);
  const sourceEntryReport = readString(detail?.source_entry_report);
  const sourceSellReport = readString(detail?.source_sell_report);
  const aiBriefMarket = readString(detail?.market);
  const modelProvider = readString(detail?.model_provider);
  const modelName = readString(detail?.model_name);
  const aiBriefState = isAiBriefReport ? resolveAiBriefState(detail) : null;
  const sellAiBriefState = isSellAiBriefReport
    ? readString(detail?.brief_state)
    : null;
  const sellAiBriefReason = isSellAiBriefReport
    ? readString(detail?.brief_reason)
    : null;
  const signalEvalDate = readString(detail?.signal_eval_date);
  const entrySessionDate = readString(detail?.entry_session_date);
  const signalEvalDateByMarket = asRecord(detail?.signal_eval_date_by_market);
  const entrySessionDateByMarket = asRecord(
    detail?.entry_session_date_by_market,
  );
  const systemIssues = asIssueArray(detail?.system_issues);
  const sourceIssues = asIssueArray(detail?.source_issues);
  const aiBriefVetoRows = isAiBriefReport
    ? asRecordArray(detail?.vetoed_candidates)
    : [];
  const sellAiBriefRows = isSellAiBriefReport
    ? asRecordArray(detail?.judgments)
    : [];
  const aiBriefWatchTickers = isAiBriefReport
    ? asStringArray(detail?.watch_tickers)
    : [];
  const aiBriefExecutableTickers = isAiBriefReport
    ? asStringArray(detail?.executable_tickers)
    : [];
  const aiBriefBlockedTickers = isAiBriefReport
    ? asStringArray(detail?.blocked_but_valid_tickers)
    : [];
  const aiBriefWatchRows = isAiBriefReport
    ? asRecordArray(detail?.watch_candidates)
    : [];
  const sourceProviderSummary = isAiBriefReport
    ? asRecord(detail?.source_provider_summary)
    : null;
  const sourceProviderChain = asStringArray(sourceProviderSummary?.chain);
  const sourceProviderFinal = asRecord(sourceProviderSummary?.final);
  const sourceProviderRows = asRecordArray(sourceProviderSummary?.providers);
  const showAiBriefWatchTickers =
    isAiBriefReport &&
    (hasOwnField(detail, "watch_tickers") || aiBriefWatchTickers.length > 0);
  const showAiBriefExecutableTickers =
    isAiBriefReport &&
    (hasOwnField(detail, "executable_tickers") ||
      aiBriefExecutableTickers.length > 0);
  const showAiBriefBlockedTickers =
    isAiBriefReport &&
    (hasOwnField(detail, "blocked_but_valid_tickers") ||
      aiBriefBlockedTickers.length > 0);
  const showAiBriefRecommendationRoles =
    isAiBriefReport &&
    aiBriefRows.some(
      (row) =>
        hasOwnField(row, "candidate_role") ||
        hasOwnField(row, "entry_action") ||
        hasOwnField(row, "candidate_role_reason"),
    );
  const showSourceProviderChain =
    isAiBriefReport && sourceProviderChain.length > 0;
  const showSourceProviderFinal =
    isAiBriefReport && sourceProviderFinal !== null;
  const showSourceProviderStatuses =
    isAiBriefReport && sourceProviderRows.length > 0;
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
            {isModelBriefReport && (
              <div>
                <dt>model_provider</dt>
                <dd>{modelProvider ?? "-"}</dd>
              </div>
            )}
            {isModelBriefReport && (
              <div>
                <dt>model_name</dt>
                <dd>{modelName ?? "-"}</dd>
              </div>
            )}
            {isModelBriefReport && (
              <div>
                <dt>brief_state</dt>
                <dd>{aiBriefState?.state ?? sellAiBriefState ?? "-"}</dd>
              </div>
            )}
            {isModelBriefReport && (
              <div>
                <dt>brief_reason</dt>
                <dd>{aiBriefState?.reason ?? sellAiBriefReason ?? "-"}</dd>
              </div>
            )}
            {showAiBriefWatchTickers && (
              <div>
                <dt>watch_tickers</dt>
                <dd>{formatStringList(aiBriefWatchTickers)}</dd>
              </div>
            )}
            {showAiBriefExecutableTickers && (
              <div>
                <dt>executable_tickers</dt>
                <dd>{formatStringList(aiBriefExecutableTickers)}</dd>
              </div>
            )}
            {showAiBriefBlockedTickers && (
              <div>
                <dt>blocked_but_valid_tickers</dt>
                <dd>{formatStringList(aiBriefBlockedTickers)}</dd>
              </div>
            )}
            {showSourceProviderChain && (
              <div>
                <dt>source_chain</dt>
                <dd>{sourceProviderChain.join(",") || "-"}</dd>
              </div>
            )}
            {showSourceProviderFinal && (
              <div>
                <dt>source_final_coverage</dt>
                <dd>{formatSourceFinalCoverage(sourceProviderFinal)}</dd>
              </div>
            )}
            {showSourceProviderStatuses && (
              <div>
                <dt>source_provider_statuses</dt>
                <dd>{formatSourceProviderStatuses(sourceProviderRows)}</dd>
              </div>
            )}
            {isAiBriefSkipReport && (
              <div>
                <dt>skip_state</dt>
                <dd>{skipState ?? "-"}</dd>
              </div>
            )}
            {isAiBriefSkipReport && (
              <div>
                <dt>skip_reason</dt>
                <dd>{skipReason ?? "-"}</dd>
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
              <dd>{evalSessionState ?? skipSessionState ?? "-"}</dd>
            </div>
            {isAiBriefSkipReport && (
              <div>
                <dt>expected_state</dt>
                <dd>{expectedState ?? "-"}</dd>
              </div>
            )}
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
            {isSellAiBriefReport && (
              <div>
                <dt>source_sell_report</dt>
                <dd>{sourceSellReport ?? "-"}</dd>
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
              AI Brief는 entry 리포트의 실행가능, 차단/검토, watch 후보를
              역할별로 분리해 모델 provider로 요약한 수동 검토용 결과입니다.
            </p>
          )}
          {isSellAiBriefReport && (
            <p className={styles.infoNote}>
              Sell AI Brief는 sell 리포트의 매도 후보를 모델 provider로 요약한
              수동 검토용 결과입니다.
            </p>
          )}
          {isAiBriefSkipReport && (
            <p className={styles.infoNote}>
              AI Brief Skip은 scheduled 실행이 runtime guard에서 중단된 이력을
              기록한 운영용 결과입니다.
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
                    <th>Stop Guide</th>
                    <th>Target Guide</th>
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
                      <td data-label="Stop Guide">
                        {formatGuideValue(row.stop_price)}
                      </td>
                      <td data-label="Target Guide">
                        {formatGuideValue(row.target_price)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {sellAiBriefRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Judgments ({sellAiBriefRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Sell Action</th>
                    <th>AI Stance</th>
                    <th>Confidence</th>
                    <th>Deterministic</th>
                    <th>Rationale</th>
                    <th>Checklist</th>
                    <th>Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {sellAiBriefRows.map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
                      <td data-label="Sell Action">
                        {String(row.sell_action ?? "-")}
                      </td>
                      <td data-label="AI Stance">
                        {String(row.ai_stance ?? "-")}
                      </td>
                      <td data-label="Confidence">
                        {String(row.confidence ?? "-")}
                      </td>
                      <td data-label="Deterministic">
                        {asStringArray(row.deterministic_reasons).join(" · ") ||
                          "-"}
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
                    <th>Readiness</th>
                    <th>Exit Capacity</th>
                    <th>Downside</th>
                    <th>Exposure</th>
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
                      <td data-label="Readiness">
                        {formatEntryReadiness(row)}
                      </td>
                      <td data-label="Exit Capacity">
                        {formatEntryExitCapacity(row)}
                      </td>
                      <td data-label="Downside">
                        {formatEntryDownsideRisk(row)}
                      </td>
                      <td data-label="Exposure">{formatEntryExposure(row)}</td>
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
                    {showAiBriefRecommendationRoles && (
                      <>
                        <th>Role</th>
                        <th>Entry Action</th>
                        <th>Role Reason</th>
                      </>
                    )}
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
                      {showAiBriefRecommendationRoles && (
                        <>
                          <td data-label="Role">
                            {String(row.candidate_role ?? "-")}
                          </td>
                          <td data-label="Entry Action">
                            {String(row.entry_action ?? "-")}
                          </td>
                          <td data-label="Role Reason">
                            {String(row.candidate_role_reason ?? "-")}
                          </td>
                        </>
                      )}
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

          {aiBriefWatchRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Watch candidates ({aiBriefWatchRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Action</th>
                    <th>Reason</th>
                    <th>Retrigger</th>
                    <th>Sources</th>
                  </tr>
                </thead>
                <tbody>
                  {aiBriefWatchRows.map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
                      <td data-label="Action">{String(row.action ?? "-")}</td>
                      <td data-label="Reason">{String(row.reason ?? "-")}</td>
                      <td data-label="Retrigger">
                        {asStringArray(row.retrigger_conditions).join(" · ") ||
                          "-"}
                      </td>
                      <td data-label="Sources">{formatSources(row.sources)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {aiBriefVetoRows.length > 0 && (
            <div className={styles.tableWrap}>
              <h3 className={styles.sectionTitle}>
                Vetoed candidates ({aiBriefVetoRows.length})
              </h3>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Action</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {aiBriefVetoRows.map((row, idx) => (
                    <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
                      <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
                      <td data-label="Action">{String(row.action ?? "-")}</td>
                      <td data-label="Reason">{String(row.reason ?? "-")}</td>
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
