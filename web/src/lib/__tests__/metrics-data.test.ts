import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase-admin", () => ({
  fetchReportIndexPage: vi.fn(),
}));

import {
  buildMetricsPanel,
  loadMetricsDashboardData,
} from "@/lib/metrics-data";
import { fetchReportIndexPage } from "@/lib/supabase-admin";

describe("metrics-data", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("normalizes missing summary metrics as null instead of zero", () => {
    const panel = buildMetricsPanel("buy", [
      {
        report_key: "2026/03/2026-03-28.buy.json",
        report_type: "buy",
        report_date: "2026-03-28",
        duplicate_index: 0,
        generated_at: "2026-03-28 21:00 KST",
        summary: {
          candidate_count: 5,
          system_issue_count: 1,
        },
        tickers: ["AAPL.NAS"],
        tickers_hydrated: true,
      },
      {
        report_key: "2026/03/2026-03-27.buy.json",
        report_type: "buy",
        report_date: "2026-03-27",
        duplicate_index: 0,
        generated_at: "2026-03-27 21:00 KST",
        summary: {
          candidate_count: 3,
          data_coverage_ratio: 0.8,
          provider_fallback_ratio: 0.25,
          rs_benchmark_unavailable_ratio: 0.5,
          system_issue_count: 0,
        },
        tickers: ["MSFT.NAS"],
        tickers_hydrated: true,
      },
    ]);

    const coverageMetric = panel.metrics.find(
      (metric) => metric.key === "data_coverage_ratio",
    );
    const candidateMetric = panel.metrics.find(
      (metric) => metric.key === "candidate_count",
    );

    expect(panel.latestReportHref).toBe(
      "/reports?type=buy&key=2026%2F03%2F2026-03-28.buy.json",
    );
    expect(coverageMetric?.latest).toBeNull();
    expect(coverageMetric?.average).toBe(0.8);
    expect(candidateMetric?.latest).toBe(5);
    expect(candidateMetric?.average).toBe(4);
  });

  it("keeps partial panel failures isolated", async () => {
    const fetchMock = vi.mocked(fetchReportIndexPage);
    fetchMock.mockImplementation(async (options) => {
      const type = options?.type ?? "all";
      if (type === "sell") {
        throw new Error("sell index unavailable");
      }
      if (type === "all") {
        throw new Error("type must be specified in metrics tests");
      }
      return {
        items: [
          {
            report_key: `2026/03/2026-03-28.${type}.json`,
            report_type: type,
            report_date: "2026-03-28",
            duplicate_index: 0,
            generated_at: "2026-03-28 21:00 KST",
            summary:
              type === "entry"
                ? { entry_count: 1, system_issue_count: 0 }
                : { candidate_count: 1, system_issue_count: 0 },
            tickers: ["AAPL.NAS"],
            tickers_hydrated: true,
          },
        ],
        total: 1,
        fetchedCount: 1,
        hasMore: false,
        nextCursor: null,
      };
    });

    const data = await loadMetricsDashboardData();

    expect(data.buy.error).toBeNull();
    expect(data.buy.panel?.title).toBe("Scan Health");
    expect(data.sell.panel).toBeNull();
    expect(data.sell.error).toContain("sell index unavailable");
    expect(data.entry.error).toBeNull();
    expect(data.entry.panel?.title).toBe("Entry Health");
  });
});
