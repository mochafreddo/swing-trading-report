import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/env.server", () => ({
  getSupabaseEnv: vi.fn(() => ({
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_API_KEY: "sb_secret_test_key",
    SUPABASE_REPORTS_BUCKET: "reports",
    REPORT_RETENTION_DAYS: 30,
  })),
}));

vi.mock("@/lib/supabase-admin", () => ({
  fetchReportIndexPage: vi.fn(),
  downloadStorageJson: vi.fn(),
  fetchRuntimeStateEntry: vi.fn(),
  upsertRuntimeStateEntry: vi.fn(),
}));

import {
  extractBuyCandidatesFromReport,
  listRecentBuyCandidates,
  searchTickerDirectory,
} from "@/lib/ticker-directory";
import {
  downloadStorageJson,
  fetchReportIndexPage,
  fetchRuntimeStateEntry,
  upsertRuntimeStateEntry,
} from "@/lib/supabase-admin";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("extractBuyCandidatesFromReport", () => {
  it("extracts ticker/name pairs and canonicalizes slash class ticker", () => {
    const candidates = extractBuyCandidatesFromReport({
      candidates: [
        {
          ticker: "brk/b.nys",
          name: "버크셔 해서웨이",
        },
        {
          ticker: "  ",
          name: "invalid",
        },
        {
          ticker: "COST.NAS",
          name: "코스트코",
        },
      ],
    });

    expect(candidates).toEqual([
      {
        ticker: "BRK.B.NYS",
        name: "버크셔 해서웨이",
      },
      {
        ticker: "COST.NAS",
        name: "코스트코",
      },
    ]);
  });

  it("deduplicates ticker while keeping the first seen order", () => {
    const candidates = extractBuyCandidatesFromReport({
      candidates: [
        { ticker: "ABBV.NYS", name: "애브비" },
        { ticker: "ABBV.NYS", name: "AbbVie" },
        { ticker: "ETN.NYS", name: "이튼" },
      ],
    });

    expect(candidates).toEqual([
      { ticker: "ABBV.NYS", name: "애브비" },
      { ticker: "ETN.NYS", name: "이튼" },
    ]);
  });
});

