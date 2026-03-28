import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a className={className} href={href}>
      {children}
    </a>
  ),
}));

import { MetricsDashboard } from "@/components/metrics-dashboard";
import type { MetricsDashboardData } from "@/lib/metrics-data";

describe("MetricsDashboard component", () => {
  it("renders metrics panels with N/A formatting and drill-down links", () => {
    const initialState: MetricsDashboardData = {
      buy: {
        error: null,
        panel: {
          type: "buy",
          title: "Scan Health",
          description: "scan desc",
          reportCount: 2,
          latestReportKey: "2026/03/2026-03-28.buy.json",
          latestGeneratedAt: "2026-03-28 21:00 KST",
          latestReportHref:
            "/reports?type=buy&key=2026%2F03%2F2026-03-28.buy.json",
          browseHref: "/reports?type=buy",
          metrics: [
            {
              key: "data_coverage_ratio",
              label: "Coverage",
              presentation: "ratio",
              latest: null,
              average: 0.82,
              series: [
                {
                  key: "2026/03/2026-03-27.buy.json",
                  label: "2026-03-27",
                  value: 0.82,
                },
                {
                  key: "2026/03/2026-03-28.buy.json",
                  label: "2026-03-28",
                  value: null,
                },
              ],
            },
          ],
        },
      },
      entry: {
        error: "entry metrics unavailable",
        panel: null,
      },
      sell: {
        error: null,
        panel: {
          type: "sell",
          title: "Sell Health",
          description: "sell desc",
          reportCount: 1,
          latestReportKey: "2026/03/2026-03-28.sell.json",
          latestGeneratedAt: "2026-03-28 21:05 KST",
          latestReportHref:
            "/reports?type=sell&key=2026%2F03%2F2026-03-28.sell.json",
          browseHref: "/reports?type=sell",
          metrics: [
            {
              key: "issue_count",
              label: "Issues",
              presentation: "count",
              latest: 2,
              average: 1.5,
              series: [
                {
                  key: "2026/03/2026-03-28.sell.json",
                  label: "2026-03-28",
                  value: 2,
                },
              ],
            },
          ],
        },
      },
    };

    const html = renderToStaticMarkup(
      createElement(MetricsDashboard, { initialState }),
    );

    expect(html).toContain("Run quality, not just run success.");
    expect(html).toContain("Scan Health");
    expect(html).toContain("Coverage");
    expect(html).toContain("N/A");
    expect(html).toContain("Avg 82.0%");
    expect(html).toContain(
      'href="/reports?type=buy&amp;key=2026%2F03%2F2026-03-28.buy.json"',
    );
    expect(html).toContain("entry metrics unavailable");
    expect(html).toContain("Browse entry reports");
  });
});
