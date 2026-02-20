import { describe, expect, it } from "vitest";

import {
  resolveReportKeysCacheTtlSeconds,
  resolveReportSearchConcurrency,
} from "@/lib/report-performance-policy";

describe("resolveReportKeysCacheTtlSeconds", () => {
  it("returns default for empty or invalid inputs", () => {
    expect(resolveReportKeysCacheTtlSeconds(undefined)).toBe(30);
    expect(resolveReportKeysCacheTtlSeconds("")).toBe(30);
    expect(resolveReportKeysCacheTtlSeconds("abc")).toBe(30);
    expect(resolveReportKeysCacheTtlSeconds("-1")).toBe(30);
    expect(resolveReportKeysCacheTtlSeconds("1.5")).toBe(30);
  });

  it("supports zero to disable cache", () => {
    expect(resolveReportKeysCacheTtlSeconds("0")).toBe(0);
  });

  it("clamps TTL to configured bounds", () => {
    expect(resolveReportKeysCacheTtlSeconds("15")).toBe(15);
    expect(resolveReportKeysCacheTtlSeconds("99999")).toBe(600);
  });
});

describe("resolveReportSearchConcurrency", () => {
  it("returns default for empty or invalid inputs", () => {
    expect(resolveReportSearchConcurrency(undefined)).toBe(8);
    expect(resolveReportSearchConcurrency("")).toBe(8);
    expect(resolveReportSearchConcurrency("abc")).toBe(8);
    expect(resolveReportSearchConcurrency("-2")).toBe(8);
    expect(resolveReportSearchConcurrency("3.5")).toBe(8);
  });

  it("clamps concurrency to configured bounds", () => {
    expect(resolveReportSearchConcurrency("0")).toBe(1);
    expect(resolveReportSearchConcurrency("4")).toBe(4);
    expect(resolveReportSearchConcurrency("99")).toBe(16);
  });
});
