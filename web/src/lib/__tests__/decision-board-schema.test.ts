import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  decisionBoardEnvelopeV0Schema,
  parseDecisionBoardReport,
  safeParseDecisionBoardReport,
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

describe("Decision Board V0 schema", () => {
  it.each(["published-entry.json", "published-holding.json", "blocked.json"])(
    "parses shared golden fixture %s",
    (name) => {
      const fixture = loadFixture(name);

      expect(parseDecisionBoardReport(fixture)).toEqual(fixture);
      expect(safeParseDecisionBoardReport(fixture).success).toBe(true);
    },
  );

  it("rejects the shared conditional-invariant fixture", () => {
    const result = safeParseDecisionBoardReport(
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

  it("accepts an empty published eligible universe", () => {
    const fixture = loadFixture("published-entry.json") as {
      decision_payload: { items: unknown[] };
    };
    fixture.decision_payload.items = [];

    expect(decisionBoardEnvelopeV0Schema.safeParse(fixture).success).toBe(true);
  });
});
