import { describe, expect, it } from "vitest";

import { resolveAiBriefState } from "../ai-brief-state";
import type { ReportJson } from "../types";

describe("resolveAiBriefState", () => {
  it("infers no-signal state from legacy artifacts without candidates", () => {
    const detail: ReportJson = {
      summary: {
        preselected_count: 0,
        recommendation_count: 0,
        source_issue_count: 0,
        system_issue_count: 0,
      },
      eligible_tickers: [],
      recommendations: [],
      source_issues: [],
      system_issues: [],
    };

    expect(resolveAiBriefState(detail)).toEqual({
      state: "NO_SIGNAL",
      reason: "no_enter_candidates",
    });
  });

  it("infers watch-only state when only trigger-pending candidates remain", () => {
    const detail: ReportJson = {
      summary: {
        preselected_count: 0,
        recommendation_count: 0,
        watch_count: 1,
        source_issue_count: 0,
        system_issue_count: 0,
      },
      eligible_tickers: [],
      watch_tickers: ["MSFT.NAS"],
      watch_candidates: [
        {
          ticker: "MSFT.NAS",
          action: "WATCH",
          reason: "entry trigger is pending re-confirmation",
          retrigger_conditions: [
            "price must satisfy the original entry trigger again",
          ],
        },
      ],
      recommendations: [],
      source_issues: [],
      system_issues: [],
    };

    expect(resolveAiBriefState(detail)).toEqual({
      state: "NEEDS_REVIEW_WATCH_ONLY",
      reason: "watch_only_trigger_pending",
    });
  });

  it("keeps matching explicit state when it agrees with inferred state", () => {
    const detail: ReportJson = {
      brief_state: "FINAL_JUDGMENT",
      brief_reason: "source_backed_final",
      summary: {
        preselected_count: 1,
        recommendation_count: 1,
        source_issue_count: 0,
        system_issue_count: 0,
      },
      eligible_tickers: ["AAPL.NAS"],
      recommendations: [
        {
          ticker: "AAPL.NAS",
          sources: [
            { title: "Apple update", url: "https://example.test/aapl" },
          ],
        },
      ],
      source_issues: [],
      system_issues: [],
    };

    expect(resolveAiBriefState(detail)).toEqual({
      state: "FINAL_JUDGMENT",
      reason: "source_backed_final",
    });
  });

  it("falls back to inferred state when explicit state is stale", () => {
    const detail: ReportJson = {
      brief_state: "FINAL_JUDGMENT",
      brief_reason: "source_backed_final",
      summary: {
        preselected_count: 1,
        recommendation_count: 1,
        source_issue_count: 0,
        system_issue_count: 0,
      },
      eligible_tickers: ["AAPL.NAS"],
      recommendations: [{ ticker: "AAPL.NAS", sources: [] }],
      source_issues: [],
      system_issues: [],
    };

    expect(resolveAiBriefState(detail)).toEqual({
      state: "NEEDS_REVIEW_WEAK_NEWS",
      reason: "weak_news_coverage",
    });
  });
});
