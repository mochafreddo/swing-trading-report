import { describe, expect, it } from "vitest";

import { formatSummaryKeyForDisplay } from "@/lib/report-summary-label";

describe("formatSummaryKeyForDisplay", () => {
  it("adds soft break opportunities for snake_case keys", () => {
    const formatted = formatSummaryKeyForDisplay("system_issue_count");

    expect(formatted).toContain("\u200B");
    expect(formatted.replaceAll("\u200B", "")).toBe("system_issue_count");
  });
});
