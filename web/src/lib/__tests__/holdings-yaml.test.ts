import { describe, expect, it } from "vitest";

import {
  buildHoldingsYamlDocument,
  buildHoldingsYamlImportSummary,
  HoldingsYamlError,
  parseHoldingsYamlDocument,
} from "@/lib/holdings-yaml";
import type { HoldingRecord, HoldingSnapshot } from "@/lib/types";

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
    created_at: overrides.created_at ?? "2026-03-28T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-03-28T00:00:00Z",
  };
}

describe("holdings-yaml", () => {
  it("builds a round-trippable export document", () => {
    const document = buildHoldingsYamlDocument([
      snapshot({
        ticker: "TSLA.NAS",
        quantity: 3,
        entry_price: 250.5,
        entry_currency: "USD",
        tags: ["leader"],
      }),
      snapshot({
        ticker: "005930",
        quantity: 2,
        entry_price: 70000,
      }),
    ]);

    expect(document).toContain("version: 1");
    expect(document).toMatch(/ticker:\s*["']005930["']/);

    expect(parseHoldingsYamlDocument(document)).toEqual([
      snapshot({
        ticker: "005930",
        quantity: 2,
        entry_price: 70000,
      }),
      snapshot({
        ticker: "TSLA.NAS",
        quantity: 3,
        entry_price: 250.5,
        entry_currency: "USD",
        tags: ["leader"],
      }),
    ]);
  });

  it("applies settings defaults and ticker normalization on import", () => {
    const parsed = parseHoldingsYamlDocument(`
version: 1
settings:
  default_currency: USD
  default_strategy: swing
  default_tags:
    - leader
holdings:
  - ticker: BRK/B.NYS
    quantity: 2
    entry_price: 510
`);

    expect(parsed).toEqual([
      snapshot({
        ticker: "BRK.B.NYS",
        quantity: 2,
        entry_price: 510,
        entry_currency: "USD",
        strategy: "swing",
        tags: ["leader"],
      }),
    ]);
  });

  it("rejects mixed-market imports without explicit row currencies", () => {
    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: "005930"
    quantity: 1
    entry_price: 70000
    entry_currency: KRW
  - ticker: TSLA.NAS
    quantity: 1
    entry_price: 250
`),
    ).toThrow(HoldingsYamlError);
  });

  it("builds a replace-all diff summary", () => {
    const summary = buildHoldingsYamlImportSummary(
      [
        record({
          ticker: "005930",
          quantity: 1,
          entry_price: 70000,
        }),
        record({
          ticker: "MSFT.NAS",
          quantity: 2,
          entry_price: 300,
          entry_currency: "USD",
        }),
      ],
      [
        snapshot({
          ticker: "005930",
          quantity: 1,
          entry_price: 70000,
        }),
        snapshot({
          ticker: "TSLA.NAS",
          quantity: 3,
          entry_price: 250,
          entry_currency: "USD",
        }),
      ],
    );

    expect(summary).toEqual({
      incomingCount: 2,
      createCount: 1,
      updateCount: 0,
      deleteCount: 1,
      unchangedCount: 1,
      createTickers: ["TSLA.NAS"],
      updateTickers: [],
      deleteTickers: ["MSFT.NAS"],
    });
  });
});
