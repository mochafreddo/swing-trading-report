import { Suspense } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const {
  hasValidAdminSession,
  listReports,
  readReportDetail,
  resolveReportSearchWindow,
  readDecisionBoardJournalStatus,
} = vi.hoisted(() => ({
  hasValidAdminSession: vi.fn(),
  listReports: vi.fn(),
  readReportDetail: vi.fn(),
  resolveReportSearchWindow: vi.fn(() => 100),
  readDecisionBoardJournalStatus: vi.fn(async () => ({
    state: "UNAVAILABLE",
    reason: "NOT_CONFIGURED",
    records: [],
  })),
}));

vi.mock("@/components/reports-client", () => ({
  ReportsClient: ({ initialState }: { initialState?: unknown }) => (
    <div data-state={initialState ? "ready" : "empty"} />
  ),
}));

vi.mock("@/components/reports/helpers", () => ({
  parseReportType: (value: string | null) => value ?? "all",
  parseDecisionBoardRunKind: (value: string | null) =>
    value === "HOLDING" ? "HOLDING" : "ENTRY",
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

vi.mock("@/lib/decision-board-journal.server", () => ({
  readDecisionBoardJournalStatus,
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
    readDecisionBoardJournalStatus.mockClear();
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
      items: [{ key: "report-1", bucketId: "reports" }],
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
        runKind: null,
        query: "",
        appliedQuery: "",
        items: [{ key: "report-1", bucketId: "reports" }],
        total: 1,
        searched: 1,
        truncated: false,
        searchWindow: 100,
        warnings: [],
        selectedKey: "report-1",
        selectedBucketId: "reports",
        detail: null,
        detailKey: null,
        detailBucketId: null,
        showRaw: false,
        journalStatus: {
          state: "UNAVAILABLE",
          reason: "NOT_CONFIGURED",
          records: [],
        },
      },
    );
  });

  it("prefetches the exact Decision Board lane from the URL", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockResolvedValueOnce({
      items: [],
      total: 0,
      searched: 0,
      truncated: false,
      searchWindow: 100,
      warnings: [],
    });

    const state = await loadReportsInitialState(
      Promise.resolve({ type: "decision-board", runKind: "HOLDING" }),
    );

    expect(listReports).toHaveBeenCalledWith({
      type: "decision-board",
      runKind: "HOLDING",
      q: "",
      limit: 30,
      searchWindow: 100,
    });
    expect(state).toMatchObject({
      reportType: "decision-board",
      runKind: "HOLDING",
    });
  });

  it("does not prefetch a Decision Board key from the wrong lane", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockResolvedValueOnce({
      items: [],
      total: 0,
      searched: 0,
      truncated: false,
      searchWindow: 100,
      warnings: [],
    });
    const wrongLaneKey =
      "2026/08/2026-08-06.decision-board.holding.holding-slot-001." +
      `${"f".repeat(64)}.json`;

    const state = await loadReportsInitialState(
      Promise.resolve({
        type: "decision-board",
        runKind: "ENTRY",
        key: wrongLaneKey,
      }),
    );

    expect(state).toMatchObject({ selectedKey: null, detail: null });
    expect(readReportDetail).not.toHaveBeenCalled();
  });

  it("prefetches a requested report key even when it is outside the current list", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockResolvedValueOnce({
      items: [
        {
          key: "2026/02/2026-02-28.buy.json",
          bucketId: "reports",
        },
      ],
      total: 1,
      searched: 1,
      truncated: false,
      searchWindow: 100,
      warnings: [],
    });
    readReportDetail.mockResolvedValueOnce({
      key: "2026/01/2026-01-31.buy.json",
      bucketId: "custom-reports",
      report: { type: "buy" },
    });

    await expect(
      loadReportsInitialState(
        Promise.resolve({ key: "2026/01/2026-01-31.buy.json" }),
      ),
    ).resolves.toMatchObject({
      selectedKey: "2026/01/2026-01-31.buy.json",
      selectedBucketId: null,
      detailKey: "2026/01/2026-01-31.buy.json",
      detailBucketId: "custom-reports",
      detail: { type: "buy" },
    });
    expect(readReportDetail).toHaveBeenCalledWith(
      "2026/01/2026-01-31.buy.json",
      { bucketId: undefined },
    );
  });

  it("does not choose an arbitrary bucket for key-only deep links", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    listReports.mockResolvedValueOnce({
      items: [
        {
          key: "2026/02/2026-02-28.buy.json",
          bucketId: "custom-reports",
        },
        {
          key: "2026/02/2026-02-28.buy.json",
          bucketId: "reports",
        },
      ],
      total: 2,
      searched: 0,
      truncated: false,
      searchWindow: 100,
      warnings: [],
    });
    readReportDetail.mockRejectedValueOnce(new Error("ambiguous"));

    const state = await loadReportsInitialState(
      Promise.resolve({ key: "2026/02/2026-02-28.buy.json" }),
    );

    expect(state).toMatchObject({
      selectedKey: "2026/02/2026-02-28.buy.json",
      selectedBucketId: null,
      detail: null,
      detailKey: null,
      detailBucketId: null,
    });
    expect(readReportDetail).toHaveBeenCalledWith(
      "2026/02/2026-02-28.buy.json",
      { bucketId: undefined },
    );
  });
});
