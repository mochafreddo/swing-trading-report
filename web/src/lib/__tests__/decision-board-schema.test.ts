import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  DecisionBoardIntegrityError,
  DecisionBoardJsonValueError,
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
  metadata?: unknown;
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

const validClaim = () => {
  const fixture = loadPublishedFixture();
  const instrument = (
    fixture.decision_payload.items[0] as unknown as {
      instrument: Record<string, unknown>;
    }
  ).instrument;
  return {
    claim_id: "claim-synthetic",
    instrument,
    source_url: "https://example.com/synthetic-claim",
    publisher: "Synthetic Publisher",
    published_at: "2026-08-06T00:30:00Z",
    article_content_hash: `sha256:${"d".repeat(64)}`,
    supporting_span: "Synthetic exact supporting text.",
    supporting_location: {
      kind: "TEXT_OFFSETS",
      start: 20,
      end: 20,
    },
    verifier_version: "fixture-verifier-v0",
    entailment: "SUPPORTED",
  };
};

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

  it.each([
    undefined,
    "",
    `sha256:${"A".repeat(64)}`,
    `sha256:${"a".repeat(63)}`,
    123,
  ])("rejects noncanonical envelope idempotency key %j", (idempotencyKey) => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;
    if (idempotencyKey === undefined) {
      delete fixture.idempotency_key;
    } else {
      fixture.idempotency_key = idempotencyKey;
    }

    expect(safeParseDecisionBoardReportStructure(fixture).success).toBe(false);
  });

  it("rejects cycles with typed path errors in canonical and verified boundaries", async () => {
    const cycle: Record<string, unknown> = {};
    cycle.self = cycle;
    const fixture = loadPublishedFixture();
    fixture.metadata = cycle;

    expect(() => canonicalDecisionPayloadBytesV0(cycle as never)).toThrowError(
      DecisionBoardJsonValueError,
    );
    expect(() => canonicalDecisionPayloadBytesV0(cycle as never)).toThrow(
      /\$\.self.*cycle/,
    );
    await expect(parseVerifiedDecisionBoardReport(fixture)).rejects.toThrow(
      DecisionBoardJsonValueError,
    );
    const result = await safeParseVerifiedDecisionBoardReport(fixture);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error).toBeInstanceOf(DecisionBoardJsonValueError);
    }
  });

  it.each([
    {
      name: "string value",
      invalid: { text: "\ud800" },
    },
    {
      name: "object key",
      invalid: { ["\udfff"]: "text" },
    },
  ])("rejects unpaired surrogate in $name", async ({ invalid }) => {
    const fixture = loadPublishedFixture();
    fixture.metadata = invalid;

    expect(() =>
      canonicalDecisionPayloadBytesV0(invalid as never),
    ).toThrowError(DecisionBoardJsonValueError);
    await expect(parseVerifiedDecisionBoardReport(fixture)).rejects.toThrow(
      DecisionBoardJsonValueError,
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

  it("rejects malformed hashes", () => {
    const fixture = loadFixture("published-entry.json") as Record<
      string,
      unknown
    >;

    const malformed = structuredClone(fixture) as {
      decision_payload_hash: string;
    };
    malformed.decision_payload_hash = `sha256:${"A".repeat(64)}`;
    expect(decisionBoardEnvelopeV0Schema.safeParse(malformed).success).toBe(
      false,
    );
  });

  it.each([
    { name: "naive", timestamp: "2026-08-06T01:00:05" },
    { name: "impossible date", timestamp: "2026-02-30T01:00:05Z" },
  ])("rejects $name timestamp mutation", ({ timestamp }) => {
    const fixture = loadPublishedFixture();

    expect(
      decisionBoardEnvelopeV0Schema.safeParse({
        ...fixture,
        created_at: timestamp,
      }).success,
    ).toBe(false);
  });

  it("rejects evidence locations whose end precedes start", () => {
    const claim = validClaim();
    claim.supporting_location.end = 19;
    const result = claimValidationV0Schema.safeParse(claim);

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
    { name: "non-HTTP scheme", sourceUrl: "mailto:research@example.com" },
    { name: "space in host", sourceUrl: "https://bad host.example/path" },
  ])("rejects source URL mutation: $name", ({ sourceUrl }) => {
    const claim = validClaim();
    claim.source_url = sourceUrl;

    expect(claimValidationV0Schema.safeParse(claim).success).toBe(false);
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
