import { describe, expect, it } from "vitest";

import { PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE } from "@/lib/run-dispatch-policy";
import {
  holdingListQuerySchema,
  holdingCreateSchema,
  holdingPatchSchema,
  runDispatchSchema,
} from "@/lib/schemas";

describe("runDispatchSchema", () => {
  it("accepts scan payload with kis provider and both universe", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "scan",
      provider: "kis",
      universe: "both",
    });

    expect(parsed.success).toBe(true);
  });

  it("accepts scan payload with pykrx provider and KR universe", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "scan",
      provider: "pykrx",
      universe: "KR",
    });

    expect(parsed.success).toBe(true);
  });

  it("rejects pykrx provider with US universe for scan", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "scan",
      provider: "pykrx",
      universe: "US",
    });

    expect(parsed.success).toBe(false);
    if (parsed.success) {
      return;
    }
    expect(
      parsed.error.issues.some(
        (issue) =>
          issue.path.join(".") === "universe" &&
          issue.message === PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
      ),
    ).toBe(true);
  });

  it("rejects pykrx provider with both universe for scan", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "scan",
      provider: "pykrx",
      universe: "both",
    });

    expect(parsed.success).toBe(false);
    if (parsed.success) {
      return;
    }
    expect(
      parsed.error.issues.some(
        (issue) =>
          issue.path.join(".") === "universe" &&
          issue.message === PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
      ),
    ).toBe(true);
  });

  it("rejects unknown keys", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "sell",
      provider: "kis",
      hack: "x",
    });

    expect(parsed.success).toBe(false);
  });
});

describe("holding schemas", () => {
  it("uses holding list defaults", () => {
    const parsed = holdingListQuerySchema.parse({});
    expect(parsed.limit).toBe(100);
    expect(parsed.cursor).toBeUndefined();
  });

  it("accepts explicit list query values", () => {
    const parsed = holdingListQuerySchema.parse({
      limit: "200",
      cursor: "abc",
    });

    expect(parsed.limit).toBe(200);
    expect(parsed.cursor).toBe("abc");
  });

  it("rejects invalid list query limits", () => {
    expect(holdingListQuerySchema.safeParse({ limit: 0 }).success).toBe(false);
    expect(holdingListQuerySchema.safeParse({ limit: 201 }).success).toBe(
      false,
    );
  });

  it("normalizes create payload", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "aapl.us",
      quantity: "3",
      entry_price: "172.5",
      tags: "core, swing",
    });

    expect(parsed.ticker).toBe("AAPL.US");
    expect(parsed.quantity).toBe(3);
    expect(parsed.tags).toEqual(["core", "swing"]);
  });

  it("accepts KR ticker format", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "005930",
      quantity: 1,
      entry_price: 70000,
    });

    expect(parsed.ticker).toBe("005930");
  });

  it("accepts US ticker format with slash", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "brk/b.nys",
      quantity: 1,
      entry_price: 450,
    });

    expect(parsed.ticker).toBe("BRK/B.NYS");
  });

  it("normalizes US class ticker dot notation to slash", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "brk.b.nys",
      quantity: 1,
      entry_price: 450,
    });

    expect(parsed.ticker).toBe("BRK/B.NYS");
  });

  it("rejects unsupported ticker format", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL",
      quantity: 1,
      entry_price: 172.5,
    });

    expect(parsed.success).toBe(false);
  });

  it("rejects ticker with empty base segment", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "A..US",
      quantity: 1,
      entry_price: 172.5,
    });

    expect(parsed.success).toBe(false);
  });

  it("requires at least one patch field", () => {
    const parsed = holdingPatchSchema.safeParse({});
    expect(parsed.success).toBe(false);
  });

  it("accepts ticker-only patch payload and normalizes ticker", () => {
    const parsed = holdingPatchSchema.parse({
      ticker: "msft.us",
    });

    expect(parsed).toEqual({ ticker: "MSFT.US" });
  });

  it("normalizes class ticker dot notation in patch payload", () => {
    const parsed = holdingPatchSchema.parse({
      ticker: "brk.b.nys",
    });

    expect(parsed).toEqual({ ticker: "BRK/B.NYS" });
  });
});
