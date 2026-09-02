import styles from "../reports-client.module.css";

import { hasOwn } from "@/lib/object-utils";

import { resolveAiBriefState } from "./ai-brief-state";
import { asIssueArray } from "./report-detail-formatters";
import { asRecord, asRecordArray, readNumberLike, readString } from "./helpers";
import type { ReportJson } from "./types";

interface AiBriefDetailProps {
  detail: ReportJson;
  summary: ReportJson | null;
  recommendations: ReportJson[];
  reportKey?: string | null;
  showRaw: boolean;
  rawJson: string;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function readMetric(
  summary: ReportJson | null,
  key: string,
  fallback: number,
): number {
  return readNumberLike(summary?.[key]) ?? fallback;
}

function formatCoverage(covered: unknown, total: unknown): string {
  return `${readNumberLike(covered) ?? "-"}/${readNumberLike(total) ?? "-"}`;
}

function formatFinalCoverage(final: ReportJson | null): string {
  if (!final) {
    return "정보 없음";
  }
  return [
    `추천 ${formatCoverage(final.recommendable_covered, final.recommendable_total)}`,
    `관찰 ${formatCoverage(final.watch_covered, final.watch_total)}`,
  ].join(" · ");
}

function formatTechnicalCoverage(final: ReportJson | null): string {
  if (!final) {
    return "-";
  }
  return [
    `recommendable=${formatCoverage(
      final.recommendable_covered,
      final.recommendable_total,
    )}`,
    `watch=${formatCoverage(final.watch_covered, final.watch_total)}`,
  ].join(" ");
}

function formatProviderStatuses(providers: ReportJson[]): string {
  const values = providers.flatMap((provider) => {
    const name = readString(provider.provider);
    if (!name) {
      return [];
    }
    return [
      `${name} ${readString(provider.status) ?? "-"} ${formatCoverage(
        provider.covered,
        provider.total,
      )}`,
    ];
  });
  return values.join(" · ") || "정보 없음";
}

function reviewLabel(state: string): string {
  if (state.startsWith("NEEDS_REVIEW")) {
    return "수동 검토 필요";
  }
  if (state === "FINAL_JUDGMENT") {
    return "소스 확인 완료";
  }
  if (state === "WATCH_ONLY") {
    return "관찰 전용";
  }
  if (state === "NO_SIGNAL") {
    return "신호 없음";
  }
  return "상태 확인 필요";
}

function sourceLinks(value: unknown) {
  const sources = asRecordArray(value);
  if (sources.length === 0) {
    return <p className={styles.aiBriefEmpty}>등록된 소스 없음</p>;
  }
  return (
    <ul className={styles.aiBriefSources}>
      {sources.map((source, index) => {
        const title = readString(source.title);
        const url = readString(source.url);
        const label = title ?? url ?? `Source ${index + 1}`;
        return (
          <li key={`${url ?? label}-${index}`}>
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ) : (
              label
            )}
          </li>
        );
      })}
    </ul>
  );
}

