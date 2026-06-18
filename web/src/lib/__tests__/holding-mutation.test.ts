import { describe, expect, it } from "vitest";

import { normalizeHoldingMutationForPersistence } from "@/lib/holding-mutation";

describe("normalizeHoldingMutationForPersistence", () => {
  it("forces entry pattern clear when quantity is zero", () => {
    expect(
      normalizeHoldingMutationForPersistence({
        quantity: 0,
        notes: "closed",
      }),
    ).toEqual({
      quantity: 0,
      notes: "closed",
      entry_pattern: null,
    });
  });

  it("rejects marker-only non-null entry pattern patch", () => {
    expect(() =>
      normalizeHoldingMutationForPersistence({
        entry_pattern: "swing_high_breakout",
      }),
    ).toThrow(/quantity > 0/);
  });

  it("allows explicit clear without quantity", () => {
    expect(
      normalizeHoldingMutationForPersistence({
        entry_pattern: null,
      }),
    ).toEqual({
      entry_pattern: null,
    });
  });

  it("allows non-null entry pattern only with positive owned quantity", () => {
    expect(
      normalizeHoldingMutationForPersistence({
        quantity: 1,
        entry_pattern: "swing_high_breakout",
      }),
    ).toEqual({
      quantity: 1,
      entry_pattern: "swing_high_breakout",
    });
  });

  it("treats owned undefined entry pattern as omitted", () => {
    expect(
      normalizeHoldingMutationForPersistence({
        ticker: "AAPL.NAS",
        quantity: 1,
        entry_pattern: undefined,
      }),
    ).toEqual({
      ticker: "AAPL.NAS",
      quantity: 1,
    });
  });
});
