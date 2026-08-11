import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ReportsList } from "@/components/reports/reports-list";

describe("ReportsList component", () => {
  it("renders manual refresh button", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "all",
        runKind: null,
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        selectedBucketId: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
        onRunKindChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain("새로고침");
  });

  it("shows refreshing label and disabled state", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "all",
        runKind: null,
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        selectedBucketId: null,
        loadingList: false,
        refreshing: true,
        onReportTypeChange: vi.fn(),
        onRunKindChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain("새로고침 중…");
    expect(html).toContain("disabled");
  });

  it("renders entry filter option", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "entry",
        runKind: null,
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        selectedBucketId: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
        onRunKindChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain(">Entry</option>");
  });

  it("renders AI Brief filter option", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "ai-brief",
        runKind: null,
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        selectedBucketId: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
        onRunKindChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain(">AI Brief</option>");
  });

  it("renders Sell AI Brief filter option", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "sell-ai-brief",
        runKind: null,
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        selectedBucketId: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
        onRunKindChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain(">Sell AI Brief</option>");
  });

  it("renders Decision Board lane and public run identity", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "decision-board",
        runKind: "ENTRY",
        query: "",
        appliedQuery: "",
        items: [
          {
            key: `2026/08/2026-08-06.decision-board.entry.entry-slot-001.${"e".repeat(64)}.json`,
            bucketId: "reports",
            type: "decision-board",
            reportDate: "2026-08-06",
            duplicateIndex: 0,
            runKind: "ENTRY",
            runId: "entry-slot-001",
          },
        ],
        total: 1,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        selectedBucketId: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
        onRunKindChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain(">Decision Board</option>");
    expect(html).toContain('name="runKind"');
    expect(html).toContain("ENTRY");
    expect(html).toContain("entry-slot-001");
  });
});
