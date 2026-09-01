import Link from "next/link";

import type { PortfolioDogfoodT14Source } from "@/lib/portfolio-dogfood-t14-schema";

import styles from "./today-decision-board.module.css";

export function MandateEvidenceOutcomeDogfood({
  source,
  selectedScenarioId,
}: {
  source: PortfolioDogfoodT14Source;
  selectedScenarioId?: string;
}) {
  if (source.state === "INVALID") {
    return (
      <section
        id="mandate-evidence-outcome"
        className={styles.dogfoodPanel}
        aria-labelledby="mandate-evidence-outcome-title"
      >
        <h2 id="mandate-evidence-outcome-title">
          Mandate → Evidence → Outcome
        </h2>
        <p className={styles.errorState}>FIXTURE CONTRACT INVALID</p>
      </section>
    );
  }

  const selection =
    selectedScenarioId ?? source.fixture.scenarios[0]?.scenario_id;
  const scenario = source.fixture.scenarios.find(
    (item) => item.scenario_id === selection,
  );

  return (
    <section
      id="mandate-evidence-outcome"
      className={styles.dogfoodPanel}
      aria-labelledby="mandate-evidence-outcome-title"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.kicker}>Public-only scenario drilldown</p>
          <h2 id="mandate-evidence-outcome-title">
            Mandate → Evidence → Outcome
          </h2>
        </div>
        <span>SYNTHETIC_ONLY · provider NOT_EVALUATED</span>
      </div>

      <nav className={styles.dogfoodTabs} aria-label="Dogfood scenarios">
        {source.fixture.scenarios.map((item) => (
          <Link
            key={item.scenario_id}
            href={`/today?dogfood=${item.scenario_id}#mandate-evidence-outcome`}
            aria-current={
              scenario?.scenario_id === item.scenario_id ? "page" : undefined
            }
          >
            {item.label}
          </Link>
        ))}
      </nav>

      {scenario === undefined ? (
        <div className={styles.errorState} role="status">
          <strong>INVALID SELECTION</strong>
          <span>
            No scenario was inferred. Choose an explicit fixture case.
          </span>
        </div>
      ) : (
        <div className={styles.dogfoodScenario}>
          <div className={styles.queueHeading}>
            <span className={styles.actionBadge}>
              {scenario.instrument.canonical_ticker} · LOCAL_ONLY
            </span>
            <span className={styles.runKind}>{scenario.scenario_id}</span>
          </div>
          <h3>
            {scenario.instrument.company_name}
            <span>{scenario.instrument.instrument_id}</span>
          </h3>

          <div className={styles.dogfoodFlow}>
            <article>
              <p className={styles.kicker}>1 · Mandate</p>
              <h4>{scenario.mandate.state}</h4>
              <p>{scenario.mandate.horizon}</p>
              <p>{scenario.mandate.thesis}</p>
              <code>{scenario.mandate.predicate}</code>
            </article>

            <article>
              <p className={styles.kicker}>2 · Evidence</p>
              <h4>
                {scenario.evidence.state}
                {scenario.evidence.issue_code === null
                  ? ""
                  : ` · ${scenario.evidence.issue_code}`}
              </h4>
              {scenario.evidence.items.map((item) => (
                <div className={styles.evidenceItem} key={item.source_url}>
                  <strong>{item.role}</strong>
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {item.publisher}
                  </a>
                  <span>{item.published_at}</span>
                  <q>{item.supporting_span}</q>
                </div>
              ))}
            </article>

            <article>
              <p className={styles.kicker}>3 · Outcome</p>
              {scenario.outcome.state === "EMPTY" ? (
                <>
                  <h4>EMPTY · NO INFERENCE</h4>
                  <p>No public outcome events yet.</p>
                </>
              ) : scenario.outcome.state === "BLOCKED" ? (
                <>
                  <h4>BLOCKED · {scenario.outcome.issue_code}</h4>
                  <p>Outcome projection withheld.</p>
                </>
              ) : (
                <>
                  <h4>CORRECTED</h4>
                  <p>{scenario.outcome.public_projection?.status}</p>
                  <p>{scenario.outcome.public_projection?.feedback_reason}</p>
                  <p>
                    Correction applied · {scenario.outcome.prior_event_count}{" "}
                    prior events preserved
                  </p>
                  <code>
                    {scenario.outcome.public_projection?.last_event_at}
                  </code>
                </>
              )}
            </article>
          </div>
        </div>
      )}
    </section>
  );
}
