import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MandateEvidenceOutcomeDogfood } from "@/components/mandate-evidence-outcome-dogfood";
import {
  mandateReviewProjectionSchema,
  portfolioReviewR1Schema,
  parsePortfolioDogfoodT14Source,
} from "@/lib/portfolio-dogfood-t14-schema";
import reviewFixture from "../../../fixtures/portfolio-mandate-review.a1.synthetic.json";

import compositeFixture from "../../../fixtures/portfolio-review.r1.synthetic.json";

const fixturePath = fileURLToPath(
  new URL(
    "../../../fixtures/portfolio-dogfood.t14.synthetic.json",
    import.meta.url,
  ),
);

const fixture = (): unknown => JSON.parse(readFileSync(fixturePath, "utf8"));

function renderScenario(selectedScenarioId: string) {
  return renderToStaticMarkup(
    createElement(MandateEvidenceOutcomeDogfood, {
      source: parsePortfolioDogfoodT14Source(fixture()),
      selectedScenarioId,
    }),
  );
}

describe("MandateEvidenceOutcomeDogfood", () => {
  it("renders the SQL composite projection and rejects private fields or advice", () => {
    expect(portfolioReviewR1Schema.safeParse(compositeFixture).success).toBe(
      true,
    );
    const html = renderScenario("corrected-lineage");
    expect(html).toContain("Long-term composite review");
    expect(html).toContain("THESIS INVALIDATED REVIEW REQUIRED");
    for (const row of compositeFixture.rows)
      expect(html).toContain(row.mandate_version_id);
    for (const change of [
      { action: "SELL" },
      { holding_document: "PRIVATE_SENTINEL" },
      { issue_codes: ["UNRECOGNIZED"] },
    ]) {
      expect(
        portfolioReviewR1Schema.safeParse({
          ...compositeFixture,
          rows: [{ ...compositeFixture.rows[0], ...change }],
        }).success,
      ).toBe(false);
    }
    expect(
      portfolioReviewR1Schema.safeParse({
        ...compositeFixture,
        advice_enabled: true,
      }).success,
    ).toBe(false);
  });
  it("uses the Python A1 projection while refusing active advice and private fields", () => {
    expect(mandateReviewProjectionSchema.safeParse(reviewFixture).success).toBe(
      true,
    );
    const html = renderScenario("corrected-lineage");
    expect(html).toContain("A1 version → slice → evidence review");
    expect(html).toContain("ALLOCATION_REBASE_REQUIRED");
    expect(html).toContain("superseded event");
    expect(
      mandateReviewProjectionSchema.safeParse({
        ...reviewFixture,
        advice_enabled: true,
      }).success,
    ).toBe(false);
    const privateRow = {
      ...reviewFixture,
      rows: [{ ...reviewFixture.rows[0], quantity: "PRIVATE_SENTINEL" }],
    };
    expect(mandateReviewProjectionSchema.safeParse(privateRow).success).toBe(
      false,
    );
  });
  it("renders the corrected public lineage without execution-private fields", () => {
    const html = renderScenario("corrected-lineage");

    expect(html).toContain("Mandate → Evidence → Outcome");
    expect(html).toContain("CORRECTED");
    expect(html).toContain("PARTIALLY_EXECUTED");
    expect(html).toContain("OTHER");
    expect(html).toContain("Correction applied · 2 prior events preserved");
    expect(html).toContain('aria-current="page"');
    expect(html).not.toMatch(
      /account_ref_hash|broker_order_id|broker_fill_id|confirmed_quantity|feedback_note_private|Synthetic private correction note/,
    );
  });

  it("renders empty and blocked states without inventing an outcome", () => {
    const empty = renderScenario("empty-outcome");
    const blocked = renderScenario("blocked-evidence");

    expect(empty).toContain("No public outcome events yet");
    expect(empty).toContain("EMPTY · NO INFERENCE");
    expect(blocked).toContain("BLOCKED · EVIDENCE_CONFLICTED");
    expect(blocked).toContain("Outcome projection withheld");
    expect(blocked).not.toContain("PARTIALLY_EXECUTED");
  });

  it("renders loading, stale, and ambiguous states without inference", () => {
    const loading = renderScenario("loading-outcome");
    const stale = renderScenario("stale-evidence");
    const ambiguous = renderScenario("ambiguous-match");

    expect(loading).toContain("LOADING · FIXTURE REPLAY");
    expect(loading).toContain('aria-busy="true"');
    expect(stale).toContain("STALE · EVIDENCE_STALE");
    expect(stale).toContain("Outcome projection withheld");
    expect(ambiguous).toContain("AMBIGUOUS MATCH · REVIEW ONLY");
    expect(ambiguous).toContain("No execution lineage was selected");
  });

  it("fails closed for an unknown selection and an invalid fixture", () => {
    const unknown = renderScenario("not-a-scenario");
    const invalid = renderToStaticMarkup(
      createElement(MandateEvidenceOutcomeDogfood, {
        source: parsePortfolioDogfoodT14Source({ schema_version: "wrong" }),
        selectedScenarioId: "corrected-lineage",
      }),
    );

    expect(unknown).toContain("INVALID SELECTION");
    expect(unknown).toContain("No scenario was inferred");
    expect(invalid).toContain("FIXTURE CONTRACT INVALID");
    expect(invalid).not.toContain("Synthetic private correction note");
  });

  it("uses URL-backed native links for keyboard and refresh persistence", () => {
    const html = renderScenario("empty-outcome");

    expect(html).toContain(
      'href="/today?dogfood=corrected-lineage#mandate-evidence-outcome"',
    );
    expect(html).toContain(
      'href="/today?dogfood=empty-outcome#mandate-evidence-outcome"',
    );
    expect(html).toContain(
      'href="/today?dogfood=blocked-evidence#mandate-evidence-outcome"',
    );
    expect(html).toContain(
      'href="/today?dogfood=invalid-contract#mandate-evidence-outcome"',
    );
  });
});
