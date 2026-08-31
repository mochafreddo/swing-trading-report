"use client";

import { useRef, useState } from "react";

import {
  parseUnclassifiedQueuePreviewInput,
  type UnclassifiedQueuePreviewInput,
} from "@/lib/portfolio-mandate-a2-private-input-schema";

import styles from "./today-decision-board.module.css";

type UnclassifiedHolding = Extract<
  UnclassifiedQueuePreviewInput["holdings"][number],
  { classification_state: "UNCLASSIFIED" }
>;

const EMPTY_STATUS =
  "Choose the synthetic or private JSON file when you are ready. Nothing is uploaded.";
const MAX_LOCAL_PREVIEW_FILE_BYTES = 1_000_000;

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

export function UnclassifiedQueuePreview() {
  const inputRef = useRef<HTMLInputElement>(null);
  const readGenerationRef = useRef(0);
  const [preview, setPreview] = useState<UnclassifiedQueuePreviewInput | null>(
    null,
  );
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
      const document = JSON.parse(await file.text()) as unknown;
      if (readGeneration !== readGenerationRef.current) {
        return;
      }
      const parsed = parseUnclassifiedQueuePreviewInput(document);
      setPreview(parsed);
      setStatus(
        `Local preview ready: ${parsed.holdings.length} unclassified rows. No data was uploaded.`,
      );
    } catch {
      if (readGeneration !== readGenerationRef.current) {
        return;
      }
      setError(
        "This file is not valid unclassified queue JSON. Nothing was loaded or uploaded.",
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

      {preview === null ? null : (
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
                Top-5 subset of a {preview.snapshot.holding_count}-holding
                snapshot
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
      )}
    </section>
  );
}
