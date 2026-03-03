import { describe, expect, it } from "vitest";

import {
  filterAndSortReportKeys,
  parseReportStorageKey,
} from "@/lib/report-key";

describe("parseReportStorageKey", () => {
  it("parses valid buy/sell keys", () => {
    const parsed = parseReportStorageKey("2026/02/2026-02-14-2.sell.json");
    expect(parsed).not.toBeNull();
    expect(parsed?.type).toBe("sell");
    expect(parsed?.reportDate).toBe("2026-02-14");
    expect(parsed?.duplicateIndex).toBe(2);
  });

  it("rejects invalid keys", () => {
    expect(parseReportStorageKey("reports/2026-02-14.buy.json")).toBeNull();
    expect(parseReportStorageKey("2026/02/2026-02-14.entry.json")).toBeNull();
  });

  it("rejects impossible calendar dates", () => {
    expect(parseReportStorageKey("2026/02/2026-02-31.buy.json")).toBeNull();
    expect(parseReportStorageKey("2026/13/2026-13-01.sell.json")).toBeNull();
  });

  it("rejects path/date mismatch", () => {
    expect(parseReportStorageKey("2026/03/2026-02-14.buy.json")).toBeNull();
    expect(parseReportStorageKey("2025/02/2026-02-14.sell.json")).toBeNull();
  });
});

describe("filterAndSortReportKeys", () => {
  it("sorts newest first and filters by type", () => {
    const result = filterAndSortReportKeys(
      [
        "2026/02/2026-02-14.buy.json",
        "2026/02/2026-02-14-1.buy.json",
        "2026/02/2026-02-10.sell.json",
        "2026/02/2026-02-14-2.buy.json",
      ],
      "buy",
    );

    expect(result.map((entry) => entry.key)).toEqual([
      "2026/02/2026-02-14-2.buy.json",
      "2026/02/2026-02-14-1.buy.json",
      "2026/02/2026-02-14.buy.json",
    ]);
  });
});
