import { Suspense } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const {
  hasValidAdminSession,
  listReports,
  readReportDetail,
  resolveReportSearchWindow,
} = vi.hoisted(() => ({
  hasValidAdminSession: vi.fn(),
  listReports: vi.fn(),
  readReportDetail: vi.fn(),
  resolveReportSearchWindow: vi.fn(() => 100),
}));

vi.mock("@/components/reports-client", () => ({
  ReportsClient: ({ initialState }: { initialState?: unknown }) => (
    <div data-state={initialState ? "ready" : "empty"} />
  ),
}));

vi.mock("@/components/reports/helpers", () => ({
  parseReportType: (value: string | null) => value ?? "all",
}));

vi.mock("@/lib/admin-prefetch", () => ({
  hasValidAdminSession,
}));

vi.mock("@/lib/reports-data", () => ({
  listReports,
  readReportDetail,
}));

vi.mock("@/lib/report-search-policy", () => ({
  resolveReportSearchWindow,
}));

import ReportsPage, {
  loadReportsInitialState,
} from "@/app/(console)/reports/page";

describe("ReportsPage", () => {
  beforeEach(() => {
    hasValidAdminSession.mockReset();
    listReports.mockReset();
    readReportDetail.mockReset();
    resolveReportSearchWindow.mockClear();
    resolveReportSearchWindow.mockReturnValue(100);
  });

  it("returns a Suspense boundary immediately", () => {
    const element = ReportsPage({
      searchParams: Promise.resolve({}),
    });

    expect(element.type).toBe(Suspense);
  });

  it("does not load reports when the admin session is invalid", async () => {
    hasValidAdminSession.mockResolvedValue(false);

    await expect(
      loadReportsInitialState(Promise.resolve({ q: "AAPL" })),
    ).resolves.toBeUndefined();
    expect(listReports).not.toHaveBeenCalled();
    expect(readReportDetail).not.toHaveBeenCalled();
  });

  it("rethrows list loading failures instead of swallowing them", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockRejectedValueOnce(new Error("reports unavailable"));

    await expect(loadReportsInitialState(Promise.resolve({}))).rejects.toThrow(
      "reports unavailable",
    );
  });

  it("keeps rendering when the initial detail prefetch fails", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockResolvedValueOnce({
      items: [{ key: "report-1" }],
      total: 1,
      searched: 1,
      truncated: false,
      searchWindow: 100,
      warnings: [],
    });
    readReportDetail.mockRejectedValueOnce(new Error("detail unavailable"));

    await expect(loadReportsInitialState(Promise.resolve({}))).resolves.toEqual(
      {
        reportType: "all",
        query: "",
        appliedQuery: "",
        items: [{ key: "report-1" }],
        total: 1,
        searched: 1,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: "report-1",
        detail: null,
        detailKey: null,
        showRaw: false,
      },
    );
  });

  it("prefetches a requested report key even when it is outside the current list", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockResolvedValueOnce({
      items: [{ key: "2026/02/2026-02-28.buy.json" }],
      total: 1,
      searched: 1,
      truncated: false,
      searchWindow: 100,
      warnings: [],
    });
    readReportDetail.mockResolvedValueOnce({
      key: "2026/01/2026-01-31.buy.json",
      report: { type: "buy" },
    });

    await expect(
      loadReportsInitialState(
        Promise.resolve({ key: "2026/01/2026-01-31.buy.json" }),
      ),
    ).resolves.toMatchObject({
      selectedKey: "2026/01/2026-01-31.buy.json",
      detailKey: "2026/01/2026-01-31.buy.json",
      detail: { type: "buy" },
    });
    expect(readReportDetail).toHaveBeenCalledWith(
      "2026/01/2026-01-31.buy.json",
    );
  });
});
