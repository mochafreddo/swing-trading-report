import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  parsePortfolioMandateA1Fixture,
  parsePortfolioMandatePublicEvidenceA1,
  portfolioMandateA1FixtureSchema,
} from "@/lib/portfolio-mandate-schema";

const fixturePath = fileURLToPath(
  new URL(
    "../../../../tests/fixtures/portfolio_mandate/portfolio-mandate-a1.synthetic.json",
    import.meta.url,
  ),
);

const fixture = (): unknown => JSON.parse(readFileSync(fixturePath, "utf8"));

describe("Portfolio Mandate A1 schema", () => {
  it("parses the shared synthetic stable identity fixture", () => {
    const value = fixture();

    expect(parsePortfolioMandateA1Fixture(value)).toEqual(value);
  });

  it("rejects fulfillment that misses the approved numeric threshold", () => {
    const value = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{ observed_value: string | null }>;
      };
    };
    value.predicate_authority_core.events[0].observed_value = "99.99";

    const result = portfolioMandateA1FixtureSchema.safeParse(value);

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toContainEqual(
        expect.objectContaining({
          path: ["predicate_authority_core", "events", 0, "observed_value"],
        }),
      );
    }
  });

  it("requires an activation draft to supersede the exact expected version", () => {
    const value = structuredClone(fixture()) as {
      mandate_version_core: {
        versions: Array<{ supersedes_version_id: string | null }>;
      };
    };
    value.mandate_version_core.versions[1].supersedes_version_id = null;

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("requires activation and user predicate actors to own the mandate", () => {
    const activation = structuredClone(fixture()) as {
      mandate_version_core: {
        activation_commands: Array<{ actor_id: string }>;
      };
    };
    activation.mandate_version_core.activation_commands[0].actor_id =
      "99999999-9999-4999-8999-999999999999";
    expect(portfolioMandateA1FixtureSchema.safeParse(activation).success).toBe(
      false,
    );

    const predicate = structuredClone(fixture()) as {
      predicate_authority_core: { events: Array<{ actor_id: string | null }> };
    };
    predicate.predicate_authority_core.events[1].actor_id =
      "99999999-9999-4999-8999-999999999999";
    expect(portfolioMandateA1FixtureSchema.safeParse(predicate).success).toBe(
      false,
    );
  });

  it("rejects evidence outside an exact alias validity window", () => {
    const value = structuredClone(fixture()) as {
      stable_identity: { evidence_seals: Array<{ source_event_time: string }> };
    };
    value.stable_identity.evidence_seals[0].source_event_time =
      "2024-12-31T23:59:59Z";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("rejects private position fields on the public evidence seal", () => {
    const value = structuredClone(fixture()) as {
      stable_identity: {
        evidence_seals: Array<Record<string, unknown>>;
      };
    };
    value.stable_identity.evidence_seals[0].account_id = "PRIVATE-ACCOUNT";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("keeps the public evidence projection separate from persistence fields", () => {
    const value = structuredClone(fixture()) as {
      stable_identity: { evidence_seals: Array<Record<string, unknown>> };
    };
    const evidence = value.stable_identity.evidence_seals[0];

    expect(parsePortfolioMandatePublicEvidenceA1(evidence)).toEqual(evidence);
    for (const privateField of [
      "account_id",
      "account_ref_hash",
      "quantity",
      "cost",
      "profit_loss",
      "notes",
      "tags",
    ]) {
      expect(() =>
        parsePortfolioMandatePublicEvidenceA1({
          ...evidence,
          [privateField]: "PRIVATE",
        }),
      ).toThrow();
    }
  });

  it("rejects duplicate evidence seal identities", () => {
    const value = structuredClone(fixture()) as {
      stable_identity: { evidence_seals: Array<Record<string, unknown>> };
    };
    value.stable_identity.evidence_seals.push(
      structuredClone(value.stable_identity.evidence_seals[0]),
    );

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("rejects duplicate evidence source scope tuples", () => {
    const value = structuredClone(fixture()) as {
      stable_identity: {
        evidence_seals: Array<Record<string, unknown>>;
      };
    };
    const duplicate = structuredClone(value.stable_identity.evidence_seals[0]);
    duplicate.evidence_seal_id = "99999999-9999-4999-8999-999999999999";
    value.stable_identity.evidence_seals.push(duplicate);

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("rejects an instrument-scoped source rebound to another instrument", () => {
    const value = structuredClone(fixture()) as {
      stable_identity: {
        evidence_seals: Array<Record<string, unknown>>;
      };
    };
    const first = value.stable_identity.evidence_seals[0];
    const rebound = structuredClone(value.stable_identity.evidence_seals[1]);
    rebound.evidence_seal_id = "98989898-9898-4898-8898-989898989898";
    rebound.source_id = first.source_id;
    rebound.scope = "INSTRUMENT";
    value.stable_identity.evidence_seals.push(rebound);

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("keeps AI predicate candidates review-only", () => {
    const value = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{ policy_effect: string }>;
      };
    };
    value.predicate_authority_core.events[2].policy_effect = "SELL_ELIGIBLE";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("requires predicate authority actors to match their producers", () => {
    const value = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{ actor_kind: string }>;
      };
    };
    value.predicate_authority_core.events[2].actor_kind = "DETERMINISTIC";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("only lets corrections supersede an earlier fulfillment", () => {
    const wrongTarget = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{
          predicate_authority_event_id: string;
          supersedes_event_id: string | null;
        }>;
      };
    };
    wrongTarget.predicate_authority_core.events[4].supersedes_event_id =
      wrongTarget.predicate_authority_core.events[2].predicate_authority_event_id;
    expect(portfolioMandateA1FixtureSchema.safeParse(wrongTarget).success).toBe(
      false,
    );

    const wrongTime = structuredClone(fixture()) as {
      predicate_authority_core: { events: Array<{ created_at: string }> };
    };
    wrongTime.predicate_authority_core.events[4].created_at =
      "2026-08-28T00:19:59Z";
    expect(portfolioMandateA1FixtureSchema.safeParse(wrongTime).success).toBe(
      false,
    );
  });

  it("rejects a mandate bound to a broker position for another instrument", () => {
    const value = structuredClone(fixture()) as {
      position_slice_core: {
        broker_positions: Array<{ instrument_id: string }>;
      };
    };
    value.position_slice_core.broker_positions[0].instrument_id =
      "44444444-4444-4444-8444-444444444444";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("matches Python existence, state, and duplicate-id validation", () => {
    const unknownInstrument = structuredClone(fixture()) as {
      mandate_version_core: { mandates: Array<{ instrument_id: string }> };
    };
    unknownInstrument.mandate_version_core.mandates[0].instrument_id =
      "99999999-9999-4999-8999-999999999999";

    const invalidDraftState = structuredClone(fixture()) as {
      mandate_version_core: {
        versions: Array<{ horizon: string | null }>;
      };
    };
    invalidDraftState.mandate_version_core.versions[1].horizon = "SWING";

    const duplicateSlice = structuredClone(fixture()) as {
      position_slice_core: { slices: Array<{ slice_id: string }> };
    };
    duplicateSlice.position_slice_core.slices[1].slice_id =
      duplicateSlice.position_slice_core.slices[0].slice_id;

    const unknownPredicateVersion = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{ mandate_version_id: string }>;
      };
    };
    unknownPredicateVersion.predicate_authority_core.events[0].mandate_version_id =
      "99999999-9999-4999-8999-999999999999";

    for (const value of [
      unknownInstrument,
      invalidDraftState,
      duplicateSlice,
      unknownPredicateVersion,
    ]) {
      expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
        false,
      );
    }
  });

  it("compares decimal quantities without Number precision loss", () => {
    const value = structuredClone(fixture()) as {
      position_slice_core: {
        snapshots: Array<{ quantity: string }>;
        slices: Array<{ quantity: string }>;
      };
    };
    value.position_slice_core.snapshots[0].quantity = "9007199254740992";
    value.position_slice_core.slices[0].quantity = "9007199254740993";
    value.position_slice_core.slices[1].quantity = "0.000000";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("binds activation to the current allocation and snapshot", () => {
    const value = structuredClone(fixture()) as {
      mandate_version_core: {
        activation_commands: Array<{ allocation_version: number }>;
      };
    };
    value.mandate_version_core.activation_commands[0].allocation_version = 2;

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("requires an approved exact predicate definition", () => {
    const value = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{ predicate_id: string }>;
      };
    };
    value.predicate_authority_core.events[0].predicate_id =
      "99999999-9999-4999-8999-999999999999";

    expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
      false,
    );
  });

  it("matches Python slice-state and rebase-evidence validation", () => {
    const invalidSlice = structuredClone(fixture()) as {
      position_slice_core: {
        slices: Array<{
          mandate_version_id: string | null;
          decision_eligible: boolean;
        }>;
      };
    };
    invalidSlice.position_slice_core.slices[0].mandate_version_id = null;
    invalidSlice.position_slice_core.slices[0].decision_eligible = false;

    const invalidEvidence = structuredClone(fixture()) as {
      position_slice_core: {
        rebase_evidence: Array<{ cause: string }>;
      };
    };
    invalidEvidence.position_slice_core.rebase_evidence[0].cause =
      "AMBIGUOUS_SELL";

    for (const value of [invalidSlice, invalidEvidence]) {
      expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
        false,
      );
    }
  });

  it("rejects stale source snapshots and cause/delta mismatches", () => {
    const staleSource = structuredClone(fixture()) as {
      position_slice_core: {
        rebase_commands: Array<{ source_snapshot_version: number }>;
      };
    };
    staleSource.position_slice_core.rebase_commands[0].source_snapshot_version = 2;

    const wrongCause = structuredClone(fixture()) as {
      position_slice_core: {
        rebase_commands: Array<{
          cause: string;
          matched_slice_id: string | null;
        }>;
      };
    };
    wrongCause.position_slice_core.rebase_commands[0].cause = "AMBIGUOUS_SELL";
    wrongCause.position_slice_core.rebase_commands[0].matched_slice_id = null;

    for (const value of [staleSource, wrongCause]) {
      expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
        false,
      );
    }
  });

  it("requires exact activation slices and sealed predicate provenance", () => {
    const wrongVersion = structuredClone(fixture()) as {
      mandate_version_core: {
        versions: Array<{ mandate_version_id: string }>;
      };
      position_slice_core: {
        slices: Array<{ mandate_version_id: string | null }>;
      };
    };
    const draftId =
      wrongVersion.mandate_version_core.versions[1].mandate_version_id;
    for (const positionSlice of wrongVersion.position_slice_core.slices) {
      positionSlice.mandate_version_id = draftId;
    }

    const unknownSeal = structuredClone(fixture()) as {
      predicate_authority_core: {
        events: Array<{ evidence_seal_id: string }>;
      };
    };
    unknownSeal.predicate_authority_core.events[0].evidence_seal_id =
      "99999999-9999-4999-8999-999999999999";

    for (const value of [wrongVersion, unknownSeal]) {
      expect(portfolioMandateA1FixtureSchema.safeParse(value).success).toBe(
        false,
      );
    }
  });
});
