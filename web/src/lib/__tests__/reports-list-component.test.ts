import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ReportsList } from "@/components/reports/reports-list";

describe("ReportsList component", () => {
  it("renders manual refresh button", () => {
    const html = renderToStaticMarkup(
      ReportsList({
        reportType: "all",
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
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
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        loadingList: false,
        refreshing: true,
        onReportTypeChange: vi.fn(),
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
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
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
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
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
        query: "",
        appliedQuery: "",
        items: [],
        total: null,
        searched: 0,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: null,
        loadingList: false,
        refreshing: false,
        onReportTypeChange: vi.fn(),
        onQueryChange: vi.fn(),
        onSelectKey: vi.fn(),
        onRefresh: vi.fn(),
      }),
    );

    expect(html).toContain(">Sell AI Brief</option>");
  });
});
