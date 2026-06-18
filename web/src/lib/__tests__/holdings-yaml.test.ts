import { describe, expect, it } from "vitest";

import {
  buildHoldingsYamlDocument,
  buildHoldingsYamlImportSummary,
  HoldingsYamlError,
  parseHoldingsYamlDocument,
} from "@/lib/holdings-yaml";
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
        entry_pattern: "swing_high_breakout",
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
        entry_pattern: "swing_high_breakout",
        tags: ["leader"],
      }),
    ]);
  });

  it("exports explicit null entry pattern ownership", () => {
    const document = buildHoldingsYamlDocument([
      snapshot({
        ticker: "AAPL.NAS",
        entry_currency: "USD",
        entry_pattern: null,
      }),
    ]);

    expect(document).toContain("entry_pattern: null");
    const parsed = parseHoldingsYamlDocument(document);
    expect(
      Object.prototype.hasOwnProperty.call(parsed[0], "entry_pattern"),
    ).toBe(true);
    expect(parsed[0]?.entry_pattern).toBeNull();
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
      {
        ticker: "BRK.B.NYS",
        quantity: 2,
        entry_price: 510,
        entry_currency: "USD",
        entry_date: null,
        strategy: "swing",
        notes: null,
        tags: ["leader"],
        stop_override: null,
        target_override: null,
      },
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

  it("rejects active holdings with zero entry price", () => {
    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: "005930"
    quantity: 1
    entry_price: 0
`),
    ).toThrow(/entry_price.*quantity > 0/);
  });

  it("rejects malformed numeric strings instead of partially parsing them", () => {
    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: "005930"
    quantity: "10 shares"
    entry_price: 70000
`),
    ).toThrow(/quantity.*finite number/);

    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: "005930"
    quantity: 1
    entry_price: "70,000"
`),
    ).toThrow(/entry_price.*finite number/);
  });

  it("rejects invalid calendar entry_date values", () => {
    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: "005930"
    quantity: 1
    entry_price: 70000
    entry_date: 2026-02-31
`),
    ).toThrow(/entry_date.*valid YYYY-MM-DD date/);
  });

  it("allows inactive holdings with zero entry price", () => {
    expect(
      parseHoldingsYamlDocument(`
holdings:
  - ticker: "005930"
    quantity: 0
    entry_price: 0
`),
    ).toEqual([
      {
        ticker: "005930",
        quantity: 0,
        entry_price: 0,
        entry_currency: null,
        entry_date: null,
        strategy: null,
        notes: null,
        tags: [],
        stop_override: null,
        target_override: null,
      },
    ]);
  });

  it("rejects unknown entry pattern values", () => {
    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
    entry_pattern: not_a_breakout
`),
    ).toThrow(/entry_pattern.*one of/);
  });

  it("rejects inactive holdings with non-null entry pattern", () => {
    expect(() =>
      parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 0
    entry_price: 0
    entry_currency: USD
    entry_pattern: swing_high_breakout
`),
    ).toThrow(/entry_pattern.*inactive/);
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

  it("treats omitted entry pattern as preserve-existing for active row diff", () => {
    const incoming = parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
`);
    expect(
      Object.prototype.hasOwnProperty.call(incoming[0], "entry_pattern"),
    ).toBe(false);

    const summary = buildHoldingsYamlImportSummary(
      [
        record({
          ticker: "AAPL.NAS",
          quantity: 1,
          entry_price: 100,
          entry_currency: "USD",
          entry_pattern: "swing_high_breakout",
        }),
      ],
      incoming,
    );

    expect(summary.updateCount).toBe(0);
    expect(summary.unchangedCount).toBe(1);
  });

  it("requires explicit entry pattern when entry identity changes", () => {
    const incoming = parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 101
    entry_currency: USD
`) satisfies HoldingReplaceSnapshot[];

    expect(() =>
      buildHoldingsYamlImportSummary(
        [
          record({
            ticker: "AAPL.NAS",
            quantity: 1,
            entry_price: 100,
            entry_currency: "USD",
            entry_pattern: "swing_high_breakout",
          }),
        ],
        incoming,
      ),
    ).toThrow(/entry_pattern.*entry identity/);
  });

  it("treats explicit null entry pattern as a clear during diff", () => {
    const incoming = parseHoldingsYamlDocument(`
holdings:
  - ticker: AAPL.NAS
    quantity: 1
    entry_price: 100
    entry_currency: USD
    entry_pattern: null
`);
    expect(
      Object.prototype.hasOwnProperty.call(incoming[0], "entry_pattern"),
    ).toBe(true);

    const summary = buildHoldingsYamlImportSummary(
      [
        record({
          ticker: "AAPL.NAS",
          quantity: 1,
          entry_price: 100,
          entry_currency: "USD",
          entry_pattern: "swing_high_breakout",
        }),
      ],
      incoming,
    );

    expect(summary.updateCount).toBe(1);
  });
});
