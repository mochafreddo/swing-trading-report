import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MandateEvidenceOutcomeDogfood } from "@/components/mandate-evidence-outcome-dogfood";
import { parsePortfolioDogfoodT14Source } from "@/lib/portfolio-dogfood-t14-schema";

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
  });
});
