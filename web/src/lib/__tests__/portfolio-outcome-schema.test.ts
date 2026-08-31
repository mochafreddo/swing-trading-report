import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  parsePortfolioOutcomeO1Fixture,
  parsePortfolioOutcomePublicProjectionO1,
  portfolioOutcomeO1FixtureSchema,
  proposeOutcomeMatchesO1,
} from "@/lib/portfolio-outcome-schema";

const fixturePath = fileURLToPath(
  new URL(
    "../../../../tests/fixtures/portfolio_mandate/portfolio-outcome-o1.synthetic.json",
    import.meta.url,
  ),
);

const fixture = (): unknown => JSON.parse(readFileSync(fixturePath, "utf8"));

describe("Portfolio Outcome O1 schema", () => {
  it("parses the shared synthetic fixture and reproduces all match states", () => {
    const value = parsePortfolioOutcomeO1Fixture(fixture());

    expect(
      proposeOutcomeMatchesO1(value.decisions, value.execution_lineages),
    ).toEqual(value.expected_proposals);
    expect(value.expected_proposals.map((proposal) => proposal.status)).toEqual(
      ["MATCH_PROPOSED", "AMBIGUOUS", "UNLINKED", "MATCH_PROPOSED"],
    );
    expect(
      value.expected_proposals.every(
        (proposal) => proposal.status !== ("MATCH_CONFIRMED" as string),
      ),
    ).toBe(true);
    expect(value.decisions[2]).toMatchObject({
      side: "BUY",
      slice_id: null,
      candidate_id: "63333333-3333-4333-8333-333333333333",
    });
    expect(value.execution_lineages[3].slice_candidate_ids).toEqual([]);
    expect(value.expected_proposals[3].candidate_decision_ids).toEqual([
      value.decisions[2].decision_id,
    ]);
  });

  it("rejects duplicate broker order, fill, and account hash identities", () => {
    const value = structuredClone(fixture()) as {
      execution_lineages: Array<Record<string, unknown>>;
    };
    const duplicate = structuredClone(value.execution_lineages[0]);
    duplicate.execution_lineage_id = "34444444-4444-4444-8444-444444444444";
    duplicate.outcome_lineage_id = "44444444-4444-4444-8444-444444444444";
    value.execution_lineages.push(duplicate);

    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("requires exact-one slice or candidate targets", () => {
    const value = structuredClone(fixture()) as {
      decisions: Array<{ candidate_id: string | null }>;
    };
    value.decisions[0].candidate_id = "61111111-1111-4111-8111-111111111111";

    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("matches the candidate BUY path without a slice", () => {
    const value = parsePortfolioOutcomeO1Fixture(fixture());
    value.decisions[0].slice_id = null;
    value.decisions[0].candidate_id = "61111111-1111-4111-8111-111111111111";
    value.decisions[0].side = "BUY";
    value.execution_lineages[0].slice_candidate_ids = [];
    value.execution_lineages[0].candidate_id =
      "61111111-1111-4111-8111-111111111111";
    value.execution_lineages[0].side = "BUY";

    expect(
      proposeOutcomeMatchesO1(value.decisions, value.execution_lineages)[0]
        .status,
    ).toBe("MATCH_PROPOSED");
  });

  it("allows only candidate BUY and holding SELL match targets", () => {
    const holdingBuy = structuredClone(fixture()) as {
      decisions: Array<{ side: string }>;
    };
    holdingBuy.decisions[0].side = "BUY";
    expect(portfolioOutcomeO1FixtureSchema.safeParse(holdingBuy).success).toBe(
      false,
    );

    const holdingBuyExecution = structuredClone(fixture()) as {
      execution_lineages: Array<{ side: string }>;
    };
    holdingBuyExecution.execution_lineages[0].side = "BUY";
    expect(
      portfolioOutcomeO1FixtureSchema.safeParse(holdingBuyExecution).success,
    ).toBe(false);

    const candidateSell = structuredClone(fixture()) as {
      decisions: Array<{
        slice_id: string | null;
        candidate_id: string | null;
        side: string;
      }>;
    };
    candidateSell.decisions[0].slice_id = null;
    candidateSell.decisions[0].candidate_id =
      "61111111-1111-4111-8111-111111111111";
    expect(
      portfolioOutcomeO1FixtureSchema.safeParse(candidateSell).success,
    ).toBe(false);

    const candidateSellExecution = structuredClone(fixture()) as {
      execution_lineages: Array<{
        slice_candidate_ids: string[];
        candidate_id: string | null;
      }>;
    };
    candidateSellExecution.execution_lineages[0].slice_candidate_ids = [];
    candidateSellExecution.execution_lineages[0].candidate_id =
      "61111111-1111-4111-8111-111111111111";
    expect(
      portfolioOutcomeO1FixtureSchema.safeParse(candidateSellExecution).success,
    ).toBe(false);
  });

  it("rejects raw accounts and noncanonical wire precision", () => {
    const account = structuredClone(fixture()) as {
      execution_lineages: Array<{ account_ref_hash: string }>;
    };
    account.execution_lineages[0].account_ref_hash = "raw-account-id";
    expect(portfolioOutcomeO1FixtureSchema.safeParse(account).success).toBe(
      false,
    );

    const decimal = structuredClone(fixture()) as {
      execution_lineages: Array<{
        fills: Array<{ price: string; executed_at: string }>;
      }>;
    };
    decimal.execution_lineages[0].fills[0].price = "100.0";
    expect(portfolioOutcomeO1FixtureSchema.safeParse(decimal).success).toBe(
      false,
    );
    decimal.execution_lineages[0].fills[0].price = "100.000000";
    decimal.execution_lineages[0].fills[0].executed_at = "2026-08-01T13:40:00Z";
    expect(portfolioOutcomeO1FixtureSchema.safeParse(decimal).success).toBe(
      false,
    );
  });

  it("requires corrections to supersede the current same-lineage head in time", () => {
    const value = structuredClone(fixture()) as {
      user_events: Array<{
        supersedes_event_id: string | null;
        created_at: string;
      }>;
    };
    value.user_events[2].supersedes_event_id =
      value.user_events[0].supersedes_event_id;
    value.user_events[2].created_at = value.user_events[1].created_at;

    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("binds confirmation to proposal candidates and exact initial quantity", () => {
    const crossLineage = structuredClone(fixture()) as {
      decisions: Array<{ decision_id: string }>;
      user_events: Array<{ decision_id: string | null }>;
    };
    crossLineage.user_events[0].decision_id =
      crossLineage.decisions[1].decision_id;
    expect(
      portfolioOutcomeO1FixtureSchema.safeParse(crossLineage).success,
    ).toBe(false);

    const wrongQuantity = structuredClone(fixture()) as {
      user_events: Array<{ confirmed_quantity: string | null }>;
    };
    wrongQuantity.user_events[0].confirmed_quantity = "9.000000";
    expect(
      portfolioOutcomeO1FixtureSchema.safeParse(wrongQuantity).success,
    ).toBe(false);
    wrongQuantity.user_events[0].confirmed_quantity = "10.000000";
    wrongQuantity.user_events[2].confirmed_quantity = "0.000000";
    expect(
      portfolioOutcomeO1FixtureSchema.safeParse(wrongQuantity).success,
    ).toBe(false);
  });

  it("rejects proposal-only and NO_ACTION user event states", () => {
    for (const status of [
      "UNLINKED",
      "MATCH_PROPOSED",
      "AMBIGUOUS",
      "NO_ACTION",
    ]) {
      const value = structuredClone(fixture()) as {
        user_events: Array<{ status: string }>;
      };
      value.user_events[2].status = status;
      expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
        false,
      );
    }
  });

  it("requires DISMISSED and UNKNOWN to clear decision and quantity", () => {
    for (const status of ["DISMISSED", "UNKNOWN"] as const) {
      const value = structuredClone(fixture()) as {
        user_events: Array<{
          status: string;
          decision_id: string | null;
          confirmed_quantity: string | null;
        }>;
        expected_public_projection: Array<{
          status: string;
          decision_id: string | null;
        }>;
      };
      value.user_events[2].status = status;
      expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
        false,
      );

      value.user_events[2].decision_id = null;
      value.user_events[2].confirmed_quantity = null;
      value.expected_public_projection[0].status = status;
      value.expected_public_projection[0].decision_id = null;
      expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
        true,
      );
    }
  });

  it("requires a nonempty private note for OTHER", () => {
    const value = structuredClone(fixture()) as {
      user_events: Array<{ feedback_note_private: string | null }>;
    };
    value.user_events[2].feedback_note_private = null;

    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("strictly rejects all private execution fields in public projection", () => {
    const value = parsePortfolioOutcomeO1Fixture(fixture());
    const projection = value.expected_public_projection[0];

    expect(parsePortfolioOutcomePublicProjectionO1(projection)).toEqual(
      projection,
    );
    for (const privateField of [
      "confirmed_quantity",
      "price",
      "account_ref_hash",
      "broker_order_id",
      "broker_fill_id",
      "feedback_note_private",
    ]) {
      expect(() =>
        parsePortfolioOutcomePublicProjectionO1({
          ...projection,
          [privateField]: "PRIVATE",
        }),
      ).toThrow();
    }
  });

  it("rejects unknown fields and provider or attribution claims", () => {
    const value = structuredClone(fixture()) as {
      capability: {
        provider_history_state: string;
        performance_attribution: string;
      };
      execution_lineages: Array<Record<string, unknown>>;
    };
    value.execution_lineages[0].private_note = "PRIVATE";
    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );

    delete value.execution_lineages[0].private_note;
    value.capability.provider_history_state = "VERIFIED";
    value.capability.performance_attribution = "ENABLED";
    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("keeps every synthetic fill inside the declared retention window", () => {
    const value = structuredClone(fixture()) as {
      capability: { retention_window: { ends_at: string } };
    };
    value.capability.retention_window.ends_at = "2026-08-01T13:39:59.999Z";

    expect(portfolioOutcomeO1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });
});
