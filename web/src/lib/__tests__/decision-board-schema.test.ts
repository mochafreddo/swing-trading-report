import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  DecisionBoardIntegrityError,
  canonicalDecisionPayloadBytesV0,
  claimValidationV0Schema,
  decisionPayloadHashV0,
  decisionBoardEnvelopeV0Schema,
  parseDecisionBoardReportStructure,
  parseVerifiedDecisionBoardReport,
  safeParseDecisionBoardReportStructure,
  safeParseVerifiedDecisionBoardReport,
} from "@/lib/decision-board-schema";

const fixturePath = (name: string) =>
  fileURLToPath(
    new URL(
      `../../../../tests/fixtures/decision_board/${name}`,
      import.meta.url,
    ),
  );

const loadFixture = (name: string): unknown =>
  JSON.parse(readFileSync(fixturePath(name), "utf8"));

type MutablePublishedReport = {
  status: string;
  issues: unknown[];
  decision_payload: {
    items: Array<{
      action?: string;
      evidence: Array<{ entailment: string }>;
    }>;
  };
  decision_payload_hash: string;
};

const loadPublishedFixture = (): MutablePublishedReport =>
  loadFixture("published-entry.json") as MutablePublishedReport;

describe("Decision Board V0 schema", () => {
  it.each(["published-entry.json", "published-holding.json", "blocked.json"])(
    "parses shared golden fixture %s",
    (name) => {
      const fixture = loadFixture(name);

      expect(parseDecisionBoardReportStructure(fixture)).toEqual(fixture);
      expect(safeParseDecisionBoardReportStructure(fixture).success).toBe(true);
    },
  );

  it.each(["published-entry.json", "published-holding.json", "blocked.json"])(
    "verifies shared golden fixture %s through the async integrity boundary",
    async (name) => {
      const fixture = loadFixture(name);

      await expect(parseVerifiedDecisionBoardReport(fixture)).resolves.toEqual(
        fixture,
      );
      expect(
        (await safeParseVerifiedDecisionBoardReport(fixture)).success,
      ).toBe(true);
    },
  );

  it("uses recursive sorted-key compact UTF-8 canonicalization for payload hashes", async () => {
    const fixture = loadPublishedFixture();
    const parsed = parseDecisionBoardReportStructure(fixture);
    expect(parsed.status).toBe("PUBLISHED");
    if (parsed.status !== "PUBLISHED") {
      return;
    }
    const unicodePayload = structuredClone(parsed.decision_payload);
    unicodePayload.items[0].instrument.company_name = "오로라 시스템즈";
    const canonicalText = new TextDecoder().decode(
      canonicalDecisionPayloadBytesV0(unicodePayload),
    );

    expect(canonicalText).toContain("오로라 시스템즈");
    expect(canonicalText.startsWith('{"items":')).toBe(true);
    expect(canonicalText).not.toContain(": ");

    await expect(decisionPayloadHashV0(fixture.decision_payload)).resolves.toBe(
      fixture.decision_payload_hash,
    );
  });

  it("rejects the shared conditional-invariant fixture", () => {
    const result = safeParseDecisionBoardReportStructure(
      loadFixture("invalid-review-action.json"),
    );

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            path: ["decision_payload", "items", 0, "action"],
          }),
        ]),
      );
    }
  });

  it("rejects unknown envelope and nested fields", () => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;
    expect(
      decisionBoardEnvelopeV0Schema.safeParse({ ...fixture, surprise: true })
        .success,
    ).toBe(false);

    const nested = structuredClone(fixture) as {
      decision_payload: { items: Array<Record<string, unknown>> };
    };
    nested.decision_payload.items[0].surprise = true;
    expect(decisionBoardEnvelopeV0Schema.safeParse(nested).success).toBe(false);
  });

  it("rejects naive timestamps and malformed hashes", () => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;

    expect(
      decisionBoardEnvelopeV0Schema.safeParse({
        ...fixture,
        created_at: "2026-08-06T01:00:05",
      }).success,
    ).toBe(false);

    const malformed = structuredClone(fixture) as {
      decision_payload_hash: string;
    };
    malformed.decision_payload_hash = `sha256:${"A".repeat(64)}`;
    expect(decisionBoardEnvelopeV0Schema.safeParse(malformed).success).toBe(
      false,
    );
  });

  it("rejects an impossible ISO calendar date", () => {
    const fixture = loadPublishedFixture();

    expect(
      decisionBoardEnvelopeV0Schema.safeParse({
        ...fixture,
        created_at: "2026-02-30T01:00:05Z",
      }).success,
    ).toBe(false);
  });

  it("rejects evidence locations whose end precedes start", () => {
    const fixture = loadPublishedFixture();
    const instrument = (
      fixture.decision_payload.items[0] as unknown as {
        instrument: Record<string, unknown>;
      }
    ).instrument;
    const result = claimValidationV0Schema.safeParse({
      claim_id: "claim-invalid-offsets",
      instrument,
      source_url: "https://example.com/synthetic-claim",
      publisher: "Synthetic Publisher",
      published_at: "2026-08-06T00:30:00Z",
      article_content_hash: `sha256:${"d".repeat(64)}`,
      supporting_span: "Synthetic exact supporting text.",
      supporting_location: {
        kind: "TEXT_OFFSETS",
        start: 20,
        end: 19,
      },
      verifier_version: "fixture-verifier-v0",
      entailment: "SUPPORTED",
    });

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ path: ["supporting_location", "end"] }),
        ]),
      );
    }
  });

  it.each([
    {
      name: "BLOCKED with payload",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        report.status = "BLOCKED";
        report.issues = [
          { code: "BLOCKED", message: "Synthetic block for mutation test." },
        ];
      },
    },
    {
      name: "DECIDED without action",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        delete report.decision_payload.items[0].action;
      },
    },
    {
      name: "run-kind/action crossover",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        report.decision_payload.items[0].action = "HOLD";
      },
    },
    {
      name: "unsupported evidence",
      structuralSuccess: false,
      mutate: (report: MutablePublishedReport) => {
        report.decision_payload.items[0].evidence[0].entailment = "UNCLEAR";
      },
    },
    {
      name: "stale payload hash",
      structuralSuccess: true,
      mutate: (report: MutablePublishedReport) => {
        report.decision_payload.items[0].action = "AVOID";
      },
    },
  ])(
    "rejects mutation at the applicable boundary: $name",
    async ({ mutate, structuralSuccess }) => {
      const fixture = loadPublishedFixture();
      mutate(fixture);

      expect(safeParseDecisionBoardReportStructure(fixture).success).toBe(
        structuralSuccess,
      );
      await expect(parseVerifiedDecisionBoardReport(fixture)).rejects.toThrow();
      const verifiedResult =
        await safeParseVerifiedDecisionBoardReport(fixture);
      expect(verifiedResult.success).toBe(false);
      if (structuralSuccess && !verifiedResult.success) {
        expect(verifiedResult.error).toBeInstanceOf(
          DecisionBoardIntegrityError,
        );
      }
    },
  );

  it("accepts an empty published eligible universe", () => {
    const fixture = loadFixture("published-entry.json") as {
      decision_payload: { items: unknown[] };
    };
    fixture.decision_payload.items = [];

    expect(decisionBoardEnvelopeV0Schema.safeParse(fixture).success).toBe(true);
  });
});
