import { describe, expect, it } from "vitest";

import { getAddBuyPrecheckError } from "@/components/holdings/add-buy-precheck";
import type { HoldingRecord } from "@/lib/types";

function makeHolding(overrides: Partial<HoldingRecord> = {}): HoldingRecord {
  return {
    ticker: "AAPL.NAS",
    quantity: 1,
    entry_price: 100,
    entry_currency: "USD",
    entry_date: "2026-03-03",
    strategy: null,
    notes: null,
    tags: [],
    stop_override: null,
    target_override: null,
    created_at: "2026-03-03T00:00:00Z",
    updated_at: "2026-03-03T00:00:00Z",
    ...overrides,
    entry_pattern: overrides.entry_pattern ?? null,
  };
}

describe("getAddBuyPrecheckError", () => {
  it("returns null when target is absent", () => {
    expect(getAddBuyPrecheckError(null)).toBeNull();
  });

  it("returns error when quantity is positive and entry price is non-positive", () => {
    expect(
      getAddBuyPrecheckError(
        makeHolding({
          quantity: 1,
          entry_price: 0,
        }),
      ),
    ).toContain("entry_price");
  });

  it("returns error when entry currency mismatches ticker market", () => {
    expect(
      getAddBuyPrecheckError(
        makeHolding({
          ticker: "AAPL.NAS",
          entry_currency: "KRW",
        }),
      ),
    ).toContain("entry_currency");
  });

  it("returns error when ticker format is unsupported for add-buy", () => {
    expect(
      getAddBuyPrecheckError(
        makeHolding({
          ticker: "AAPL.US",
        }),
      ),
    ).toContain("ticker");
  });

  it("allows missing entry currency for auto-fill", () => {
    expect(
      getAddBuyPrecheckError(
        makeHolding({
          ticker: "005930",
          entry_currency: null,
        }),
      ),
    ).toBeNull();
  });
});
