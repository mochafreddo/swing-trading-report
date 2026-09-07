import type { StoredReviewSource } from "@/lib/portfolio-review-store-schema";

import styles from "./today-decision-board.module.css";

const reviewLabels = {
  BLOCKED: "검토 차단 · 입력 확인 필요",
  REVIEW_REQUIRED: "추가 검토 필요",
  THESIS_INVALIDATED_REVIEW_REQUIRED:
    "투자 근거 무효화 조건 확인 · 재검토 필요",
  NO_TRIGGER_OBSERVED: "확인한 관측에서 무효화 조건 미충족",
};
const outcomeLabels = {
  UNLINKED: "검토와 연결되지 않은 주문 결과",
  AMBIGUOUS: "연결이 모호한 주문 결과",
  NO_ACTION: "사용자가 아무 행동도 하지 않았음을 확인",
};

export function PortfolioStoredReview({
  source,
  synthetic = false,
}: {
  source: StoredReviewSource;
  synthetic?: boolean;
}) {
  return (
    <section
      className={styles.dogfoodPanel}
      aria-labelledby="stored-review-title"
      id="stored-review"
    >
      <h2 id="stored-review-title">저장된 검토 → Outcome</h2>
      <p>
        {synthetic
          ? "SYNTHETIC_ONLY · 폐기형 DB 조회 결과"
          : "LOCAL_ONLY · 인증 owner/version 연결 필요"}{" "}
        · 조언 비활성
      </p>
      {source.state !== "READY" ? (
        <p role="status">
          {source.state === "DISABLED"
            ? "DISABLED · 실제 인증 연결은 꺼져 있습니다."
            : source.state === "STALE"
              ? "STALE · 저장된 검토가 만료되어 표시를 중단했습니다."
              : "UNAVAILABLE · 검토를 읽을 수 없습니다. 이전 결과를 사용하지 않습니다."}
        </p>
      ) : (
        source.value.rows.map((row, index) => (
          <article key={row.mandate_version_id}>
            <h3>
              검토 {index + 1} · Version {row.mandate_version_id.slice(0, 8)}
            </h3>
            {row.run_id === null ? (
              <p>EMPTY · 저장된 검토 없음</p>
            ) : (
              <>
                <p>
                  {row.run_status === "BLOCKED"
                    ? reviewLabels.BLOCKED
                    : row.review && reviewLabels[row.review.status]}
                </p>
                <p>검토 전용 · 매수·매도 조언 없음</p>
                <p>
                  검토 시각{" "}
                  <time dateTime={row.as_of ?? undefined}>
                    {row.as_of &&
                      new Date(row.as_of)
                        .toISOString()
                        .slice(0, 19)
                        .replace("T", " ")}{" "}
                    UTC
                  </time>
                </p>
                <details>
                  <summary>검토 근거와 정정 이력</summary>
                  <p>
                    Version <code>{row.mandate_version_id}</code>
                  </p>
                  <p>
                    {row.run_status} · {row.review?.status} · action=null
                  </p>
                  <p>
                    Run <code>{row.run_id}</code>
                  </p>
                  <p>
                    PRIMARY 관측 {row.review?.current_observation_count}개 ·
                    정정 전 관측 {row.review?.superseded_observation_count}개
                  </p>
                  <p>
                    {row.review?.issue_codes.join(" · ") ||
                      "확인된 차단 사유 없음"}
                  </p>
                  <p>원문과 관측값은 이 화면에 노출하지 않습니다.</p>
                </details>
                <h4>Outcome</h4>
                {row.outcomes.length === 0 ? (
                  <p>아직 기록된 Outcome이 없습니다.</p>
                ) : (
                  <ul>
                    {row.outcomes.map((o) => (
                      <li key={o.outcome_id}>
                        {outcomeLabels[o.status]} ({o.status})
                        {o.supersedes_outcome_id ? " · 이전 기록 정정" : ""}
                      </li>
                    ))}
                  </ul>
                )}
                <p>
                  주문 누적 결과만으로 체결이나 Decision 연결을 확정하지
                  않습니다.
                </p>
              </>
            )}
          </article>
        ))
      )}
    </section>
  );
}
