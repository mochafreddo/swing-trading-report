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

function buyReportRow(reportKey: string, reportDate: string) {
  return {
    report_key: reportKey,
    report_type: "buy" as const,
    report_date: reportDate,
    duplicate_index: 0,
    generated_at: `${reportDate}T00:00:00Z`,
    summary: null,
    tickers: [],
    tickers_hydrated: true,
  };
}

function reportIndexPage(items: ReturnType<typeof buyReportRow>[]) {
  return {
    items,
    total: items.length,
    fetchedCount: items.length,
    hasMore: false,
    nextCursor: null,
  };
}

function cachedTickerEntry({
  ticker = "ABBV.NYS",
  name = "애브비",
  reportDate,
  reportKey,
  updatedAtMs = Date.now() - 1000,
}: {
  ticker?: string;
  name?: string;
  reportDate: string;
  reportKey: string;
  updatedAtMs?: number;
}) {
  return {
    ticker,
    name,
    aliases: [ticker, ticker.split(".")[0] ?? ticker, name],
    lastSeenReportDate: reportDate,
    lastSeenReportKey: reportKey,
    updatedAtMs,
  };
}

function cachedDirectoryState({
  builtAtMs = Date.now(),
  buyReportKeys,
  entries,
}: {
  builtAtMs?: number;
  buyReportKeys: string[];
  entries: ReturnType<typeof cachedTickerEntry>[];
}) {
  return {
    state_key: "ticker_directory:v1",
    expires_at: "2099-01-01T00:00:00.000Z",
    state_payload: {
      version: 1,
      builtAtMs,
      source: {
        buyReportsScanned: buyReportKeys.length,
        buyReportKeys,
      },
      entries,
    },
  };
}

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
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      )
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      );

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
    vi.mocked(fetchRuntimeStateEntry).mockResolvedValueOnce(
      cachedDirectoryState({
        buyReportKeys: ["2026/02/2026-02-26.buy.json"],
        entries: [
          cachedTickerEntry({
            reportDate: "2026-02-26",
            reportKey: "2026/02/2026-02-26.buy.json",
          }),
        ],
      }),
    );
    vi.mocked(fetchReportIndexPage)
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      )
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
          buyReportRow("2026/02/2026-02-26.buy.json", "2026-02-26"),
        ]),
      );
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

  it("drops cached entries whose reports are outside the current source window", async () => {
    vi.mocked(fetchRuntimeStateEntry).mockResolvedValueOnce(
      cachedDirectoryState({
        builtAtMs: Date.now() - 25 * 60 * 60 * 1000,
        buyReportKeys: ["2026/02/2026-02-25.buy.json"],
        entries: [
          cachedTickerEntry({
            reportDate: "2026-02-25",
            reportKey: "2026/02/2026-02-25.buy.json",
            updatedAtMs: Date.now() - 25 * 60 * 60 * 1000,
          }),
        ],
      }),
    );
    vi.mocked(fetchReportIndexPage)
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      )
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      );
    vi.mocked(downloadStorageJson).mockResolvedValueOnce({
      candidates: [{ ticker: "ETN.NYS", name: "이튼" }],
    });

    const result = await searchTickerDirectory({ q: "ABBV", limit: 5 });

    expect(result.results).toEqual([]);
    expect(vi.mocked(upsertRuntimeStateEntry)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(upsertRuntimeStateEntry)).toHaveBeenCalledWith(
      "ticker_directory:v1",
      expect.objectContaining({
        entries: [
          expect.objectContaining({
            ticker: "ETN.NYS",
            lastSeenReportKey: "2026/02/2026-02-27.buy.json",
          }),
        ],
      }),
      expect.any(String),
    );
  });

  it("does not mark failed report downloads as scanned during refresh", async () => {
    vi.mocked(fetchRuntimeStateEntry).mockResolvedValueOnce(
      cachedDirectoryState({
        builtAtMs: Date.now() - 25 * 60 * 60 * 1000,
        buyReportKeys: ["2026/02/2026-02-26.buy.json"],
        entries: [
          cachedTickerEntry({
            reportDate: "2026-02-26",
            reportKey: "2026/02/2026-02-26.buy.json",
            updatedAtMs: Date.now() - 25 * 60 * 60 * 1000,
          }),
        ],
      }),
    );
    vi.mocked(fetchReportIndexPage)
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      )
      .mockResolvedValueOnce(
        reportIndexPage([
          buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
        ]),
      );
    vi.mocked(downloadStorageJson).mockRejectedValueOnce(
      new Error("storage unavailable"),
    );

    const result = await searchTickerDirectory({ q: "ETN", limit: 5 });

    expect(result.results).toEqual([]);
    expect(vi.mocked(upsertRuntimeStateEntry)).toHaveBeenCalledWith(
      "ticker_directory:v1",
      expect.objectContaining({
        source: {
          buyReportsScanned: 0,
          buyReportKeys: [],
        },
      }),
      expect.any(String),
    );
  });
});

describe("listRecentBuyCandidates", () => {
  it("returns first non-empty recent report candidates", async () => {
    vi.mocked(fetchReportIndexPage).mockResolvedValueOnce(
      reportIndexPage([
        buyReportRow("2026/02/2026-02-28.buy.json", "2026-02-28"),
        buyReportRow("2026/02/2026-02-27.buy.json", "2026-02-27"),
      ]),
    );

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
