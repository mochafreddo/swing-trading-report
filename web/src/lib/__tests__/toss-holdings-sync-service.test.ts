import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/runtime-state", () => ({
  upsertRuntimeStateEntry: vi.fn(),
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
    created_at: overrides.created_at ?? "2026-06-30T00:00:00Z",
    updated_at: overrides.updated_at ?? "2026-06-30T00:00:00Z",
  } satisfies HoldingRecord;
}

function deps(
  overrides: Partial<TossHoldingsSyncDependencies> = {},
): TossHoldingsSyncDependencies {
  return {
    fetchAllHoldings: vi.fn(async () => []),
    fetchTossHoldingsItems: vi.fn(async () => []),
    listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
      candidates: [],
      directory: {
        builtAtMs: 0,
        sourceReports: 0,
        usableForAutoMapping: false,
      },
    })),
    replaceAllHoldings: vi.fn(async () => ({
      insertedCount: 0,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
    })),
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
  });

  it("dry-run preview degrades to blocked rows when ticker-directory lookup fails", async () => {
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

    const preview = await buildTossHoldingsSyncPreview(testDeps);

    expect(preview.payload.applyBlocked).toBe(true);
    expect(preview.payload.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
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
  });

  it("scheduled auto apply blocks delete diffs from non-empty Toss snapshots", async () => {
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
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("delete_guard_blocked");
    expect(result.summary.deleteCount).toBe(1);
    expect(result.changes.delete).toEqual([
      expect.objectContaining({ ticker: "TSLA.NAS" }),
    ]);
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
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
    });

    const result = await runScheduledTossAutoApply(
      { autoApplyEnabled: true },
      testDeps,
    );

    expect(result.status).toBe("applied");
    expect(testDeps.replaceAllHoldings).toHaveBeenCalledWith(
      [expect.objectContaining({ ticker: "005930", quantity: 2 })],
      { expectedCurrentHoldings: currentHoldings },
    );
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
    expect(testDeps.replaceAllHoldings).not.toHaveBeenCalled();
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
    } satisfies ScheduledTossAutoSyncResponse;

    await expect(
      recordScheduledTossFreshnessMarker(result, {
        sessionDate: "2026-07-06",
        now,
      }),
    ).resolves.toEqual({
      stateKey: "toss-sync:success:MIXED:2026-07-06",
      sessionDate: "2026-07-06",
    });

    expect(upsertRuntimeStateEntry).toHaveBeenCalledWith(
      "toss-sync:success:MIXED:2026-07-06",
      {
        scope: "MIXED",
        sessionDate: "2026-07-06",
        status: "applied",
        diffHash: "hash-1",
        incomingCount: 3,
        createCount: 1,
        updateCount: 1,
        deleteCount: 0,
        unchangedCount: 1,
        source: "scheduled-route",
        timezone: "Asia/Seoul",
        updatedAt: "2026-07-06T22:15:00.000Z",
      },
      "2026-07-08T10:15:00.000Z",
    );
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
    } satisfies ScheduledTossAutoSyncResponse;

    await expect(
      recordScheduledTossFreshnessMarker(unchanged, { now }),
    ).resolves.toEqual({
      stateKey: "toss-sync:success:MIXED:2026-07-07",
      sessionDate: "2026-07-07",
    });

    expect(upsertRuntimeStateEntry).toHaveBeenCalledWith(
      "toss-sync:success:MIXED:2026-07-07",
      expect.objectContaining({
        sessionDate: "2026-07-07",
        status: "unchanged",
      }),
      "2026-07-08T04:00:00.000Z",
    );
    vi.mocked(upsertRuntimeStateEntry).mockClear();

    await expect(
      recordScheduledTossFreshnessMarker({
        ...unchanged,
        status: "blocked",
        applyBlocked: true,
      }),
    ).resolves.toBeNull();

    expect(upsertRuntimeStateEntry).not.toHaveBeenCalled();
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
