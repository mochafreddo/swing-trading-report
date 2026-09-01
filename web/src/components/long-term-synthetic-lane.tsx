import {
  compilePortfolioLongTermT13,
  type PortfolioLongTermT13Fixture,
} from "@/lib/portfolio-long-term-schema";

import styles from "./today-decision-board.module.css";

export function LongTermSyntheticLane({
  fixture,
}: {
  fixture: PortfolioLongTermT13Fixture;
}) {
  const decisions = compilePortfolioLongTermT13(fixture);
  return (
    <section
      className={styles.localPreview}
      aria-labelledby="long-term-synthetic-title"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.kicker}>Synthetic policy dogfood</p>
          <h2 id="long-term-synthetic-title">LONG_TERM synthetic lane</h2>
        </div>
        <span>{decisions.length} synthetic cases · LOCAL_ONLY</span>
      </div>

      <p className={styles.localPreviewCaveat}>
        No real holding, provider, database, or order connection. Every result
        is fixture-backed audit evidence and remains LOCAL_ONLY · NOT ACTIVE.
      </p>

      <div
        className={styles.longTermGrid}
        aria-label="Synthetic LONG_TERM cases"
      >
        {fixture.cases.map((item, index) => {
          const decision = decisions[index];
          if (decision === undefined) {
            return null;
          }
          const noAdvice = decision.status === "NO_ADVICE";
          return (
            <article className={styles.longTermCard} key={item.case_id}>
              <div className={styles.queueHeading}>
                <span
                  className={
                    noAdvice ? styles.unclassifiedBadge : styles.actionBadge
                  }
                >
                  {noAdvice
                    ? "UNCLASSIFIED · NO ADVICE"
                    : `${decision.action ?? decision.status} · LOCAL_ONLY · NOT ACTIVE`}
                </span>
                <span className={styles.runKind}>{item.case_id}</span>
              </div>
              <h3>
                {item.instrument.canonical_ticker}
                <span>{item.instrument.company_name}</span>
              </h3>
              <p className={styles.notActive}>{decision.reason_code}</p>

              <dl className={styles.longTermFacts}>
                <div>
                  <dt>Mandate</dt>
                  <dd>
                    {item.mandate.classification_state} ·{" "}
                    {item.mandate.approval_state}
                  </dd>
                </div>
                <div>
                  <dt>Cadence</dt>
                  <dd>
                    {item.mandate.review_cadence.kind} ·{" "}
                    {item.mandate.review_cadence.due ? "DUE" : "NOT DUE"}
                  </dd>
                </div>
                <div>
                  <dt>Evidence</dt>
                  <dd>
                    {item.evidence.validation_status} ·{" "}
                    {item.evidence.source_tier}
                  </dd>
                </div>
                <div>
                  <dt>Concentration</dt>
                  <dd>{item.concentration.status}</dd>
                </div>
              </dl>

              {item.mandate.thesis === null ? (
                <p className={styles.issueCodes}>
                  No approved thesis or invalidation predicate.
                </p>
              ) : (
                <>
                  <h4>Approved thesis</h4>
                  <p className={styles.issueCodes}>{item.mandate.thesis}</p>
                  <h4>Observable invalidation</h4>
                  <p className={styles.issueCodes}>
                    {item.mandate.invalidation_predicate.metric}{" "}
                    {item.mandate.invalidation_predicate.operator}{" "}
                    {item.mandate.invalidation_predicate.threshold}{" "}
                    {item.mandate.invalidation_predicate.unit} ·{" "}
                    {item.mandate.invalidation_predicate.period}
                  </p>
                </>
              )}

              <h4>Primary filing evidence</h4>
              <p className={styles.issueCodes}>
                <a
                  href={item.evidence.filing_event.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {item.evidence.filing_event.publisher}
                </a>{" "}
                · {item.evidence.filing_event.period} ·{" "}
                {item.evidence.filing_event.published_at}
              </p>
              <p className={styles.issueCodes}>
                “{item.evidence.filing_event.supporting_span}”
              </p>
              <p className={styles.sourceStatus}>
                Predicate: {item.evidence.predicate_evaluation.result} ·
                Authority: {item.evidence.predicate_evaluation.authority}
              </p>
            </article>
          );
        })}
      </div>
    </section>
  );
}
