import { describe, expect, it } from "vitest";

import { asIssueArray, formatSources } from "../report-detail-formatters";

describe("report detail formatters", () => {
  it("formats structured issues with ticker, severity, code, and message", () => {
    expect(
      asIssueArray([
        " plain issue ",
        "",
        {
          ticker: "AAPL.NAS",
          severity: "WARN",
          code: "source_missing",
          message: "No source was available.",
        },
        {
          severity: "ERROR",
          code: "provider_failed",
        },
        null,
      ]),
    ).toEqual([
      "plain issue",
      "AAPL.NAS WARN source_missing: No source was available.",
      "ERROR provider_failed",
    ]);
  });

  it("formats recommendation sources without changing legacy separators", () => {
    expect(
      formatSources([
        {
          title: "Apple supply chain update",
          url: "https://example.test/aapl",
        },
        { title: "Only title" },
        { url: "https://example.test/url-only" },
        {},
        "invalid",
      ]),
    ).toBe(
      "Apple supply chain update (https://example.test/aapl) · Only title · https://example.test/url-only",
    );
  });

  it("uses the legacy dash fallback when no source text is available", () => {
    expect(formatSources([])).toBe("-");
    expect(formatSources(null)).toBe("-");
  });
});
