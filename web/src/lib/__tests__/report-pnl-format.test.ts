import { describe, expect, it } from "vitest";

import { formatPnlPercent } from "@/components/reports/helpers";

describe("formatPnlPercent", () => {
  it("formats positive pnl ratio as signed percent", () => {
    expect(formatPnlPercent(0.053)).toBe("+5.3%");
  });

  it("formats negative pnl ratio as percent", () => {
    expect(formatPnlPercent(-0.034)).toBe("-3.4%");
  });

  it("formats zero pnl ratio as zero percent", () => {
    expect(formatPnlPercent(0)).toBe("0.0%");
  });

  it("returns placeholder for invalid values", () => {
    expect(formatPnlPercent(null)).toBe("-");
    expect(formatPnlPercent("0.1")).toBe("-");
  });
});
