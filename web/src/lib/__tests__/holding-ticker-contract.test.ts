import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  normalizeHoldingTickerForMutation,
  US_TICKER_PATTERN,
} from "@/lib/holding-ticker";
import { holdingCreateSchema } from "@/lib/schemas";

type HoldingTickerCase = {
  input: string;
  valid: boolean;
  canonical?: string;
};

const fixturePath = path.resolve(
  process.cwd(),
  "../tests/contracts/holding_ticker_cases.json",
);
const contractCases = JSON.parse(
  fs.readFileSync(fixturePath, "utf8"),
) as HoldingTickerCase[];

describe("holding ticker contract fixture", () => {
  for (const testCase of contractCases) {
    it(`matches shared contract for ${testCase.input}`, () => {
      const parsed = holdingCreateSchema.safeParse({
        ticker: testCase.input,
        quantity: 1,
        entry_price: 100,
      });

      expect(parsed.success).toBe(testCase.valid);

      if (!testCase.valid) {
        return;
      }

      expect(normalizeHoldingTickerForMutation(testCase.input)).toBe(
        testCase.canonical,
      );

      const normalizedInput = testCase.input.trim().toUpperCase();
      if (testCase.canonical?.includes(".")) {
        expect(US_TICKER_PATTERN.test(normalizedInput)).toBe(true);
      } else {
        expect(US_TICKER_PATTERN.test(normalizedInput)).toBe(false);
      }
    });
  }
});
