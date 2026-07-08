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
    broker_state: overrides.broker_state ?? "confirmed",
    broker_missing_first_seen_date:
      overrides.broker_missing_first_seen_date ?? null,
    broker_missing_last_seen_date:
      overrides.broker_missing_last_seen_date ?? null,
    broker_missing_count: overrides.broker_missing_count ?? 0,
    broker_missing_diff_hash: overrides.broker_missing_diff_hash ?? null,
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

  it("treats broker quarantine evidence as a restorable update", () => {
    const current = [
      record({
        ticker: "TSLA.NAS",
        quantity: 1,
        entry_price: 250,
        entry_currency: "USD",
        broker_state: "not_seen_in_toss",
        broker_missing_first_seen_date: "2026-07-07",
        broker_missing_last_seen_date: "2026-07-07",
        broker_missing_count: 1,
        broker_missing_diff_hash: "sha256:missing",
      }),
    ];
    const target = [
      snapshot({
        ticker: "TSLA.NAS",
        quantity: 1,
        entry_price: 250,
        entry_currency: "USD",
      }),
    ];

    const result = buildHoldingsReconciliation(current, target);

    expect(result.summary.updateCount).toBe(1);
    expect(result.summary.unchangedCount).toBe(0);
    expect(result.changes.update).toEqual([
      expect.objectContaining({
        ticker: "TSLA.NAS",
        changedFields: [
          "broker_state",
          "broker_missing_first_seen_date",
          "broker_missing_last_seen_date",
          "broker_missing_count",
          "broker_missing_diff_hash",
        ],
      }),
    ]);
  });
});
