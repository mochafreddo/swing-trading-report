import { describe, expect, it } from "vitest";

import { resolveReportSearchWindow } from "@/lib/report-search-policy";

describe("resolveReportSearchWindow", () => {
  it("returns default when unset", () => {
    expect(resolveReportSearchWindow(undefined)).toBe(100);
  });

  it("returns parsed value for valid integer string", () => {
    expect(resolveReportSearchWindow("250")).toBe(250);
  });

  it("returns default for non-integer strings", () => {
    expect(resolveReportSearchWindow("25.5")).toBe(100);
    expect(resolveReportSearchWindow("abc")).toBe(100);
  });

  it("returns default for non-positive values", () => {
    expect(resolveReportSearchWindow("0")).toBe(100);
    expect(resolveReportSearchWindow("-3")).toBe(100);
  });

  it("clamps to minimum boundary", () => {
    expect(resolveReportSearchWindow("9")).toBe(10);
  });

  it("clamps to maximum boundary", () => {
    expect(resolveReportSearchWindow("1001")).toBe(1000);
  });
});

