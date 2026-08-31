import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  parseUnclassifiedQueuePreviewInput,
  portfolioMandateA2PrivateInputSchema,
  unclassifiedQueuePreviewInputSchema,
} from "@/lib/portfolio-mandate-a2-private-input-schema";

const fixturePath = fileURLToPath(
  new URL(
    "../../../../tests/fixtures/portfolio_mandate/portfolio-mandate-a2-unclassified-preview.synthetic.json",
    import.meta.url,
  ),
);

const fixture = (): Record<string, unknown> =>
  JSON.parse(readFileSync(fixturePath, "utf8")) as Record<string, unknown>;

const clone = <T>(value: T): T => structuredClone(value);

describe("Portfolio Mandate A2 private input Web contract", () => {
  it("accepts the strict five-row synthetic unclassified preview", () => {
    const parsed = parseUnclassifiedQueuePreviewInput(fixture());

    expect(parsed.state).toBe("USER_INPUT_RECORDED_UNCLASSIFIED");
    expect(parsed.snapshot.holding_count).toBe(12);
    expect(parsed.holdings).toHaveLength(5);
    expect(
      parsed.holdings.every(
        (holding) => holding.classification_state === "UNCLASSIFIED",
      ),
    ).toBe(true);
  });

  it("matches the base state enum but fail-closes the queue preview on a wrong state", () => {
    const input = fixture();
    input.state = "AWAITING_USER_INPUT";

    expect(portfolioMandateA2PrivateInputSchema.safeParse(input).success).toBe(
      true,
    );
    expect(unclassifiedQueuePreviewInputSchema.safeParse(input).success).toBe(
      false,
    );
  });

  it.each([
    [
      "root private field",
      (input: Record<string, unknown>) => {
        input.account_id = "synthetic-private-field";
      },
    ],
    [
      "holding private field",
      (input: Record<string, unknown>) => {
        const holdings = input.holdings as Array<Record<string, unknown>>;
        holdings[0].market_value = "123.45";
      },
    ],
    [
      "account identifier marker",
      (input: Record<string, unknown>) => {
        const snapshot = input.snapshot as Record<string, unknown>;
        snapshot.account_identifier_included = true;
      },
    ],
    [
      "amount marker",
      (input: Record<string, unknown>) => {
        const snapshot = input.snapshot as Record<string, unknown>;
        snapshot.amounts_included = true;
      },
    ],
    [
      "ticker",
      (input: Record<string, unknown>) => {
        const holdings = input.holdings as Array<Record<string, unknown>>;
        holdings[0].ticker = "lowercase.nas";
      },
    ],
    [
      "thesis recall contradiction",
      (input: Record<string, unknown>) => {
        const holdings = input.holdings as Array<Record<string, unknown>>;
        holdings[0].thesis_recall = "NOT_REMEMBERED";
      },
    ],
    [
      "invalidation recall contradiction",
      (input: Record<string, unknown>) => {
        const holdings = input.holdings as Array<Record<string, unknown>>;
        holdings[1].invalidation_recall = "REMEMBERED";
      },
    ],
  ])("rejects %s without returning a partial contract", (_label, mutate) => {
    const input = clone(fixture());
    mutate(input);

    expect(unclassifiedQueuePreviewInputSchema.safeParse(input).success).toBe(
      false,
    );
  });
});
