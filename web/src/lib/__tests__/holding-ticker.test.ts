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

  it("keeps dot notation class ticker as canonical", () => {
    expect(normalizeHoldingTickerForMutation("brk.b.nys")).toBe("BRK.B.NYS");
  });

  it("normalizes slash notation class ticker to dot", () => {
    expect(normalizeHoldingTickerForMutation("brk/b.nys")).toBe("BRK.B.NYS");
  });

  it("returns canonical and slash aliases for class ticker", () => {
    expect(buildHoldingTickerAliases("BRK.B.NYS")).toEqual([
      "BRK.B.NYS",
      "BRK/B.NYS",
    ]);
    expect(buildHoldingTickerAliases("BRK/B.NYS")).toEqual([
      "BRK.B.NYS",
      "BRK/B.NYS",
    ]);
  });

  it("returns single alias for plain ticker", () => {
    expect(buildHoldingTickerAliases("AAPL.NAS")).toEqual(["AAPL.NAS"]);
  });

  it("normalizes US suffix synonym to canonical exchange", () => {
    expect(normalizeHoldingTickerForMutation("aapl.nasdaq")).toBe("AAPL.NAS");
  });

  it("does not normalize multi-dot base ticker", () => {
    expect(normalizeHoldingTickerForMutation("abc.def.ghi.nas")).toBe(
      "ABC.DEF.GHI.NAS",
    );
  });

  it("does not normalize exchange-marker-like symbol", () => {
    expect(normalizeHoldingTickerForMutation("aapl.o.nas")).toBe("AAPL.O.NAS");
  });

  it("rejects ambiguous .US suffix in pattern", () => {
    expect(US_TICKER_PATTERN.test("AAPL.US")).toBe(false);
  });

  it("rejects ticker with empty base segment in pattern", () => {
    expect(US_TICKER_PATTERN.test("A..NAS")).toBe(false);
    expect(US_TICKER_PATTERN.test("ABC..NAS")).toBe(false);
  });

  it("rejects invalid US class notation in pattern", () => {
    expect(US_TICKER_PATTERN.test("AAPL.O.NAS")).toBe(false);
    expect(US_TICKER_PATTERN.test("AAPL/O.NAS")).toBe(false);
  });

  it("rejects numeric-only US symbol in pattern", () => {
    expect(US_TICKER_PATTERN.test("005930.NAS")).toBe(false);
  });
});
