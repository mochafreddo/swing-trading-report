"use client";

import { useRef, useState } from "react";

import {
  parseLocalPortfolioPreviewText,
  type LocalPortfolioPreview,
  type PortfolioMandatePrivatePreview,
} from "@/lib/portfolio-mandate-private-preview-schema";
import type { UnclassifiedQueuePreviewInput } from "@/lib/portfolio-mandate-a2-private-input-schema";

import styles from "./today-decision-board.module.css";

type UnclassifiedHolding = Extract<
  UnclassifiedQueuePreviewInput["holdings"][number],
  { classification_state: "UNCLASSIFIED" }
>;

const EMPTY_STATUS =
  "Choose the synthetic or private JSON file when you are ready. Nothing is uploaded.";
const MAX_LOCAL_PREVIEW_FILE_BYTES = 1_000_000;

type PrivateMandateHolding = PortfolioMandatePrivatePreview["holdings"][number];

function horizonTask(holding: UnclassifiedHolding): string {
  return holding.proposed_horizon === null
    ? "Provide and confirm the intended horizon"
    : `Confirm the unapproved ${holding.proposed_horizon} horizon draft`;
}

function thesisTask(holding: UnclassifiedHolding): string {
  return holding.thesis_recall === "REMEMBERED"
    ? "Confirm the recalled thesis"
    : "Provide and confirm the thesis";
}

function invalidationTask(holding: UnclassifiedHolding): string {
  return holding.invalidation_recall === "REMEMBERED"
    ? "Confirm the recalled invalidation conditions"
    : "Provide and confirm invalidation conditions";
}

function triggerSummary(
  trigger: PrivateMandateHolding["invalidation_policy"]["hard_triggers"][number],
): string | null {
  if (trigger.conditions === undefined) {
    return null;
  }
  return `${trigger.condition_match ?? "ALL"} · ${trigger.conditions.length} ${
    trigger.conditions.length === 1 ? "condition" : "conditions"
  }`;
}

