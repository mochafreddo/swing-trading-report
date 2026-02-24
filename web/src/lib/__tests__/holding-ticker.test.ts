import { describe, expect, it } from "vitest";

import {
  buildHoldingTickerAliases,
  normalizeHoldingTickerForMutation,
  US_TICKER_PATTERN,
} from "@/lib/holding-ticker";

describe("holding ticker helpers", () => {
  it("keeps KR ticker unchanged", () => {
    expect(normalizeHoldingTickerForMutation("005930")).toBe("005930");
  });

  it("normalizes dot notation class ticker to slash", () => {
    expect(normalizeHoldingTickerForMutation("brk.b.nys")).toBe("BRK/B.NYS");
  });

  it("keeps slash notation class ticker unchanged", () => {
    expect(normalizeHoldingTickerForMutation("brk/b.nys")).toBe("BRK/B.NYS");
  });

  it("returns canonical and dotted aliases for class ticker", () => {
    expect(buildHoldingTickerAliases("BRK/B.NYS")).toEqual([
      "BRK/B.NYS",
      "BRK.B.NYS",
    ]);
    expect(buildHoldingTickerAliases("BRK.B.NYS")).toEqual([
      "BRK/B.NYS",
      "BRK.B.NYS",
    ]);
  });

  it("returns single alias for plain ticker", () => {
    expect(buildHoldingTickerAliases("AAPL.US")).toEqual(["AAPL.US"]);
  });

  it("does not normalize multi-dot base ticker", () => {
    expect(normalizeHoldingTickerForMutation("abc.def.ghi.us")).toBe(
      "ABC.DEF.GHI.US",
    );
  });

  it("rejects ticker with empty base segment in pattern", () => {
    expect(US_TICKER_PATTERN.test("A..US")).toBe(false);
    expect(US_TICKER_PATTERN.test("ABC..US")).toBe(false);
  });
});
