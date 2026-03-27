import { describe, expect, it } from "vitest";

import {
  buildReportDetailRequestPath,
  buildReportsListRequestPath,
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
});