function UnclassifiedPreviewResult({
  preview,
}: {
  preview: UnclassifiedQueuePreviewInput;
}) {
  return (
    <div className={styles.localPreviewResult}>
      <dl className={styles.localPreviewScope}>
        <div>
          <dt>Observed snapshot</dt>
          <dd>
            <time dateTime={preview.snapshot.observed_at_kst}>
              {preview.snapshot.observed_at_kst}
            </time>
          </dd>
        </div>
        <div>
          <dt>Preview scope</dt>
          <dd>
            Top-5 subset of a {preview.snapshot.holding_count}-holding snapshot
          </dd>
        </div>
      </dl>
      <p className={styles.localPreviewCaveat}>
        Historical snapshot scope only — not a current, freshness-proven, or
        complete portfolio view.
      </p>

      <div
        className={styles.unclassifiedGrid}
        aria-label="Unclassified local preview rows"
      >
        {preview.holdings.map((holding, index) => (
          <article
            className={styles.unclassifiedCard}
            key={`${holding.ticker}:${index}`}
          >
            <div className={styles.queueHeading}>
              <span className={styles.unclassifiedBadge}>
                UNCLASSIFIED · NO ADVICE
              </span>
            </div>
            <h3>{holding.ticker}</h3>
            <p className={styles.unapprovedDraft}>
              UNAPPROVED DRAFT · {holding.proposed_horizon ?? "NO HORIZON"}
            </p>
            <h4>Confirmation tasks</h4>
            <ul>
              <li>{horizonTask(holding)}</li>
              <li>{thesisTask(holding)}</li>
              <li>{invalidationTask(holding)}</li>
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}

function PrivateMandatePreviewResult({
  preview,
}: {
  preview: PortfolioMandatePrivatePreview;
}) {
  const coreCount = preview.holdings.filter(
    (holding) => holding.role === "CORE",
  ).length;

  return (
    <div className={styles.localPreviewResult}>
      <dl className={styles.localPreviewScope}>
        <div>
          <dt>Mandate date</dt>
          <dd>
            <time dateTime={preview.decision_date}>
              {preview.decision_date}
            </time>
          </dd>
        </div>
        <div>
          <dt>Preview scope</dt>
          <dd>
            {coreCount} CORE · {preview.holdings.length - coreCount} SATELLITE
          </dd>
        </div>
        <div>
          <dt>Valuation queue</dt>
          <dd>{preview.portfolio_policy.valuation_queue.join(" → ")}</dd>
        </div>
        <div>
          <dt>Review state</dt>
          <dd>
            {preview.review_state.review_due ? "DUE" : "NOT DUE"} · NO
            AUTOMATION
          </dd>
        </div>
      </dl>
      <p className={styles.localPreviewCaveat}>
        Private local draft only. It is not active advice, an approval event, or
        an instruction to trade.
      </p>

      <div
        className={styles.privateMandateGrid}
        aria-label="Private portfolio mandate preview rows"
      >
        {preview.holdings.map((holding) => (
          <article className={styles.privateMandateCard} key={holding.ticker}>
            <div className={styles.queueHeading}>
              <span className={styles.unclassifiedBadge}>
                PRIVATE DRAFT · NO ADVICE · NOT ACTIVE
              </span>
              <span className={styles.runKind}>{holding.role}</span>
            </div>
            <h3>{holding.ticker}</h3>

            <h4>Thesis</h4>
            <p>{holding.thesis}</p>

            <h4>Composite invalidation</h4>
            <ul>
              {holding.invalidation_policy.hard_triggers.map((trigger) => (
                <li key={trigger.id}>
                  <strong>{trigger.id}</strong>: {trigger.description}
                  {triggerSummary(trigger) === null ? null : (
                    <small>{triggerSummary(trigger)}</small>
                  )}
                </li>
              ))}
              <li>
                <strong>Deterioration:</strong>{" "}
                {holding.invalidation_policy.deterioration_rule.minimum_matches}
                {" of "}
                {holding.invalidation_policy.deterioration_rule.signals.length}
                {" signals for "}
                {
                  holding.invalidation_policy.deterioration_rule
                    .consecutive_periods
                }
                {" consecutive quarters"}
              </li>
            </ul>

            <h4>Concentration</h4>
            <p className={styles.privateMandateState}>
              {holding.concentration.individual_status} ·{" "}
              {holding.concentration.estimated_weight_pct}% ESTIMATE
              {holding.concentration.sector_status === undefined
                ? ""
                : ` · ${holding.concentration.sector_status}`}
            </p>

            <h4>Frozen addition</h4>
            <p className={styles.privateMandateState}>
              {holding.addition_policy.status}
            </p>
            <ul>
              {holding.addition_policy.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>

            <h4>Evidence references</h4>
            <ul className={styles.privateEvidenceList}>
              {holding.evidence.map((evidence) => (
                <li key={`${evidence.source_type}:${evidence.url}`}>
                  <a
                    href={evidence.url}
                    rel="noreferrer noopener"
                    target="_blank"
                  >
                    {evidence.title}
                  </a>
                  <small>
                    {evidence.source_type} · {evidence.published_on}
                  </small>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}

export function UnclassifiedQueuePreview() {
  const inputRef = useRef<HTMLInputElement>(null);
  const readGenerationRef = useRef(0);
  const [preview, setPreview] = useState<LocalPortfolioPreview | null>(null);
  const [status, setStatus] = useState(EMPTY_STATUS);
  const [error, setError] = useState<string | null>(null);

  async function handleFileSelected(file: File | undefined) {
    const readGeneration = ++readGenerationRef.current;
    setPreview(null);
    setError(null);
    if (file === undefined) {
      setStatus(EMPTY_STATUS);
      return;
    }

    if (file.size > MAX_LOCAL_PREVIEW_FILE_BYTES) {
      setError(
        "This file is too large for the local preview. Nothing was read or uploaded.",
      );
      setStatus("Local preview rejected.");
      return;
    }

    setStatus("Reading and validating locally in browser memory...");
    try {
      const document = parseLocalPortfolioPreviewText(await file.text());
      if (readGeneration !== readGenerationRef.current) {
        return;
      }
      setPreview(document);
      setStatus(
        `Local preview ready: ${document.document.holdings.length} validated rows. No data was uploaded.`,
      );
    } catch {
      if (readGeneration !== readGenerationRef.current) {
        return;
      }
      setError(
        "This file is not valid local preview JSON. Nothing was loaded or uploaded.",
      );
      setStatus("Local preview rejected.");
    }
  }

  function clearPreview() {
    readGenerationRef.current += 1;
    setPreview(null);
    setError(null);
    setStatus("Local preview cleared from browser memory.");
    if (inputRef.current !== null) {
      inputRef.current.value = "";
    }
  }

  return (
    <section
      className={styles.localPreview}
      aria-labelledby="unclassified-preview-title"
    >
      <div className={styles.sectionHeading}>
        <div>
          <p className={styles.kicker}>Local preview · memory-only</p>
          <h2 id="unclassified-preview-title">Unclassified Queue</h2>
        </div>
        <span>NO UPLOAD · NO WRITE · NO ADVICE</span>
      </div>

      <p className={styles.localPreviewNotice}>
        Open a strict JSON snapshot in this browser tab only. The file is not
        uploaded or persisted; refresh clears the selected private data.
      </p>
      <div className={styles.localPreviewControls}>
        <label htmlFor="unclassified-preview-file">
          Unclassified queue JSON
        </label>
        <input
          ref={inputRef}
          id="unclassified-preview-file"
          type="file"
          accept="application/json,.json"
          onClick={(event) => {
            event.currentTarget.value = "";
          }}
          onChange={(event) => {
            void handleFileSelected(event.currentTarget.files?.[0]);
          }}
        />
        <button type="button" onClick={clearPreview}>
          Clear local preview
        </button>
      </div>
      <p className={styles.localPreviewStatus} role="status" aria-live="polite">
        {status}
      </p>
      {error === null ? null : (
        <p className={styles.localPreviewError} role="alert">
          {error}
        </p>
      )}

      {preview?.kind === "UNCLASSIFIED_A2" ? (
        <UnclassifiedPreviewResult preview={preview.document} />
      ) : preview?.kind === "PRIVATE_MANDATE_V1" ? (
        <PrivateMandatePreviewResult preview={preview.document} />
      ) : null}
    </section>
  );
}
