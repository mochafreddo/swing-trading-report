import { describe, expect, it } from "vitest";

import {
  buildTossHoldingsDiffHash,
  buildTossHoldingsDryRun,
} from "@/lib/toss/holdings-sync";
import type { HoldingRecord } from "@/lib/types";

function holding(overrides: Partial<HoldingRecord> & { ticker: string }) {
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
    created_at: overrides.created_at ?? "2026-06-19T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-06-19T00:00:00Z",
  } satisfies HoldingRecord;
}

describe("toss holdings sync dry-run", () => {
  it("normalizes safe Toss rows, preserves app metadata, and blocks unresolved rows", () => {
    const currentHoldings = [
      holding({
        ticker: "005930",
        quantity: 1,
        entry_price: 70000,
        entry_pattern: "trend_pullback_bounce",
      }),
      holding({
        ticker: "AAPL.NAS",
        quantity: 2,
        entry_price: 190,
        entry_currency: "USD",
        entry_pattern: "swing_high_breakout",
        strategy: "swing",
        notes: "core",
        tags: ["leader"],
        stop_override: 170,
      }),
    ];

    const dryRun = buildTossHoldingsDryRun({
      currentHoldings,
      items: [
        {
          symbol: "005930",
          name: "Samsung Electronics",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "1",
          averagePurchasePrice: "70000",
        },
        {
          symbol: "AAPL",
          name: "Apple",
          marketCountry: "US",
          currency: "USD",
          quantity: "3",
          averagePurchasePrice: "188.50",
        },
        {
          symbol: "MSFT",
          name: "Microsoft",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ],
    });

    expect(dryRun.applyBlocked).toBe(true);
    expect(dryRun.targetRows).toEqual([
      expect.objectContaining({
        ticker: "005930",
        quantity: 1,
        entry_price: 70000,
        entry_currency: null,
        entry_pattern: "trend_pullback_bounce",
      }),
      expect.objectContaining({
        ticker: "AAPL.NAS",
        quantity: 3,
        entry_price: 188.5,
        entry_currency: "USD",
        entry_pattern: "swing_high_breakout",
        strategy: "swing",
        notes: "core",
        tags: ["leader"],
        stop_override: 170,
      }),
    ]);
    expect(dryRun.blockedRows).toEqual([
      {
        symbol: "MSFT",
        marketCountry: "US",
        currency: "USD",
        reason: "ticker_exchange_unresolved",
        message:
          "Toss returned a US symbol without a safe existing exchange suffix mapping.",
      },
    ]);
    expect(dryRun.reconciliation.summary).toEqual(
      expect.objectContaining({
        incomingCount: 2,
        createCount: 0,
        updateCount: 1,
        deleteCount: 0,
        unchangedCount: 1,
      }),
    );
  });

  it("builds a stable diff hash that changes when normalized holdings change", () => {
    const currentHoldings = [
      holding({
        ticker: "005930",
        quantity: 1,
        entry_price: 70000,
      }),
    ];
    const first = buildTossHoldingsDryRun({
      currentHoldings,
      items: [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "1",
          averagePurchasePrice: "70000",
        },
      ],
    });
    const repeated = buildTossHoldingsDryRun({
      currentHoldings,
      items: [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "1.0",
          averagePurchasePrice: "70000.00",
        },
      ],
    });
    const changed = buildTossHoldingsDryRun({
      currentHoldings,
      items: [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "2",
          averagePurchasePrice: "70000",
        },
      ],
    });

    expect(buildTossHoldingsDiffHash(first)).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(buildTossHoldingsDiffHash(repeated)).toBe(
      buildTossHoldingsDiffHash(first),
    );
    expect(buildTossHoldingsDiffHash(changed)).not.toBe(
      buildTossHoldingsDiffHash(first),
    );
  });
});
