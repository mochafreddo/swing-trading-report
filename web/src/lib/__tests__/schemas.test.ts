import { describe, expect, it } from "vitest";

import { PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE } from "@/lib/run-dispatch-policy";
import {
  holdingAddBuySchema,
  holdingListQuerySchema,
  holdingCreateSchema,
  holdingPatchSchema,
  reportDetailQuerySchema,
  reportListQuerySchema,
  runDispatchSchema,
  tossHoldingsSyncRequestSchema,
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
      ticker: "aapl.nasdaq",
      quantity: "3",
      entry_price: "172.5",
      tags: "core, swing",
    });

    expect(parsed.ticker).toBe("AAPL.NAS");
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

    expect(parsed.ticker).toBe("BRK.B.NYS");
  });

  it("keeps US class ticker dot notation as canonical", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "brk.b.nys",
      quantity: 1,
      entry_price: 450,
    });

    expect(parsed.ticker).toBe("BRK.B.NYS");
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
      ticker: "A..NAS",
      quantity: 1,
      entry_price: 172.5,
    });

    expect(parsed.success).toBe(false);
  });

  it("rejects ambiguous .US suffix", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL.US",
      quantity: 1,
      entry_price: 172.5,
    });

    expect(parsed.success).toBe(false);
  });

  it("rejects exchange-marker-like US symbol", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL.O.NAS",
      quantity: 1,
      entry_price: 172.5,
    });

    expect(parsed.success).toBe(false);
  });

  it("rejects numeric-only US symbol", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "005930.NAS",
      quantity: 1,
      entry_price: 172.5,
    });

    expect(parsed.success).toBe(false);
  });

  it("rejects create payload when quantity is positive and entry_price is zero", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL.NAS",
      quantity: 1,
      entry_price: 0,
    });

    expect(parsed.success).toBe(false);
    if (parsed.success) {
      return;
    }
    expect(
      parsed.error.issues.some(
        (issue) =>
          issue.path.join(".") === "entry_price" &&
          issue.message === "entry_price must be > 0 when quantity > 0",
      ),
    ).toBe(true);
  });

  it("rejects create payload with invalid calendar entry_date", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL.NAS",
      quantity: 1,
      entry_price: 172.5,
      entry_date: "2026-02-31",
    });

    expect(parsed.success).toBe(false);
  });

  it("accepts active create payload with entry pattern", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "AAPL.NAS",
      quantity: 1,
      entry_price: 172.5,
      entry_pattern: " swing_high_breakout ",
    });

    expect(parsed.entry_pattern).toBe("swing_high_breakout");
  });

  it("rejects unknown create entry pattern values", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL.NAS",
      quantity: 1,
      entry_price: 172.5,
      entry_pattern: "not_a_breakout",
    });

    expect(parsed.success).toBe(false);
  });

  it("rejects inactive create payload with non-null entry pattern", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL.NAS",
      quantity: 0,
      entry_price: 0,
      entry_pattern: "swing_high_breakout",
    });

    expect(parsed.success).toBe(false);
  });

  it("accepts inactive create payload with explicit null entry pattern", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "AAPL.NAS",
      quantity: 0,
      entry_price: 0,
      entry_pattern: null,
    });

    expect(parsed.entry_pattern).toBeNull();
  });

  it("requires at least one patch field", () => {
    const parsed = holdingPatchSchema.safeParse({});
    expect(parsed.success).toBe(false);
  });

  it("accepts active patch payload with entry pattern", () => {
    const parsed = holdingPatchSchema.parse({
      quantity: 1,
      entry_pattern: " swing_high_breakout ",
    });

    expect(parsed.entry_pattern).toBe("swing_high_breakout");
  });

  it("rejects marker-only non-null entry pattern patch", () => {
    const parsed = holdingPatchSchema.safeParse({
      entry_pattern: "swing_high_breakout",
    });

    expect(parsed.success).toBe(false);
  });

  it("accepts explicit entry pattern clear without quantity", () => {
    const parsed = holdingPatchSchema.parse({
      entry_pattern: null,
    });

    expect(parsed.entry_pattern).toBeNull();
  });

  it("rejects inactive patch payload with non-null entry pattern", () => {
    const parsed = holdingPatchSchema.safeParse({
      quantity: 0,
      entry_pattern: "swing_high_breakout",
    });

    expect(parsed.success).toBe(false);
  });

  it("accepts ticker-only patch payload and normalizes ticker", () => {
    const parsed = holdingPatchSchema.parse({
      ticker: "msft.nasd",
    });

    expect(parsed).toEqual({ ticker: "MSFT.NAS" });
  });

  it("normalizes class ticker slash notation in patch payload", () => {
    const parsed = holdingPatchSchema.parse({
      ticker: "brk/b.nys",
    });

    expect(parsed).toEqual({ ticker: "BRK.B.NYS" });
  });

  it("rejects patch payload when quantity is positive and entry_price is zero", () => {
    const parsed = holdingPatchSchema.safeParse({
      quantity: 1,
      entry_price: 0,
    });

    expect(parsed.success).toBe(false);
    if (parsed.success) {
      return;
    }
    expect(
      parsed.error.issues.some(
        (issue) =>
          issue.path.join(".") === "entry_price" &&
          issue.message === "entry_price must be > 0 when quantity > 0",
      ),
    ).toBe(true);
  });

  it("normalizes add-buy payload", () => {
    const parsed = holdingAddBuySchema.parse({
      buy_quantity: "2.5",
      buy_price: "182.45",
      buy_date: "2026-03-03",
    });

    expect(parsed).toEqual({
      buy_quantity: 2.5,
      buy_price: 182.45,
      buy_date: "2026-03-03",
    });
  });

  it("rejects non-positive add-buy quantity or price", () => {
    expect(
      holdingAddBuySchema.safeParse({
        buy_quantity: 0,
        buy_price: 10,
      }).success,
    ).toBe(false);
    expect(
      holdingAddBuySchema.safeParse({
        buy_quantity: 1,
        buy_price: -1,
      }).success,
    ).toBe(false);
  });

  it("accepts add-buy payload without buy_date", () => {
    const parsed = holdingAddBuySchema.parse({
      buy_quantity: 1,
      buy_price: 100,
    });

    expect(parsed).toEqual({
      buy_quantity: 1,
      buy_price: 100,
    });
  });

  it("rejects add-buy payload with invalid calendar buy_date", () => {
    const parsed = holdingAddBuySchema.safeParse({
      buy_quantity: 1,
      buy_price: 100,
      buy_date: "2026-02-31",
    });

    expect(parsed.success).toBe(false);
  });
});

