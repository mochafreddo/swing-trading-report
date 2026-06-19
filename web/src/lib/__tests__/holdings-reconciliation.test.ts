import { describe, expect, it } from "vitest";

import { buildHoldingsReconciliation } from "@/lib/holdings-reconciliation";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingSnapshot,
} from "@/lib/types";

function snapshot(
  overrides: Partial<HoldingSnapshot> & Pick<HoldingSnapshot, "ticker">,
): HoldingSnapshot {
  return {
    ticker: overrides.ticker,
    quantity: overrides.quantity ?? 1,
    entry_price: overrides.entry_price ?? 100,
    entry_currency: overrides.entry_currency ?? null,
    entry_date: overrides.entry_date ?? null,
    strategy: overrides.strategy ?? null,
    entry_pattern: overrides.entry_pattern ?? null,
    notes: overrides.notes ?? null,
    tags: overrides.tags ?? [],
    stop_override: overrides.stop_override ?? null,
    target_override: overrides.target_override ?? null,
  };
}

function record(
  overrides: Partial<HoldingRecord> & Pick<HoldingRecord, "ticker">,
): HoldingRecord {
  return {
    ...snapshot(overrides),
    created_at: overrides.created_at ?? "2026-06-19T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-06-19T00:00:00Z",
  };
}

describe("holdings reconciliation", () => {
  it("builds summary counts and grouped row-level changes", () => {
    const current = [
      record({ ticker: "005930", quantity: 1, entry_price: 70000 }),
      record({
        ticker: "AAPL.NAS",
        quantity: 2,
        entry_price: 190,
        entry_currency: "USD",
        entry_pattern: "swing_high_breakout",
      }),
      record({
        ticker: "MSFT.NAS",
        quantity: 1,
        entry_price: 300,
        entry_currency: "USD",
      }),
    ];
    const target: HoldingReplaceSnapshot[] = [
      snapshot({ ticker: "005930", quantity: 1, entry_price: 70000 }),
      {
        ...snapshot({
          ticker: "AAPL.NAS",
          quantity: 3,
          entry_price: 188,
          entry_currency: "USD",
        }),
        entry_pattern: "swing_high_breakout",
      },
      snapshot({
        ticker: "TSLA.NAS",
        quantity: 1,
        entry_price: 250,
        entry_currency: "USD",
      }),
    ];

    const result = buildHoldingsReconciliation(current, target);

    expect(result.summary).toEqual({
      incomingCount: 3,
      createCount: 1,
      updateCount: 1,
      deleteCount: 1,
      unchangedCount: 1,
      createTickers: ["TSLA.NAS"],
      updateTickers: ["AAPL.NAS"],
      deleteTickers: ["MSFT.NAS"],
    });
    expect(result.changes.create).toEqual([
      expect.objectContaining({ ticker: "TSLA.NAS", after: target[2] }),
    ]);
    expect(result.changes.update).toEqual([
      expect.objectContaining({
        ticker: "AAPL.NAS",
        before: snapshot({
          ticker: "AAPL.NAS",
          quantity: 2,
          entry_price: 190,
          entry_currency: "USD",
          entry_pattern: "swing_high_breakout",
        }),
        after: target[1],
        changedFields: ["quantity", "entry_price"],
      }),
    ]);
    expect(result.changes.delete).toEqual([
      expect.objectContaining({
        ticker: "MSFT.NAS",
        before: snapshot({
          ticker: "MSFT.NAS",
          quantity: 1,
          entry_price: 300,
          entry_currency: "USD",
        }),
      }),
    ]);
    expect(result.changes.unchanged).toEqual([
      expect.objectContaining({ ticker: "005930" }),
    ]);
  });
});
