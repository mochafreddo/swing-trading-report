import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  compilePortfolioLongTermT13,
  parsePortfolioLongTermT13Fixture,
} from "@/lib/portfolio-long-term-schema";

const fixturePath = fileURLToPath(
  new URL(
    "../../../fixtures/portfolio-long-term.t13.synthetic.json",
    import.meta.url,
  ),
);

const fixture = (): unknown => JSON.parse(readFileSync(fixturePath, "utf8"));

describe("Portfolio LONG_TERM T13 schema", () => {
  it("parses and compiles the shared local-only fixture", () => {
    const value = parsePortfolioLongTermT13Fixture(fixture());

    expect(compilePortfolioLongTermT13(value)).toEqual(
      value.expected_decisions,
    );
    expect(compilePortfolioLongTermT13(structuredClone(value))).toEqual(
      value.expected_decisions,
    );
  });

  it("rejects duplicate case IDs even when expected decisions are rewritten", () => {
    const value = parsePortfolioLongTermT13Fixture(fixture());
    const duplicate = structuredClone(value);
    const firstCase = duplicate.cases[0];
    const secondCase = duplicate.cases[1];
    const secondDecision = duplicate.expected_decisions[1];
    expect(firstCase).toBeDefined();
    expect(secondCase).toBeDefined();
    expect(secondDecision).toBeDefined();
    if (
      firstCase === undefined ||
      secondCase === undefined ||
      secondDecision === undefined
    ) {
      throw new Error("fixture must contain at least two cases");
    }
    secondCase.case_id = firstCase.case_id;
    secondDecision.case_id = firstCase.case_id;

    expect(() => parsePortfolioLongTermT13Fixture(duplicate)).toThrow(
      /case_id.*unique/i,
    );
  });
});

const boundaryCases = JSON.parse(
  readFileSync(
    new URL(
      "../../../../tests/fixtures/portfolio_mandate/long-term-policy-boundary.synthetic.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as {
  name: string;
  path: string[];
  value: unknown;
  action: string | null;
  reason: string;
}[];
it.each(boundaryCases)(
  "rejects unsafe local policy input: $name",
  (boundary) => {
    const value = parsePortfolioLongTermT13Fixture(fixture());
    let target = value.cases[0] as unknown as Record<string, unknown>;
    for (const part of boundary.path.slice(0, -1))
      target = target[part] as Record<string, unknown>;
    target[boundary.path.at(-1)!] = boundary.value;
    const result = compilePortfolioLongTermT13(value)[0];
    expect([result?.action, result?.reason_code]).toEqual([
      boundary.action,
      boundary.reason,
    ]);
  },
);
