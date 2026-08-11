import { describe, expect, it } from "vitest";

import {
  buildReportDetailRequestPath,
  buildReportsListRequestPath,
  buildReportsStateQueryString,
  parseDecisionBoardJournalStatusPayload,
} from "@/components/reports/use-reports-state";

describe("reports request path builders", () => {
  it("builds list path without refresh by default", () => {
    const path = buildReportsListRequestPath({
      type: "buy",
      limit: 30,
      query: "AAPL",
    });

    expect(path).toBe("/api/reports?type=buy&limit=30&q=AAPL");
  });

  it("adds refresh=1 to list path when requested", () => {
    const path = buildReportsListRequestPath({
      type: "sell",
      limit: 30,
      query: "",
      refresh: true,
    });

    expect(path).toBe("/api/reports?type=sell&limit=30&refresh=1");
  });

  it("builds entry list path", () => {
    const path = buildReportsListRequestPath({
      type: "entry",
      limit: 30,
      query: "",
    });

    expect(path).toBe("/api/reports?type=entry&limit=30");
  });

  it("builds AI brief list path", () => {
    const path = buildReportsListRequestPath({
      type: "ai-brief",
      limit: 30,
      query: "",
    });

    expect(path).toBe("/api/reports?type=ai-brief&limit=30");
  });

  it("keeps Decision Board run kind in list request identity", () => {
    const path = buildReportsListRequestPath({
      type: "decision-board",
      runKind: "HOLDING",
      limit: 30,
      query: "",
    });

    expect(path).toBe(
      "/api/reports?type=decision-board&limit=30&runKind=HOLDING",
    );
  });

  it("keeps Decision Board run kind in browser URL identity", () => {
    expect(
      buildReportsStateQueryString({
        reportType: "decision-board",
        runKind: "ENTRY",
        appliedQuery: "",
        selectedKey: null,
        selectedBucketId: null,
        showRaw: false,
      }),
    ).toBe("type=decision-board&runKind=ENTRY");
  });

  it("builds detail path without refresh by default", () => {
    const path = buildReportDetailRequestPath({
      key: "2026/02/2026-02-14.buy.json",
    });

    expect(path).toBe(
      "/api/reports/detail?key=2026%2F02%2F2026-02-14.buy.json",
    );
  });

  it("adds refresh=1 to detail path when requested", () => {
    const path = buildReportDetailRequestPath({
      key: "2026/02/2026-02-14.buy.json",
      refresh: true,
    });

    expect(path).toBe(
      "/api/reports/detail?key=2026%2F02%2F2026-02-14.buy.json&refresh=1",
    );
  });

  it("adds bucket to detail path when requested", () => {
    const path = buildReportDetailRequestPath({
      key: "2026/02/2026-02-14.buy.json",
      bucketId: "custom-reports",
    });

    expect(path).toBe(
      "/api/reports/detail?key=2026%2F02%2F2026-02-14.buy.json&bucket=custom-reports",
    );
  });

  it("rejects malformed or non-warning local journal payloads", () => {
    expect(
      parseDecisionBoardJournalStatusPayload({
        state: "AVAILABLE",
        records: [{ status: "STARTED" }],
      }),
    ).toBeNull();
    expect(
      parseDecisionBoardJournalStatusPayload({
        state: "UNAVAILABLE",
        reason: "PRIVATE_PATH",
        records: [],
      }),
    ).toBeNull();
  });
});
