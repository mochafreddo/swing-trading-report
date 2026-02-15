import { describe, expect, it } from "vitest";

import {
  buildHoldingsKeysetFilter,
  decodeHoldingCursor,
  encodeHoldingCursor,
  HoldingCursorError,
} from "@/lib/holdings-pagination";

describe("holdings-pagination", () => {
  it("encodes and decodes cursor payload", () => {
    const cursor = {
      updated_at: "2026-02-15T09:30:00.000Z",
      ticker: "AAPL.US",
    };

    const encoded = encodeHoldingCursor(cursor);
    expect(decodeHoldingCursor(encoded)).toEqual(cursor);
  });

  it("throws for malformed cursor encoding", () => {
    expect(() => decodeHoldingCursor("not-base64url")).toThrow(
      HoldingCursorError,
    );
  });

  it("throws for invalid cursor payload", () => {
    const malformed = Buffer.from(
      JSON.stringify({ updated_at: "2026-02-15T09:30:00.000Z" }),
      "utf-8",
    ).toString("base64url");

    expect(() => decodeHoldingCursor(malformed)).toThrow(HoldingCursorError);
  });

  it("builds keyset filter expression", () => {
    expect(
      buildHoldingsKeysetFilter({
        updated_at: "2026-02-15T09:30:00.000Z",
        ticker: "AAPL.US",
      }),
    ).toBe(
      '(updated_at.lt."2026-02-15T09:30:00.000Z",and(updated_at.eq."2026-02-15T09:30:00.000Z",ticker.gt."AAPL.US"))',
    );
  });
});
