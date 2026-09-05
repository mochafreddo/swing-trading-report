import { Suspense, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchLatestDecisionBoardReport,
  hasValidAdminSession,
  readReportDetail,
  readDecisionBoardJournalStatus,
} = vi.hoisted(() => ({
  fetchLatestDecisionBoardReport: vi.fn(),
  hasValidAdminSession: vi.fn(),
  readReportDetail: vi.fn(),
  readDecisionBoardJournalStatus: vi.fn(),
}));

vi.mock("@/lib/admin-prefetch", () => ({ hasValidAdminSession }));
vi.mock("@/lib/supabase-admin", () => ({
  fetchLatestDecisionBoardReport,
}));
vi.mock("@/lib/reports-data", () => ({
  InvalidDecisionBoardReportError: class extends Error {},
  readReportDetail,
}));
vi.mock("@/lib/decision-board-journal.server", () => ({
  readDecisionBoardJournalStatus,
}));

import TodayPage, {
  loadTodayDecisionBoard,
  readTodayDogfoodSelection,
} from "@/app/(console)/today/page";

const DIGEST = `sha256:${"a".repeat(64)}`;

function report(runKind: "ENTRY" | "HOLDING") {
  return {
    schema_version: "decision-board.v0",
    run_id: `${runKind.toLowerCase()}-run`,
    created_at: "2026-08-31T00:00:00Z",
    idempotency_key: DIGEST,
    run_kind: runKind,
    status: "PUBLISHED",
    issues: [],
    decision_payload: {
      run_kind: runKind,
      sealed_input_hash: DIGEST,
      items: [],
    },
    decision_payload_hash: DIGEST,
  };
}

describe("TodayPage", () => {
  beforeEach(() => {
    hasValidAdminSession.mockReset();
    fetchLatestDecisionBoardReport.mockReset();
    readReportDetail.mockReset();
    readDecisionBoardJournalStatus.mockReset();
    readDecisionBoardJournalStatus.mockResolvedValue({
      state: "AVAILABLE",
      records: [],
    });
  });

  it("returns a Suspense boundary immediately", () => {
    expect(TodayPage().type).toBe(Suspense);
  });

  it("keeps the memory-only portfolio preview on the Today route", async () => {
    hasValidAdminSession.mockResolvedValue(false);
    const page = TodayPage();
    const content = page.props.children as ReactElement<{
      searchParams: Promise<Record<string, never>>;
    }>;
    const renderContent = content.type as (
      props: typeof content.props,
    ) => Promise<ReactElement>;

    const html = renderToStaticMarkup(await renderContent(content.props));

    expect(html).toContain('id="unclassified-preview-file"');
    expect(html).toContain("NO UPLOAD · NO WRITE · NO ADVICE");
  });

  it("accepts one bounded dogfood query and rejects ambiguous input", () => {
    expect(readTodayDogfoodSelection({ dogfood: "empty-outcome" })).toEqual({
      state: "SELECTED",
      scenarioId: "empty-outcome",
    });
    expect(
      readTodayDogfoodSelection({
        dogfood: ["empty-outcome", "blocked-evidence"],
      }),
    ).toEqual({ state: "INVALID" });
    expect(readTodayDogfoodSelection({ dogfood: "../private" })).toEqual({
      state: "INVALID",
    });
    expect(readTodayDogfoodSelection({})).toEqual({ state: "DEFAULT" });
    expect(readTodayDogfoodSelection({ dogfood: "invalid-contract" })).toEqual({
      state: "INVALID_FIXTURE",
    });
  });

  it("does not query report storage without a valid admin session", async () => {
    hasValidAdminSession.mockResolvedValue(false);

    await expect(loadTodayDecisionBoard()).resolves.toEqual({
      lanes: [
        { runKind: "ENTRY", state: "UNAVAILABLE" },
        { runKind: "HOLDING", state: "UNAVAILABLE" },
      ],
      journalStatus: {
        state: "UNAVAILABLE",
        reason: "UNSAFE_OR_INVALID",
        records: [],
      },
    });
    expect(fetchLatestDecisionBoardReport).not.toHaveBeenCalled();
    expect(readReportDetail).not.toHaveBeenCalled();
  });

  it("loads and verifies both public lanes", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    fetchLatestDecisionBoardReport.mockImplementation(
      async (runKind: "ENTRY" | "HOLDING") => ({
        report_key: `${runKind.toLowerCase()}-key`,
        bucket_id: "reports",
      }),
    );
    readReportDetail.mockImplementation(async (key: string) => {
      const runKind = key.startsWith("entry") ? "ENTRY" : "HOLDING";
      return { key, bucketId: "reports", report: report(runKind) };
    });

    const result = await loadTodayDecisionBoard();

    expect(fetchLatestDecisionBoardReport).toHaveBeenCalledTimes(2);
    expect(fetchLatestDecisionBoardReport).toHaveBeenCalledWith("ENTRY");
    expect(fetchLatestDecisionBoardReport).toHaveBeenCalledWith("HOLDING");
    expect(readReportDetail).toHaveBeenCalledWith("entry-key", {
      bucketId: "reports",
    });
    expect(readReportDetail).toHaveBeenCalledWith("holding-key", {
      bucketId: "reports",
    });
    expect(result.lanes.map((lane) => lane.state)).toEqual([
      "PUBLISHED",
      "PUBLISHED",
    ]);
    expect(readDecisionBoardJournalStatus).toHaveBeenCalledOnce();
  });

  it("fails one lane closed without hiding the other lane", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    fetchLatestDecisionBoardReport.mockImplementation(
      async (runKind: "ENTRY" | "HOLDING") =>
        runKind === "ENTRY"
          ? null
          : { report_key: "holding-key", bucket_id: "reports" },
    );
    readReportDetail.mockResolvedValue({
      key: "holding-key",
      bucketId: "reports",
      report: report("HOLDING"),
    });

    await expect(loadTodayDecisionBoard()).resolves.toMatchObject({
      lanes: [
        { runKind: "ENTRY", state: "MISSING" },
        { runKind: "HOLDING", state: "PUBLISHED" },
      ],
    });
  });

  it("labels a malformed public projection INVALID", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    fetchLatestDecisionBoardReport.mockImplementation(
      async (runKind: "ENTRY" | "HOLDING") =>
        runKind === "ENTRY"
          ? { report_key: "entry-key", bucket_id: "reports" }
          : null,
    );
    readReportDetail.mockResolvedValue({
      key: "entry-key",
      bucketId: "reports",
      report: { schema_version: "decision-board.v0", status: "PUBLISHED" },
    });

    await expect(loadTodayDecisionBoard()).resolves.toMatchObject({
      lanes: [
        { runKind: "ENTRY", state: "INVALID" },
        { runKind: "HOLDING", state: "MISSING" },
      ],
    });
  });

  it("keeps verified lanes when journal observability fails", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    fetchLatestDecisionBoardReport.mockResolvedValue(null);
    readDecisionBoardJournalStatus.mockRejectedValue(new Error("unavailable"));

    await expect(loadTodayDecisionBoard()).resolves.toMatchObject({
      lanes: [{ state: "MISSING" }, { state: "MISSING" }],
      journalStatus: { state: "UNAVAILABLE", records: [] },
    });
  });
});
