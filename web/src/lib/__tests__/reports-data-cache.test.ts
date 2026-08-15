import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/env.server", () => ({
  getSupabaseEnv: vi.fn(() => ({
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_API_KEY: "sb_secret_test_key",
    SUPABASE_REPORTS_BUCKET: "reports",
    REPORT_RETENTION_DAYS: 30,
  })),
}));

vi.mock("@/lib/supabase-admin", () => ({
  SupabaseApiError: class SupabaseApiError extends Error {
    status: number;

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  fetchReportIndexPage: vi.fn(),
  fetchReportIndexEntry: vi.fn(),
  downloadStorageJson: vi.fn(),
}));

import {
  __resetReportsCacheForTests,
  listReports,
  readReportDetail,
} from "@/lib/reports-data";
import {
  downloadStorageJson,
  fetchReportIndexEntry,
  fetchReportIndexPage,
} from "@/lib/supabase-admin";

describe("reports-data cache", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubEnv("SAB_ENABLE_REPORTS_CACHE_IN_TEST", "1");
    __resetReportsCacheForTests();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("caches list results for same query", async () => {
    vi.mocked(fetchReportIndexPage).mockResolvedValue({
      items: [
        {
          bucket_id: "reports",
          report_key: "2026/02/2026-02-14.buy.json",
          report_type: "buy",
          report_date: "2026-02-14",
          duplicate_index: 0,
          generated_at: "2026-02-14T00:00:00Z",
          summary: null,
          tickers: ["AAPL.US"],
          tickers_hydrated: true,
        },
      ],
      total: 1,
      fetchedCount: 1,
      hasMore: false,
      nextCursor: null,
    });

    await listReports({
      type: "buy",
      q: "",
      limit: 30,
      searchWindow: 100,
    });
    await listReports({
      type: "buy",
      q: "",
      limit: 30,
      searchWindow: 100,
    });

    expect(fetchReportIndexPage).toHaveBeenCalledTimes(1);
  });

  it("bypasses list cache when refresh=true", async () => {
    vi.mocked(fetchReportIndexPage).mockResolvedValue({
      items: [],
      total: 0,
      fetchedCount: 0,
      hasMore: false,
      nextCursor: null,
    });

    await listReports({
      type: "buy",
      q: "",
      limit: 30,
      searchWindow: 100,
    });
    await listReports({
      type: "buy",
      q: "",
      limit: 30,
      searchWindow: 100,
      refresh: true,
    });

    expect(fetchReportIndexPage).toHaveBeenCalledTimes(2);
  });

  it("keeps Decision Board run kind in list cache identity", async () => {
    vi.mocked(fetchReportIndexPage).mockResolvedValue({
      items: [],
      total: 0,
      fetchedCount: 0,
      hasMore: false,
      nextCursor: null,
    });

    await listReports({
      type: "decision-board",
      runKind: "ENTRY",
      q: "",
      limit: 30,
      searchWindow: 100,
    });
    await listReports({
      type: "decision-board",
      runKind: "HOLDING",
      q: "",
      limit: 30,
      searchWindow: 100,
    });
    await listReports({
      type: "decision-board",
      runKind: "ENTRY",
      q: "",
      limit: 30,
      searchWindow: 100,
    });

    expect(fetchReportIndexPage).toHaveBeenCalledTimes(2);
    expect(fetchReportIndexPage).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ runKind: "ENTRY" }),
    );
    expect(fetchReportIndexPage).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ runKind: "HOLDING" }),
    );
  });

  it("caches report detail for same key", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValue(null);
    vi.mocked(downloadStorageJson).mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    });

    await readReportDetail("2026/02/2026-02-14.buy.json");
    await readReportDetail("2026/02/2026-02-14.buy.json");

    expect(downloadStorageJson).toHaveBeenCalledTimes(1);
  });

  it("downloads report detail from indexed bucket when available", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValue({
      bucket_id: "custom-reports",
      report_key: "2026/02/2026-02-14.buy.json",
      report_type: "buy",
      report_date: "2026-02-14",
      duplicate_index: 0,
      generated_at: "2026-02-14T00:00:00Z",
      summary: null,
      tickers: ["AAPL.US"],
      tickers_hydrated: true,
    });
    vi.mocked(downloadStorageJson).mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    });

    await readReportDetail("2026/02/2026-02-14.buy.json");

    expect(fetchReportIndexEntry).toHaveBeenCalledWith(
      "2026/02/2026-02-14.buy.json",
      undefined,
    );
    expect(downloadStorageJson).toHaveBeenCalledWith(
      "custom-reports",
      "2026/02/2026-02-14.buy.json",
    );
  });

  it("downloads report detail from an explicit indexed bucket", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValue({
      bucket_id: "custom-reports",
      report_key: "2026/02/2026-02-14.buy.json",
      report_type: "buy",
      report_date: "2026-02-14",
      duplicate_index: 0,
      generated_at: "2026-02-14T00:00:00Z",
      summary: null,
      tickers: ["AAPL.US"],
      tickers_hydrated: true,
    });
    vi.mocked(downloadStorageJson).mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    });

    await readReportDetail("2026/02/2026-02-14.buy.json", {
      bucketId: "custom-reports",
    });

    expect(fetchReportIndexEntry).toHaveBeenCalledWith(
      "2026/02/2026-02-14.buy.json",
      "custom-reports",
    );
    expect(downloadStorageJson).toHaveBeenCalledWith(
      "custom-reports",
      "2026/02/2026-02-14.buy.json",
    );
  });

  it("rejects explicit bucket detail when report index has no matching row", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValue(null);

    await expect(
      readReportDetail("2026/02/2026-02-14.buy.json", {
        bucketId: "private-bucket",
      }),
    ).rejects.toMatchObject({ status: 404 });

    expect(downloadStorageJson).not.toHaveBeenCalled();
  });

  it("accepts AI brief detail keys", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValue(null);
    vi.mocked(downloadStorageJson).mockResolvedValue({
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      recommendations: [{ ticker: "AAPL.NAS" }],
    });

    const detail = await readReportDetail("2026/05/2026-05-05.ai-brief.json");

    expect(detail.key).toBe("2026/05/2026-05-05.ai-brief.json");
    expect(downloadStorageJson).toHaveBeenCalledWith(
      "reports",
      "2026/05/2026-05-05.ai-brief.json",
    );
  });

  it("rejects whitespace-wrapped Decision Board detail keys before network access", async () => {
    const key =
      "2026/08/2026-08-06.decision-board.entry.run-1." +
      `${"a".repeat(64)}.json`;

    await expect(readReportDetail(` ${key} `)).rejects.toMatchObject({
      status: 400,
    });
    expect(fetchReportIndexEntry).not.toHaveBeenCalled();
    expect(downloadStorageJson).not.toHaveBeenCalled();
  });

  it("bypasses detail cache when refresh=true", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValue(null);
    vi.mocked(downloadStorageJson).mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    });

    await readReportDetail("2026/02/2026-02-14.buy.json");
    await readReportDetail("2026/02/2026-02-14.buy.json", { refresh: true });

    expect(downloadStorageJson).toHaveBeenCalledTimes(2);
  });
});