function textList(items: string[], emptyLabel: string) {
  if (items.length === 0) {
    return <p className={styles.aiBriefEmpty}>{emptyLabel}</p>;
  }
  return (
    <ul className={styles.aiBriefTextList}>
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

export function AiBriefDetail({
  detail,
  summary,
  recommendations,
  reportKey,
  showRaw,
  rawJson,
}: AiBriefDetailProps) {
  const state = resolveAiBriefState(detail);
  const watchRows = asRecordArray(detail.watch_candidates);
  const vetoRows = asRecordArray(detail.vetoed_candidates);
  const sourceSummary = asRecord(detail.source_provider_summary);
  const sourceFinal = asRecord(sourceSummary?.final);
  const sourceProviders = asRecordArray(sourceSummary?.providers);
  const sourceChain = asStringArray(sourceSummary?.chain);
  const systemIssues = asIssueArray(detail.system_issues);
  const sourceIssues = asIssueArray(detail.source_issues);
  const screenOuts = asStringArray(detail.screen_outs);
  const combinedIssues = asStringArray(detail.issues);
  const reviewTone = state.state.startsWith("NEEDS_REVIEW")
    ? "warning"
    : state.state === "FINAL_JUDGMENT"
      ? "positive"
      : "neutral";
  const metrics = [
    {
      label: "추천 가능",
      value: readMetric(summary, "recommendable_count", recommendations.length),
      tone: "default",
    },
    {
      label: "실행 가능",
      value: readMetric(summary, "executable_count", 0),
      tone: "default",
    },
    {
      label: "차단",
      value: readMetric(summary, "blocked_but_valid_count", 0),
      tone: "danger",
    },
    {
      label: "관찰 대상",
      value: readMetric(summary, "watch_count", watchRows.length),
      tone: "accent",
    },
    {
      label: "소스 이슈",
      value: readMetric(summary, "source_issue_count", sourceIssues.length),
      tone: "warning",
    },
  ] as const;
  const issueSections = [
    { label: `System issues (${systemIssues.length})`, items: systemIssues },
    { label: `Source issues (${sourceIssues.length})`, items: sourceIssues },
    { label: `Screen outs (${screenOuts.length})`, items: screenOuts },
    { label: `Issues (${combinedIssues.length})`, items: combinedIssues },
  ].filter((section) => section.items.length > 0);

  return (
    <div className={styles.aiBriefDetail}>
      <dl className={styles.aiBriefContext}>
        <div>
          <dt>생성 시각</dt>
          <dd>{String(detail.generated_at ?? "-")}</dd>
        </div>
        <div>
          <dt>리포트 경로</dt>
          <dd>{reportKey ?? String(detail.schema ?? "-")}</dd>
        </div>
        <div>
          <dt>모델</dt>
          <dd>
            {[readString(detail.model_provider), readString(detail.model_name)]
              .filter(Boolean)
              .join(" · ") || "-"}
          </dd>
        </div>
      </dl>

      <section
        className={styles.aiBriefState}
        data-tone={reviewTone}
        aria-labelledby="ai-brief-state-title"
      >
        <div className={styles.aiBriefStateLead}>
          <span className={styles.aiBriefStateMark} aria-hidden="true">
            <svg viewBox="0 0 24 24" role="presentation">
              <path d="M12 3.5 21 20H3L12 3.5Z" />
              <path d="M12 9v5.2M12 17.2v.1" />
            </svg>
          </span>
          <div>
            <p className={styles.aiBriefLabel}>Review state</p>
            <h3 id="ai-brief-state-title">{state.state}</h3>
            <strong>{reviewLabel(state.state)}</strong>
          </div>
        </div>
        <dl className={styles.aiBriefStateFacts}>
          <div>
            <dt>이유</dt>
            <dd>{state.reason}</dd>
          </div>
          <div>
            <dt>소스 커버리지</dt>
            <dd>{formatFinalCoverage(sourceFinal)}</dd>
          </div>
          <div>
            <dt>프로바이더 상태</dt>
            <dd>{formatProviderStatuses(sourceProviders)}</dd>
          </div>
        </dl>
      </section>

      <dl className={styles.aiBriefMetrics} aria-label="AI Brief 핵심 요약">
        {metrics.map((metric) => (
          <div key={metric.label} data-tone={metric.tone}>
            <dt>{metric.label}</dt>
            <dd>{metric.value}</dd>
          </div>
        ))}
      </dl>

      <section
        className={styles.aiBriefSection}
        aria-label={`Recommendations (${recommendations.length})`}
      >
        <div className={styles.aiBriefSectionHeading}>
          <h3>추천 판단</h3>
          <span>{recommendations.length}건</span>
        </div>
        {recommendations.length === 0 ? (
          <p className={styles.aiBriefEmptyPanel}>
            표시할 추천 판단이 없습니다.
          </p>
        ) : (
          <ol className={styles.aiBriefDecisionList}>
            {recommendations.map((row, index) => (
              <li key={`${String(row.ticker ?? "-")}-${index}`}>
                <article className={styles.aiBriefDecision}>
                  <header className={styles.aiBriefDecisionHeader}>
                    <span className={styles.aiBriefRank}>
                      {String(row.rank ?? index + 1)}
                    </span>
                    <div>
                      <h4>{String(row.ticker ?? "-")}</h4>
                      <p>{String(row.candidate_role_reason ?? "-")}</p>
                    </div>
                    <dl className={styles.aiBriefDecisionMeta}>
                      <div>
                        <dt>Entry Action</dt>
                        <dd>{String(row.entry_action ?? "-")}</dd>
                      </div>
                      <div>
                        <dt>Role</dt>
                        <dd>{String(row.candidate_role ?? "-")}</dd>
                      </div>
                      <div>
                        <dt>Confidence</dt>
                        <dd>{String(row.confidence ?? "-")}</dd>
                      </div>
                    </dl>
                  </header>
                  <div className={styles.aiBriefDecisionBody}>
                    <section>
                      <h5>판단 근거</h5>
                      {textList(asStringArray(row.rationale), "근거 없음")}
                    </section>
                    <section>
                      <h5>행동 전 체크리스트</h5>
                      {textList(
                        asStringArray(row.checklist),
                        "체크리스트 없음",
                      )}
                    </section>
                    <section>
                      <h5>소스</h5>
                      {sourceLinks(row.sources)}
                    </section>
                  </div>
                </article>
              </li>
            ))}
          </ol>
        )}
      </section>

      {watchRows.length > 0 && (
        <section
          className={styles.aiBriefSection}
          aria-label={`Watch candidates (${watchRows.length})`}
        >
          <div className={styles.aiBriefSectionHeading}>
            <h3>관찰 대상</h3>
            <span>{watchRows.length}건</span>
          </div>
          <div className={styles.aiBriefWatchList}>
            {watchRows.map((row, index) => (
              <article key={`${String(row.ticker ?? "-")}-${index}`}>
                <header>
                  <div>
                    <h4>{String(row.ticker ?? "-")}</h4>
                    <p>{String(row.action ?? "WATCH")}</p>
                  </div>
                  <p>{String(row.reason ?? "-")}</p>
                </header>
                <div>
                  <section>
                    <h5>재진입 조건</h5>
                    {textList(
                      asStringArray(row.retrigger_conditions),
                      "재진입 조건 없음",
                    )}
                  </section>
                  <section>
                    <h5>소스</h5>
                    {sourceLinks(row.sources)}
                  </section>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {vetoRows.length > 0 && (
        <section
          className={styles.aiBriefSection}
          aria-label={`Vetoed candidates (${vetoRows.length})`}
        >
          <div className={styles.aiBriefSectionHeading}>
            <h3>제외 판단</h3>
            <span>{vetoRows.length}건</span>
          </div>
          <div className={styles.aiBriefVetoList}>
            {vetoRows.map((row, index) => (
              <article key={`${String(row.ticker ?? "-")}-${index}`}>
                <strong>{String(row.ticker ?? "-")}</strong>
                <span>{String(row.action ?? "-")}</span>
                <p>{String(row.reason ?? "-")}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className={styles.aiBriefLower}>
        {issueSections.length > 0 && (
          <div>
            <h3>이슈</h3>
            <div className={styles.issuesGrid}>
              {issueSections.map((section) => (
                <details key={section.label} className={styles.issueSection}>
                  <summary>{section.label}</summary>
                  <ul>
                    {section.items.map((item, index) => (
                      <li key={`${item}-${index}`}>{item}</li>
                    ))}
                  </ul>
                </details>
              ))}
            </div>
          </div>
        )}

        <details className={styles.aiBriefTechnical}>
          <summary>기술 메타데이터</summary>
          <dl>
            <div>
              <dt>schema</dt>
              <dd>{String(detail.schema ?? "-")}</dd>
            </div>
            <div>
              <dt>type</dt>
              <dd>{String(detail.type ?? "-")}</dd>
            </div>
            <div>
              <dt>market</dt>
              <dd>{String(detail.market ?? "-")}</dd>
            </div>
            <div>
              <dt>model_provider</dt>
              <dd>{String(detail.model_provider ?? "-")}</dd>
            </div>
            <div>
              <dt>model_name</dt>
              <dd>{String(detail.model_name ?? "-")}</dd>
            </div>
            <div>
              <dt>brief_state</dt>
              <dd>{state.state}</dd>
            </div>
            <div>
              <dt>brief_reason</dt>
              <dd>{state.reason}</dd>
            </div>
            <div>
              <dt>source_entry_report</dt>
              <dd>{String(detail.source_entry_report ?? "-")}</dd>
            </div>
            <div>
              <dt>source_buy_report</dt>
              <dd>{String(detail.source_buy_report ?? "-")}</dd>
            </div>
            {sourceChain.length > 0 && (
              <div>
                <dt>source_chain</dt>
                <dd>{sourceChain.join(",")}</dd>
              </div>
            )}
            {hasOwn(detail, "watch_tickers") && (
              <div>
                <dt>watch_tickers</dt>
                <dd>{asStringArray(detail.watch_tickers).join(", ") || "-"}</dd>
              </div>
            )}
            {hasOwn(detail, "executable_tickers") && (
              <div>
                <dt>executable_tickers</dt>
                <dd>
                  {asStringArray(detail.executable_tickers).join(", ") || "-"}
                </dd>
              </div>
            )}
            {hasOwn(detail, "blocked_but_valid_tickers") && (
              <div>
                <dt>blocked_but_valid_tickers</dt>
                <dd>
                  {asStringArray(detail.blocked_but_valid_tickers).join(", ") ||
                    "-"}
                </dd>
              </div>
            )}
            {sourceFinal && (
              <div>
                <dt>source_final_coverage</dt>
                <dd>{formatTechnicalCoverage(sourceFinal)}</dd>
              </div>
            )}
            {sourceProviders.length > 0 && (
              <div>
                <dt>source_provider_statuses</dt>
                <dd>{formatProviderStatuses(sourceProviders)}</dd>
              </div>
            )}
          </dl>
        </details>
      </section>

      {showRaw && (
        <pre id="report-raw-json" className={styles.raw}>
          {rawJson}
        </pre>
      )}
    </div>
  );
}
