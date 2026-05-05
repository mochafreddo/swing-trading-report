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
  fetchReportIndexPage: vi.fn(),
  downloadStorageJson: vi.fn(),
}));

import {
  __resetReportsCacheForTests,
  listReports,
  readReportDetail,
} from "@/lib/reports-data";
import {
  downloadStorageJson,
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

  it("caches report detail for same key", async () => {
    vi.mocked(downloadStorageJson).mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    });

    await readReportDetail("2026/02/2026-02-14.buy.json");
    await readReportDetail("2026/02/2026-02-14.buy.json");

    expect(downloadStorageJson).toHaveBeenCalledTimes(1);
  });

  it("accepts AI brief detail keys", async () => {
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

  it("bypasses detail cache when refresh=true", async () => {
    vi.mocked(downloadStorageJson).mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    });

    await readReportDetail("2026/02/2026-02-14.buy.json");
    await readReportDetail("2026/02/2026-02-14.buy.json", { refresh: true });

    expect(downloadStorageJson).toHaveBeenCalledTimes(2);
  });
});
