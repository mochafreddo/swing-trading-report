import { describe, expect, it } from "vitest";

import {
  isActiveHoldingQuantity,
  partitionHoldingsByActivity,
} from "@/lib/holding-activity";
import type { HoldingRecord } from "@/lib/types";

function makeHolding(ticker: string, quantity: number): HoldingRecord {
  return {
    ticker,
    quantity,
    entry_price: 100,
    entry_currency: "USD",
    entry_date: "2026-02-14",
    strategy: null,
    notes: null,
    tags: [],
    stop_override: null,
    target_override: null,
    created_at: "2026-02-14T00:00:00.000Z",
    updated_at: "2026-02-14T00:00:00.000Z",
  };
}

describe("isActiveHoldingQuantity", () => {
  it("returns true only for finite positive numbers", () => {
    expect(isActiveHoldingQuantity(1)).toBe(true);
    expect(isActiveHoldingQuantity(0)).toBe(false);
    expect(isActiveHoldingQuantity(-1)).toBe(false);
    expect(isActiveHoldingQuantity(Number.NaN)).toBe(false);
    expect(isActiveHoldingQuantity(Number.POSITIVE_INFINITY)).toBe(false);
  });
});

describe("partitionHoldingsByActivity", () => {
  it("partitions holdings while preserving original order", () => {
    const items = [
      makeHolding("AAPL.US", 2),
      makeHolding("005930", 0),
      makeHolding("MSFT.US", 1),
      makeHolding("TSLA.US", -3),
    ];

    const result = partitionHoldingsByActivity(items);

    expect(result.active.map((item) => item.ticker)).toEqual([
      "AAPL.US",
      "MSFT.US",
    ]);
    expect(result.inactive.map((item) => item.ticker)).toEqual([
      "005930",
      "TSLA.US",
    ]);
    expect(result.activeCount).toBe(2);
    expect(result.inactiveCount).toBe(2);
    expect(result.totalCount).toBe(4);
  });

  it("treats NaN and Infinity as inactive", () => {
    const items = [
      makeHolding("NVDA.US", Number.NaN),
      makeHolding("AMZN.US", Number.POSITIVE_INFINITY),
    ];

    const result = partitionHoldingsByActivity(items);

    expect(result.activeCount).toBe(0);
    expect(result.inactiveCount).toBe(2);
  });
});
