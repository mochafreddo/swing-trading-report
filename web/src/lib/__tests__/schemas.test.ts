import { describe, expect, it } from "vitest";

import {
  holdingCreateSchema,
  holdingPatchSchema,
  runDispatchSchema
} from "@/lib/schemas";

describe("runDispatchSchema", () => {
  it("accepts scan payload with whitelisted fields", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "scan",
      provider: "kis",
      universe: "both",
      ref: "main"
    });

    expect(parsed.success).toBe(true);
  });

  it("rejects unknown keys", () => {
    const parsed = runDispatchSchema.safeParse({
      workflow: "sell",
      provider: "kis",
      hack: "x"
    });

    expect(parsed.success).toBe(false);
  });
});

describe("holding schemas", () => {
  it("normalizes create payload", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "aapl.us",
      quantity: "3",
      entry_price: "172.5",
      tags: "core, swing"
    });

    expect(parsed.ticker).toBe("AAPL.US");
    expect(parsed.quantity).toBe(3);
    expect(parsed.tags).toEqual(["core", "swing"]);
  });

  it("accepts KR ticker format", () => {
    const parsed = holdingCreateSchema.parse({
      ticker: "005930",
      quantity: 1,
      entry_price: 70000
    });

    expect(parsed.ticker).toBe("005930");
  });

  it("rejects unsupported ticker format", () => {
    const parsed = holdingCreateSchema.safeParse({
      ticker: "AAPL",
      quantity: 1,
      entry_price: 172.5
    });

    expect(parsed.success).toBe(false);
  });

  it("requires at least one patch field", () => {
    const parsed = holdingPatchSchema.safeParse({});
    expect(parsed.success).toBe(false);
  });
});