describe("searchTickerDirectory", () => {
  it("builds cache when runtime_state is missing and returns name search results", async () => {
    vi.mocked(fetchRuntimeStateEntry).mockResolvedValueOnce(null);
    vi.mocked(fetchReportIndexPage)
      .mockResolvedValueOnce({
        items: [
          {
            report_key: "2026/02/2026-02-27.buy.json",
            report_type: "buy",
            report_date: "2026-02-27",
            duplicate_index: 0,
            generated_at: "2026-02-27T00:00:00Z",
            summary: null,
            tickers: [],
            tickers_hydrated: true,
          },
        ],
        total: 1,
        fetchedCount: 1,
        hasMore: false,
        nextCursor: null,
      })
      .mockResolvedValueOnce({
        items: [
          {
            report_key: "2026/02/2026-02-27.buy.json",
            report_type: "buy",
            report_date: "2026-02-27",
            duplicate_index: 0,
            generated_at: "2026-02-27T00:00:00Z",
            summary: null,
            tickers: [],
            tickers_hydrated: true,
          },
        ],
        total: 1,
        fetchedCount: 1,
        hasMore: false,
        nextCursor: null,
      });

    vi.mocked(downloadStorageJson).mockResolvedValueOnce({
      candidates: [
        { ticker: "COST.NAS", name: "코스트코 홀세일" },
        { ticker: "ETN.NYS", name: "이튼" },
      ],
    });

    const result = await searchTickerDirectory({ q: "코스트코", limit: 5 });

    expect(result.results).toEqual([
      {
        ticker: "COST.NAS",
        name: "코스트코 홀세일",
      },
    ]);
    expect(vi.mocked(upsertRuntimeStateEntry)).toHaveBeenCalledTimes(1);
  });

  it("incrementally merges only new reports when cache already exists", async () => {
    vi.mocked(fetchRuntimeStateEntry).mockResolvedValueOnce({
      state_key: "ticker_directory:v1",
      expires_at: "2099-01-01T00:00:00.000Z",
      state_payload: {
        version: 1,
        builtAtMs: Date.now(),
        source: {
          buyReportsScanned: 1,
          buyReportKeys: ["2026/02/2026-02-26.buy.json"],
        },
        entries: [
          {
            ticker: "ABBV.NYS",
            name: "애브비",
            aliases: ["ABBV.NYS", "ABBV", "애브비"],
            lastSeenReportDate: "2026-02-26",
            lastSeenReportKey: "2026/02/2026-02-26.buy.json",
            updatedAtMs: Date.now() - 1000,
          },
        ],
      },
    });
    vi.mocked(fetchReportIndexPage)
      .mockResolvedValueOnce({
        items: [
          {
            report_key: "2026/02/2026-02-27.buy.json",
            report_type: "buy",
            report_date: "2026-02-27",
            duplicate_index: 0,
            generated_at: "2026-02-27T00:00:00Z",
            summary: null,
            tickers: [],
            tickers_hydrated: true,
          },
        ],
        total: 1,
        fetchedCount: 1,
        hasMore: false,
        nextCursor: null,
      })
      .mockResolvedValueOnce({
        items: [
          {
            report_key: "2026/02/2026-02-27.buy.json",
            report_type: "buy",
            report_date: "2026-02-27",
            duplicate_index: 0,
            generated_at: "2026-02-27T00:00:00Z",
            summary: null,
            tickers: [],
            tickers_hydrated: true,
          },
          {
            report_key: "2026/02/2026-02-26.buy.json",
            report_type: "buy",
            report_date: "2026-02-26",
            duplicate_index: 0,
            generated_at: "2026-02-26T00:00:00Z",
            summary: null,
            tickers: [],
            tickers_hydrated: true,
          },
        ],
        total: 2,
        fetchedCount: 2,
        hasMore: false,
        nextCursor: null,
      });
    vi.mocked(downloadStorageJson).mockResolvedValueOnce({
      candidates: [{ ticker: "ETN.NYS", name: "이튼" }],
    });

    const result = await searchTickerDirectory({ q: "이튼", limit: 5 });

    expect(result.results).toEqual([{ ticker: "ETN.NYS", name: "이튼" }]);
    expect(vi.mocked(downloadStorageJson)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(downloadStorageJson)).toHaveBeenCalledWith(
      "reports",
      "2026/02/2026-02-27.buy.json",
    );
    expect(vi.mocked(upsertRuntimeStateEntry)).toHaveBeenCalledTimes(1);
  });
});

describe("listRecentBuyCandidates", () => {
  it("returns first non-empty recent report candidates", async () => {
    vi.mocked(fetchReportIndexPage).mockResolvedValueOnce({
      items: [
        {
          report_key: "2026/02/2026-02-28.buy.json",
          report_type: "buy",
          report_date: "2026-02-28",
          duplicate_index: 0,
          generated_at: "2026-02-28T00:00:00Z",
          summary: null,
          tickers: [],
          tickers_hydrated: true,
        },
        {
          report_key: "2026/02/2026-02-27.buy.json",
          report_type: "buy",
          report_date: "2026-02-27",
          duplicate_index: 0,
          generated_at: "2026-02-27T00:00:00Z",
          summary: null,
          tickers: [],
          tickers_hydrated: true,
        },
      ],
      total: 2,
      fetchedCount: 2,
      hasMore: false,
      nextCursor: null,
    });

    vi.mocked(downloadStorageJson)
      .mockResolvedValueOnce({ candidates: [] })
      .mockResolvedValueOnce({
        candidates: [
          { ticker: "ABBV.NYS", name: "애브비" },
          { ticker: "ETN.NYS", name: "이튼" },
        ],
      });

    const result = await listRecentBuyCandidates({
      limitReports: 10,
      limitCandidates: 10,
    });

    expect(result.report?.key).toBe("2026/02/2026-02-27.buy.json");
    expect(result.candidates).toEqual([
      { ticker: "ABBV.NYS", name: "애브비" },
      { ticker: "ETN.NYS", name: "이튼" },
    ]);
  });
});