describe("tossHoldingsSyncRequestSchema", () => {
  it("accepts apply payload with a reviewed diff hash and confirmation text", () => {
    const parsed = tossHoldingsSyncRequestSchema.parse({
      mode: "apply",
      diffHash:
        "sha256:4444444444444444444444444444444444444444444444444444444444444444",
      confirmationText: "APPLY TOSS HOLDINGS",
    });

    expect(parsed).toEqual({
      mode: "apply",
      diffHash:
        "sha256:4444444444444444444444444444444444444444444444444444444444444444",
      confirmationText: "APPLY TOSS HOLDINGS",
    });
  });

  it("rejects apply payload without confirmation text", () => {
    const parsed = tossHoldingsSyncRequestSchema.safeParse({
      mode: "apply",
      diffHash:
        "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    });

    expect(parsed.success).toBe(false);
  });
});

describe("report query schemas", () => {
  it("normalizes report list refresh flag from query string", () => {
    const parsed = reportListQuerySchema.parse({
      type: "buy",
      q: "aapl",
      limit: "20",
      refresh: "1",
    });

    expect(parsed.refresh).toBe(true);
  });

  it("defaults refresh=false when omitted", () => {
    const parsed = reportListQuerySchema.parse({
      type: "all",
      q: "",
      limit: "30",
    });

    expect(parsed.refresh).toBe(false);
  });

  it("normalizes report detail refresh flag from query string", () => {
    const parsed = reportDetailQuerySchema.parse({
      key: "2026/02/2026-02-14.buy.json",
      refresh: "true",
    });

    expect(parsed.refresh).toBe(true);
  });
});
