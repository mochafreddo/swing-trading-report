import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/runtime-state", () => ({
  upsertRuntimeStateEntry: vi.fn(),
}));

vi.mock("@/lib/env.server", () => ({
  getSupabaseEnv: vi.fn(() => ({
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_API_KEY: "sb_secret_test",
  })),
}));

vi.mock("@/lib/supabase/admin-client", () => ({
  buildAuthHeaders: vi.fn((headers) => ({
    apikey: "sb_secret_test",
    Authorization: "Bearer sb_secret_test",
    ...headers,
  })),
  fetchSupabase: vi.fn(),
  parseError: vi.fn(async () => "upstream error"),
  SupabaseApiError: class SupabaseApiError extends Error {
    constructor(
      message: string,
      readonly status: number,
    ) {
      super(message);
    }
  },
}));

import {
  applyTossHoldingsSyncPreview,
  buildTossHoldingsSyncDependenciesFromEnv,
  buildTossHoldingsSyncPreview,
  recordScheduledTossFreshnessMarker,
  runScheduledTossAutoApply,
  type ScheduledTossAutoSyncResponse,
  type TossHoldingsSyncDependencies,
} from "@/lib/toss/holdings-sync-service";
import { upsertRuntimeStateEntry } from "@/lib/supabase/runtime-state";
import { fetchSupabase } from "@/lib/supabase/admin-client";
import type { HoldingRecord } from "@/lib/types";

const REPLACE_DIGEST = `sha256:${"a".repeat(64)}`;
const QUARANTINE_DIGEST = `sha256:${"b".repeat(64)}`;
const UNCHANGED_DIGEST = `sha256:${"c".repeat(64)}`;
const INITIAL_DIGEST = `sha256:${"d".repeat(64)}`;

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
    broker_state: overrides.broker_state ?? "confirmed",
    broker_missing_first_seen_date:
      overrides.broker_missing_first_seen_date ?? null,
    broker_missing_last_seen_date:
      overrides.broker_missing_last_seen_date ?? null,
    broker_missing_count: overrides.broker_missing_count ?? 0,
    broker_missing_diff_hash: overrides.broker_missing_diff_hash ?? null,
    created_at: overrides.created_at ?? "2026-06-30T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-06-30T00:00:00Z",
  } satisfies HoldingRecord;
}

function deps(
  overrides: Partial<TossHoldingsSyncDependencies> = {},
): TossHoldingsSyncDependencies {
  const fetchAllHoldings = overrides.fetchAllHoldings ?? vi.fn(async () => []);
  return {
    fetchAllHoldings,
    fetchBrokerHoldingsState: vi.fn(async () => ({
      holdings: await fetchAllHoldings(),
      holdingsDigest: INITIAL_DIGEST,
    })),
    fetchTossHoldingsItems: vi.fn(async () => []),
    listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
      candidates: [],
      directory: {
        builtAtMs: 0,
        sourceReports: 0,
        usableForAutoMapping: false,
      },
    })),
    listReviewedTickerMappings: vi.fn(async () => []),
    replaceAllHoldings: vi.fn(async () => ({
      insertedCount: 0,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
    })),
    replaceAllHoldingsAndCaptureBrokerDigest: vi.fn(async () => ({
      insertedCount: 0,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
      postStateDigest: REPLACE_DIGEST,
    })),
    applyScheduledTossQuarantine: vi.fn(async (input) => ({
      insertedCount: 0,
      updatedCount: 0,
      quarantinedCount: input.quarantineTickers.length,
      unchangedCount: 0,
      postStateDigest: QUARANTINE_DIGEST,
    })),
    captureBrokerHoldingsDigest: vi.fn(async () => UNCHANGED_DIGEST),
    ...overrides,
  };
}

