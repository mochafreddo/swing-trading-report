import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  parseLocalPortfolioPreviewText,
  parsePortfolioMandatePrivatePreviewText,
  portfolioMandatePrivatePreviewSchema,
} from "@/lib/portfolio-mandate-private-preview-schema";

const fixturePath = resolve(
  process.cwd(),
  "../tests/fixtures/portfolio_mandate/portfolio-mandate-private-v1-preview.synthetic.json",
);

const fixtureText = () => readFileSync(fixturePath, "utf8");

const fixture = (): Record<string, unknown> =>
  JSON.parse(fixtureText()) as Record<string, unknown>;

const holdings = (input: Record<string, unknown>) =>
  input.holdings as Array<Record<string, unknown>>;

const policy = (input: Record<string, unknown>) =>
  input.portfolio_policy as Record<string, unknown>;

describe("portfolio-mandate private preview contract", () => {
  it("parses the synthetic eight-holding v1 overlay through the strict text boundary", () => {
    const parsed = parsePortfolioMandatePrivatePreviewText(fixtureText());

    expect(parsed.schema_version).toBe("portfolio-mandate-private.v1");
    expect(parsed.holdings).toHaveLength(8);
    expect(
      parsed.holdings.filter((holding) => holding.role === "CORE"),
    ).toHaveLength(5);
    expect(
      parsed.holdings.filter((holding) => holding.role === "SATELLITE"),
    ).toHaveLength(3);
    expect(
      parsed.holdings[0].invalidation_policy.hard_triggers[0].condition_match,
    ).toBeUndefined();
    expect(parsed.portfolio_policy.valuation_queue).toEqual([
      "ALFA.NAS",
      "BRAV.NYS",
      "CHAR.NAS",
    ]);
  });

  it.each([
    [
      "an unknown field",
      (input: Record<string, unknown>) => {
        input.account_identifier = "must-never-pass";
      },
    ],
    [
      "a duplicate holding ticker",
      (input: Record<string, unknown>) => {
        holdings(input)[1].ticker = holdings(input)[0].ticker;
      },
    ],
    [
      "the wrong CORE/SATELLITE split",
      (input: Record<string, unknown>) => {
        holdings(input)[4].role = "SATELLITE";
      },
    ],
    [
      "a condition match without conditions",
      (input: Record<string, unknown>) => {
        const invalidation = holdings(input)[2].invalidation_policy as Record<
          string,
          unknown
        >;
        const triggers = invalidation.hard_triggers as Array<
          Record<string, unknown>
        >;
        triggers[0].condition_match = "ALL";
      },
    ],
    [
      "a queue ticker outside the holdings",
      (input: Record<string, unknown>) => {
        policy(input).valuation_queue = ["ALFA.NAS", "OUTS.NAS"];
      },
    ],
    [
      "an inverted concentration threshold",
      (input: Record<string, unknown>) => {
        const thresholds = policy(input).concentration_thresholds_pct as Record<
          string,
          unknown
        >;
        thresholds.individual_warning = 25;
      },
    ],
    [
      "a partial portfolio weight total",
      (input: Record<string, unknown>) => {
        const concentration = holdings(input)[0].concentration as Record<
          string,
          unknown
        >;
        concentration.estimated_weight_pct = 1;
      },
    ],
    [
      "a duplicate prohibited operation",
      (input: Record<string, unknown>) => {
        policy(input).prohibited_operations = ["ORDER_CREATE", "ORDER_CREATE"];
      },
    ],
  ])("rejects %s as one indivisible contract", (_label, mutate) => {
    const input = fixture();
    mutate(input);

    expect(portfolioMandatePrivatePreviewSchema.safeParse(input).success).toBe(
      false,
    );
  });

  it("rejects duplicate JSON keys before schema dispatch", () => {
    const duplicateKeyText = fixtureText().replace(
      '"schema_version": "portfolio-mandate-private.v1",',
      '"schema_version": "portfolio-mandate-private.v1",\n  "schema_version": "portfolio-mandate-private.v1",',
    );

    expect(() => parseLocalPortfolioPreviewText(duplicateKeyText)).toThrow(
      "duplicate JSON object key",
    );
  });

  it("rejects an unknown local-preview schema without fallback parsing", () => {
    const input = fixture();
    input.schema_version = "portfolio-mandate-private.v2";

    expect(() => parseLocalPortfolioPreviewText(JSON.stringify(input))).toThrow(
      "Unsupported local portfolio preview schema",
    );
  });
});