describe("toss holdings sync service", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it("builds a preview and applies create update delete changes", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => [
        holding({
          ticker: "AAPL.NAS",
          quantity: 1,
          entry_price: 190,
          entry_currency: "USD",
        }),
        holding({
          ticker: "TSLA.NAS",
          quantity: 1,
          entry_price: 200,
          entry_currency: "USD",
        }),
      ]),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "AAPL",
          marketCountry: "US",
          currency: "USD",
          quantity: "2",
          averagePurchasePrice: "188",
        },
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "1",
          averagePurchasePrice: "70000",
        },
      ]),
      replaceAllHoldings: vi.fn(async () => ({
        insertedCount: 1,
        updatedCount: 1,
        deletedCount: 1,
        unchangedCount: 0,
      })),
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);
    const payload = await applyTossHoldingsSyncPreview(preview, testDeps);

    expect(payload.mode).toBe("apply");
    expect(payload.summary).toEqual(
      expect.objectContaining({
        createCount: 1,
        updateCount: 1,
        deleteCount: 1,
      }),
    );
    expect(testDeps.replaceAllHoldings).toHaveBeenCalledWith(
      [
        expect.objectContaining({ ticker: "005930" }),
        expect.objectContaining({ ticker: "AAPL.NAS", quantity: 2 }),
      ],
      {
        expectedCurrentHoldings: [
          expect.objectContaining({ ticker: "AAPL.NAS" }),
          expect.objectContaining({ ticker: "TSLA.NAS" }),
        ],
      },
    );
  });

  it("fails apply when replace-all result counts diverge from the preview", async () => {
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "1",
          averagePurchasePrice: "70000",
        },
      ]),
      replaceAllHoldings: vi.fn(async () => ({
        insertedCount: 0,
        updatedCount: 0,
        deletedCount: 0,
        unchangedCount: 1,
      })),
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    await expect(
      applyTossHoldingsSyncPreview(preview, testDeps),
    ).rejects.toThrow("replace_holdings_v1 result did not match preview");
  });

  it("scheduled auto apply returns disabled without fetching when the flag is off", async () => {
    const testDeps = deps();

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: false },
      testDeps,
    );

    expect(result.status).toBe("disabled");
    expect(testDeps.fetchAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("scheduled auto apply skips blocked previews without writing", async () => {
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("blocked");
    expect(result.applyBlocked).toBe(true);
    expect(result.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("dry-run preview degrades to blocked rows when ticker-directory lookup fails", async () => {
    const listReviewedTickerMappings = vi.fn(async () => [
      { ticker: "MSFT.NAS" },
    ]);
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
      listTickerDirectoryExactBaseCandidates: vi.fn(async () => {
        throw new Error("ticker directory unavailable");
      }),
      listReviewedTickerMappings,
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    expect(preview.payload.applyBlocked).toBe(true);
    expect(preview.payload.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
    expect(listReviewedTickerMappings).not.toHaveBeenCalled();
  });

  it("uses the reviewed registry when the ticker directory has no candidate", async () => {
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
      listReviewedTickerMappings: vi.fn(async () => [{ ticker: "MSFT.NAS" }]),
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    expect(preview.payload.applyBlocked).toBe(false);
    expect(preview.payload.targetRows).toEqual([
      expect.objectContaining({ ticker: "MSFT.NAS" }),
    ]);
  });

  it("keeps an exact class-share directory match ahead of the registry fallback", async () => {
    const listReviewedTickerMappings = vi.fn(async () => [
      { ticker: "BRK.B.NAS" },
    ]);
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "BRK/B",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "500",
        },
      ]),
      listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
        candidates: [{ ticker: "BRK.B.NYS", name: "Berkshire Hathaway" }],
        directory: {
          builtAtMs: Date.now(),
          sourceReports: 1,
          usableForAutoMapping: true,
        },
      })),
      listReviewedTickerMappings,
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    expect(preview.payload.applyBlocked).toBe(false);
    expect(preview.payload.targetRows).toEqual([
      expect.objectContaining({ ticker: "BRK.B.NYS" }),
    ]);
    expect(listReviewedTickerMappings).not.toHaveBeenCalled();
  });

  it("sends only unresolved symbols to the reviewed registry in a mixed batch", async () => {
    const listReviewedTickerMappings = vi.fn(async () => [
      { ticker: "MSFT.NAS" },
    ]);
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "AAPL",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "190",
        },
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
      listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
        candidates: [{ ticker: "AAPL.NAS", name: "Apple" }],
        directory: {
          builtAtMs: Date.now(),
          sourceReports: 1,
          usableForAutoMapping: true,
        },
      })),
      listReviewedTickerMappings,
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    expect(listReviewedTickerMappings).toHaveBeenCalledWith(["MSFT"]);
    expect(preview.payload.applyBlocked).toBe(false);
    expect(preview.payload.targetRows.map((row) => row.ticker)).toEqual([
      "AAPL.NAS",
      "MSFT.NAS",
    ]);
  });

  it("does not let the registry override ambiguous directory venues", async () => {
    const listReviewedTickerMappings = vi.fn(async () => [
      { ticker: "ABC.NAS" },
    ]);
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "ABC",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "10",
        },
      ]),
      listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
        candidates: [
          { ticker: "ABC.NAS", name: null },
          { ticker: "ABC.NYS", name: null },
        ],
        directory: {
          builtAtMs: Date.now(),
          sourceReports: 1,
          usableForAutoMapping: true,
        },
      })),
      listReviewedTickerMappings,
    });

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    expect(listReviewedTickerMappings).not.toHaveBeenCalled();
    expect(preview.payload.applyBlocked).toBe(true);
    expect(preview.payload.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
  });

  it("scheduled auto apply propagates registry validation failure before writes", async () => {
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
      listReviewedTickerMappings: vi.fn(async () => {
        throw new Error("reviewed registry invalid");
      }),
    });

    await expect(
      runScheduledTossAutoApply({ autoApplyEnabled: true }, testDeps),
    ).rejects.toThrow("reviewed registry invalid");
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(
      testDeps.replaceAllHoldingsAndCaptureBrokerDigest,
    ).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
    expect(testDeps.captureBrokerHoldingsDigest).not.toHaveBeenCalled();
  });

  it("scheduled auto apply fails closed when ticker-directory lookup fails", async () => {
    const testDeps = deps({
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "MSFT",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "400",
        },
      ]),
      listTickerDirectoryExactBaseCandidates: vi.fn(async () => {
        throw new Error("ticker directory unavailable");
      }),
    });

    await expect(
      runScheduledTossAutoApply({ autoApplyEnabled: true }, testDeps),
    ).rejects.toThrow("ticker directory unavailable");
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("scheduled auto apply blocks an empty Toss snapshot from wiping active holdings", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => [
        holding({ ticker: "AAPL.NAS", quantity: 1, entry_price: 190 }),
      ]),
      fetchTossHoldingsItems: vi.fn(async () => []),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("wipe_guard_blocked");
    expect(result.summary.deleteCount).toBe(1);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("scheduled auto apply blocks an empty Toss snapshot from deleting inactive holdings", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => [
        holding({ ticker: "AAPL.NAS", quantity: 0, entry_price: 190 }),
      ]),
      fetchTossHoldingsItems: vi.fn(async () => []),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("wipe_guard_blocked");
    expect(result.summary.deleteCount).toBe(1);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("scheduled auto apply quarantines delete diffs from non-empty Toss snapshots", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => [
        holding({
          ticker: "AAPL.NAS",
          quantity: 1,
          entry_price: 190,
          entry_currency: "USD",
        }),
        holding({
          ticker: "TSLA.NAS",
          quantity: 1,
          entry_price: 200,
          entry_currency: "USD",
        }),
      ]),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "AAPL",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "190",
        },
      ]),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true, sessionDate: "2026-07-08" },
      testDeps,
    );

    expect(result.status).toBe("applied");
    expect(result.expectedPostStateDigest).toBe(QUARANTINE_DIGEST);
    expect(result.summary.deleteCount).toBe(1);
    expect(result.quarantinedCount).toBe(1);
    expect(result.quarantinedTickers).toEqual(["TSLA.NAS"]);
    expect(result.changes.delete).toEqual([
      expect.objectContaining({ ticker: "TSLA.NAS" }),
    ]);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).toHaveBeenCalledWith({
      targetRows: [expect.objectContaining({ ticker: "AAPL.NAS" })],
      quarantineTickers: ["TSLA.NAS"],
      expectedCurrentHoldings: expect.arrayContaining([
        expect.objectContaining({ ticker: "AAPL.NAS" }),
        expect.objectContaining({ ticker: "TSLA.NAS" }),
      ]),
      sessionDate: "2026-07-08",
      diffHash: result.diffHash,
    });
  });

  it("scheduled auto apply writes with a current-holdings compare-and-swap snapshot", async () => {
    const currentHoldings = [
      holding({
        ticker: "005930",
        quantity: 1,
        entry_price: 69000,
      }),
    ];
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => currentHoldings),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "2",
          averagePurchasePrice: "70000",
        },
      ]),
      replaceAllHoldings: vi.fn(async () => ({
        insertedCount: 0,
        updatedCount: 1,
        deletedCount: 0,
        unchangedCount: 0,
      })),
      replaceAllHoldingsAndCaptureBrokerDigest: vi.fn(async () => ({
        insertedCount: 0,
        updatedCount: 1,
        deletedCount: 0,
        unchangedCount: 0,
        postStateDigest: REPLACE_DIGEST,
      })),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("applied");
    expect(result.expectedPostStateDigest).toBe(REPLACE_DIGEST);
    expect(
      testDeps.replaceAllHoldingsAndCaptureBrokerDigest,
    ).toHaveBeenCalledWith(
      [expect.objectContaining({ ticker: "005930", quantity: 2 })],
      { expectedCurrentHoldings: currentHoldings },
    );
  });

  it("scheduled auto apply restores broker state when a quarantined holding reappears", async () => {
    const currentHoldings = [
      holding({
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
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => currentHoldings),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "TSLA",
          marketCountry: "US",
          currency: "USD",
          quantity: "1",
          averagePurchasePrice: "250",
        },
      ]),
      replaceAllHoldings: vi.fn(async () => ({
        insertedCount: 0,
        updatedCount: 1,
        deletedCount: 0,
        unchangedCount: 0,
      })),
      replaceAllHoldingsAndCaptureBrokerDigest: vi.fn(async () => ({
        insertedCount: 0,
        updatedCount: 1,
        deletedCount: 0,
        unchangedCount: 0,
        postStateDigest: REPLACE_DIGEST,
      })),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("applied");
    expect(result.summary.updateCount).toBe(1);
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
    expect(
      testDeps.replaceAllHoldingsAndCaptureBrokerDigest,
    ).toHaveBeenCalledWith([expect.objectContaining({ ticker: "TSLA.NAS" })], {
      expectedCurrentHoldings: currentHoldings,
    });
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("scheduled auto apply treats empty Toss and empty active holdings as unchanged", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => []),
      fetchTossHoldingsItems: vi.fn(async () => []),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("unchanged");
    expect(result.summary.incomingCount).toBe(0);
    expect(result.expectedPostStateDigest).toBe(UNCHANGED_DIGEST);
    expect(testDeps.captureBrokerHoldingsDigest).toHaveBeenCalledWith(
      INITIAL_DIGEST,
    );
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
  });

  it("fails closed when holdings change between scheduled preview and unchanged capture", async () => {
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => []),
      fetchTossHoldingsItems: vi.fn(async () => []),
      captureBrokerHoldingsDigest: vi.fn(async () => {
        throw new Error("broker holdings pre-state conflict");
      }),
    });

    await expect(
      runScheduledTossAutoApply(
        { autoApplyEnabled: true, sessionDate: "2026-08-06" },
        testDeps,
      ),
    ).rejects.toThrow("pre-state conflict");
    expect(testDeps.captureBrokerHoldingsDigest).toHaveBeenCalledWith(
      INITIAL_DIGEST,
    );
  });

  it("uses the DB mutation digest when an active normal holding becomes zero", async () => {
    const currentHoldings = [
      holding({
        ticker: "005930",
        quantity: 1,
        entry_price: 70000,
        entry_pattern: "trend_pullback_bounce",
      }),
    ];
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => currentHoldings),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "0",
          averagePurchasePrice: "70000",
        },
      ]),
      replaceAllHoldingsAndCaptureBrokerDigest: vi.fn(async () => ({
        insertedCount: 0,
        updatedCount: 1,
        deletedCount: 0,
        unchangedCount: 0,
        postStateDigest: REPLACE_DIGEST,
      })),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true, sessionDate: "2026-08-06" },
      testDeps,
    );

    expect(result.expectedPostStateDigest).toBe(REPLACE_DIGEST);
    expect(
      testDeps.replaceAllHoldingsAndCaptureBrokerDigest,
    ).toHaveBeenCalledWith(
      [expect.objectContaining({ ticker: "005930", quantity: 0 })],
      { expectedCurrentHoldings: currentHoldings },
    );
  });

  it("uses the DB quarantine digest when an active target holding becomes zero", async () => {
    const currentHoldings = [
      holding({
        ticker: "005930",
        quantity: 1,
        entry_price: 70000,
        entry_pattern: "trend_pullback_bounce",
      }),
      holding({ ticker: "035420", quantity: 1, entry_price: 200000 }),
    ];
    const testDeps = deps({
      fetchAllHoldings: vi.fn(async () => currentHoldings),
      fetchTossHoldingsItems: vi.fn(async () => [
        {
          symbol: "005930",
          marketCountry: "KR",
          currency: "KRW",
          quantity: "0",
          averagePurchasePrice: "70000",
        },
      ]),
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true, sessionDate: "2026-08-06" },
      testDeps,
    );

    expect(result.expectedPostStateDigest).toBe(QUARANTINE_DIGEST);
    expect(testDeps.applyScheduledTossQuarantine).toHaveBeenCalledWith(
      expect.objectContaining({
        targetRows: [
          expect.objectContaining({ ticker: "005930", quantity: 0 }),
        ],
        quarantineTickers: ["035420"],
      }),
    );
  });

  it("rejects a future KST session before reading or mutating holdings", async () => {
    const testDeps = deps();

    await expect(
      runScheduledTossAutoApply(
        {
          autoApplyEnabled: true,
          sessionDate: "2099-01-01",
          now: new Date("2026-08-06T00:00:00Z"),
        },
        testDeps,
      ),
    ).rejects.toThrow("future KST session");
    expect(testDeps.fetchAllHoldings).not.toHaveBeenCalled();
    expect(
      testDeps.replaceAllHoldingsAndCaptureBrokerDigest,
    ).not.toHaveBeenCalled();
    expect(testDeps.applyScheduledTossQuarantine).not.toHaveBeenCalled();
  });

  it("records a scheduled Toss freshness marker with key payload and TTL", async () => {
    const now = new Date("2026-07-06T22:15:00.000Z");
    const result = {
      mode: "auto-apply",
      status: "applied",
      summary: {
        incomingCount: 3,
        createCount: 1,
        updateCount: 1,
        deleteCount: 0,
        unchangedCount: 1,
        createTickers: ["005930"],
        updateTickers: ["AAPL.NAS"],
        deleteTickers: [],
      },
      diffHash: "hash-1",
      applyBlocked: false,
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
      quarantinedCount: 1,
      quarantinedTickers: ["TSLA.NAS"],
      expectedPostStateDigest: `sha256:${"c".repeat(64)}`,
    } satisfies ScheduledTossAutoSyncResponse;

    vi.mocked(fetchSupabase).mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            state_key: "toss-sync:success:MIXED:2026-07-06",
            session_date: "2026-07-06",
            status: "applied",
            fresh_until: "2026-07-08T10:15:00.000Z",
            sealed_at: "2026-07-06T22:15:01.000Z",
            holdings_digest: `sha256:${"a".repeat(64)}`,
            revision: 7,
          },
        ]),
        { status: 200 },
      ),
    );

    await expect(
      recordScheduledTossFreshnessMarker(result, {
        sessionDate: "2026-07-06",
        now,
      }),
    ).resolves.toEqual({
      stateKey: "toss-sync:success:MIXED:2026-07-06",
      sessionDate: "2026-07-06",
      holdingsDigest: `sha256:${"a".repeat(64)}`,
      revision: 7,
      sealedAt: "2026-07-06T22:15:01.000Z",
    });

    expect(fetchSupabase).toHaveBeenCalledWith(
      "https://example.supabase.co/rest/v1/rpc/seal_broker_snapshot_v0",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining(
          '"p_state_key":"toss-sync:success:MIXED:2026-07-06"',
        ),
      }),
    );
    const sealBody = JSON.parse(
      String(vi.mocked(fetchSupabase).mock.calls[0]?.[1]?.body),
    ) as Record<string, unknown>;
    expect(sealBody.p_expected_post_state_digest).toBe(
      `sha256:${"c".repeat(64)}`,
    );
    expect(upsertRuntimeStateEntry).not.toHaveBeenCalled();
  });

  it("uses the KST date fallback and skips non-success statuses for freshness markers", async () => {
    const now = new Date("2026-07-06T16:00:00.000Z");
    const unchanged = {
      mode: "auto-apply",
      status: "unchanged",
      summary: {
        incomingCount: 0,
        createCount: 0,
        updateCount: 0,
        deleteCount: 0,
        unchangedCount: 0,
        createTickers: [],
        updateTickers: [],
        deleteTickers: [],
      },
      diffHash: "hash-empty",
      applyBlocked: false,
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
      quarantinedCount: 0,
      quarantinedTickers: [],
      expectedPostStateDigest: `sha256:${"d".repeat(64)}`,
    } satisfies ScheduledTossAutoSyncResponse;

    vi.mocked(fetchSupabase).mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            state_key: "toss-sync:success:MIXED:2026-07-07",
            session_date: "2026-07-07",
            status: "unchanged",
            fresh_until: "2026-07-08T04:00:00.000Z",
            sealed_at: "2026-07-06T16:00:01.000Z",
            holdings_digest: `sha256:${"b".repeat(64)}`,
            revision: 8,
          },
        ]),
        { status: 200 },
      ),
    );

    await expect(
      recordScheduledTossFreshnessMarker(unchanged, { now }),
    ).resolves.toEqual({
      stateKey: "toss-sync:success:MIXED:2026-07-07",
      sessionDate: "2026-07-07",
      holdingsDigest: `sha256:${"b".repeat(64)}`,
      revision: 8,
      sealedAt: "2026-07-06T16:00:01.000Z",
    });

    expect(fetchSupabase).toHaveBeenCalledTimes(1);
    vi.mocked(fetchSupabase).mockClear();

    await expect(
      recordScheduledTossFreshnessMarker({
        ...unchanged,
        status: "blocked",
        applyBlocked: true,
      }),
    ).resolves.toBeNull();

    expect(fetchSupabase).not.toHaveBeenCalled();
    expect(upsertRuntimeStateEntry).not.toHaveBeenCalled();
  });

  it("refuses to seal a successful sync without an expected post-state digest", async () => {
    const result = {
      mode: "auto-apply",
      status: "unchanged",
      summary: {
        incomingCount: 0,
        createCount: 0,
        updateCount: 0,
        deleteCount: 0,
        unchangedCount: 0,
        createTickers: [],
        updateTickers: [],
        deleteTickers: [],
      },
      diffHash: "hash-empty",
      applyBlocked: false,
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
      quarantinedCount: 0,
      quarantinedTickers: [],
    } satisfies ScheduledTossAutoSyncResponse;

    await expect(recordScheduledTossFreshnessMarker(result)).rejects.toThrow(
      "expected post-state digest",
    );
    expect(fetchSupabase).not.toHaveBeenCalled();
  });

  it("builds runtime dependencies that read QA holdings from a fixture file", async () => {
    vi.stubEnv("TOSS_SYNC_SOURCE", "fixture");
    vi.stubEnv("TOSS_SYNC_QA_FIXTURE_ENABLED", "1");
    vi.stubEnv("SUPABASE_URL", "http://host.docker.internal:54321");
    vi.stubEnv("TOSS_INVEST_CLIENT_ID", "");
    vi.stubEnv("TOSS_INVEST_CLIENT_SECRET", "");
    vi.stubEnv("TOSS_INVEST_ACCOUNT", "");

    const runtimeDeps = buildTossHoldingsSyncDependenciesFromEnv();

    await expect(runtimeDeps.fetchTossHoldingsItems()).resolves.toEqual([
      expect.objectContaining({ symbol: "005930", marketCountry: "KR" }),
      expect.objectContaining({
        symbol: "AAPL",
        name: "Apple Inc.",
        marketCountry: "US",
      }),
    ]);
  });

  it("refuses fixture source without the explicit QA guard", () => {
    vi.stubEnv("TOSS_SYNC_SOURCE", "fixture");
    vi.stubEnv("SUPABASE_URL", "http://host.docker.internal:54321");

    expect(() => buildTossHoldingsSyncDependenciesFromEnv()).toThrow(
      "TOSS_SYNC_QA_FIXTURE_ENABLED=1",
    );
  });

  it("refuses fixture source when Supabase is not local", () => {
    vi.stubEnv("TOSS_SYNC_SOURCE", "fixture");
    vi.stubEnv("TOSS_SYNC_QA_FIXTURE_ENABLED", "1");
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");

    expect(() => buildTossHoldingsSyncDependenciesFromEnv()).toThrow(
      "local Supabase",
    );
  });
});
