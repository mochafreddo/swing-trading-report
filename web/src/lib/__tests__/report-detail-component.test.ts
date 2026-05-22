import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ReportDetail } from "@/components/reports/report-detail";
import type { ReportJson } from "@/components/reports/types";

function renderReportDetail(
  detail: ReportJson,
  aiBriefRows: ReportJson[] = [],
): string {
  return renderToStaticMarkup(
    createElement(ReportDetail, {
      detail,
      loadingDetail: false,
      error: null,
      showRaw: false,
      summary: detail.summary as ReportJson,
      buyRows: [],
      sellRows: [],
      entryRows: [],
      aiBriefRows,
      rawDetailJson: "",
      onToggleRaw: vi.fn(),
    }),
  );
}

describe("ReportDetail component", () => {
  it("renders candidate reason/risk columns and issues section", () => {
    const detail: ReportJson = {
      schema: "sab.report.v1",
      type: "buy",
      generated_at: "2026-02-11 21:03 KST",
      provider: "kis",
      strategy_mode: "sma_ema_hybrid",
      eval_context: {
        market: "US",
        session_state: "AFTER_CLOSE",
      },
      summary: {
        candidate_count: 1,
      },
      system_issues: ["FX rate missing"],
      screen_outs: ["ETF excluded"],
      issues: ["FX rate missing", "ETF excluded"],
    };
    const buyRows: ReportJson[] = [
      {
        ticker: "SYK.NYS",
        name: "Stryker",
        price: "$361.06",
        score: "7.0",
        pattern: "trend_pullback_bounce",
        pattern_reasons:
          "Bullish candle with rising volume, Reversal candle near EMA short",
        entry_state: "READY",
        entry_state_reason: "Pullback bounce confirmed on close",
        risk_guide: "Stop 352.33 / Target 378.52 (~1:2)",
        gap_guard_pct: "±2.4%",
      },
    ];

    const html = renderToStaticMarkup(
      createElement(ReportDetail, {
        detail,
        loadingDetail: false,
        error: null,
        showRaw: false,
        summary: detail.summary as ReportJson,
        buyRows,
        sellRows: [],
        entryRows: [],
        aiBriefRows: [],
        rawDetailJson: "",
        onToggleRaw: vi.fn(),
      }),
    );

    expect(html).toContain("strategy_mode");
    expect(html).toContain("session_state");
    expect(html).toContain("Candidates (1)");
    expect(html).toContain("근거");
    expect(html).toContain("리스크");
    expect(html).toContain("눌림 반등 / READY(확인)");
    expect(html).toContain("Issues");
    expect(html).toContain("System issues (1)");
    expect(html).toContain("Screen outs (1)");
  });

  it("renders entry rows with source metadata", () => {
    const detail: ReportJson = {
      schema: "sab.report.v1",
      type: "entry",
      generated_at: "2026-02-26 08:55 KST",
      provider: "kis",
      mode: "PRE_OPEN",
      source_buy_report: "2026-02-25.buy.json",
      signal_eval_date: "2026-02-25",
      entry_session_date: "2026-02-26",
      summary: {
        entry_count: 1,
      },
      eval_context: {
        market: "US",
        session_state: "PRE_OPEN",
      },
    };
    const entryRows: ReportJson[] = [
      {
        ticker: "AAPL.NASD",
        action: "ENTER",
        signal_close: 100,
        entry_price: 101.5,
        gap_pct: 0.015,
        reasons: ["entry conditions satisfied"],
      },
    ];

    const html = renderToStaticMarkup(
      createElement(ReportDetail, {
        detail,
        loadingDetail: false,
        error: null,
        showRaw: false,
        summary: detail.summary as ReportJson,
        buyRows: [],
        sellRows: [],
        entryRows,
        aiBriefRows: [],
        rawDetailJson: "",
        onToggleRaw: vi.fn(),
      }),
    );

    expect(html).toContain("source_buy_report");
    expect(html).toContain("entry_session_date");
    expect(html).toContain("Entries (1)");
    expect(html).toContain("AAPL.NASD");
    expect(html).toContain("ENTER");
    expect(html).toContain("2026-02-25.buy.json");
  });

  it("renders AI brief recommendations and structured issues", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      market: "US",
      model_provider: "openai",
      model_name: "gpt-test",
      brief_state: "NEEDS_REVIEW_WEAK_NEWS",
      brief_reason: "weak_news_coverage",
      source_entry_report: "2026-05-05.entry.json",
      source_buy_report: "2026-05-04.buy.json",
      summary: {
        recommendation_count: 1,
        source_issue_count: 1,
      },
      source_issues: [
        {
          ticker: "AAPL.NAS",
          code: "openai_no_external_sources",
          severity: "WARN",
          message: "No external source provider was configured.",
        },
      ],
      system_issues: [],
    };
    const aiBriefRows: ReportJson[] = [
      {
        ticker: "AAPL.NAS",
        rank: 1,
        confidence: "LOW",
        rationale: ["entry setup remains valid"],
        checklist: ["manually confirm price and risk"],
        sources: [
          {
            title: "Apple supply chain update",
            url: "https://example.test/aapl",
          },
        ],
      },
    ];

    const html = renderToStaticMarkup(
      createElement(ReportDetail, {
        detail,
        loadingDetail: false,
        error: null,
        showRaw: false,
        summary: detail.summary as ReportJson,
        buyRows: [],
        sellRows: [],
        entryRows: [],
        aiBriefRows,
        rawDetailJson: "",
        onToggleRaw: vi.fn(),
      }),
    );

    expect(html).toContain("model_provider");
    expect(html).toContain("brief_state");
    expect(html).toContain("NEEDS_REVIEW_WEAK_NEWS");
    expect(html).toContain("brief_reason");
    expect(html).toContain("weak_news_coverage");
    expect(html).toContain("source_entry_report");
    expect(html).toContain("Recommendations (1)");
    expect(html).toContain("AAPL.NAS");
    expect(html).toContain("entry setup remains valid");
    expect(html).toContain("Apple supply chain update");
    expect(html).toContain("Source issues (1)");
    expect(html).toContain("openai_no_external_sources");
  });

  it("infers AI brief state for legacy artifacts without explicit fields", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      market: "KR",
      model_provider: "openai",
      model_name: "gpt-test",
      source_entry_report: "2026-05-05.entry.json",
      summary: {
        preselected_count: 1,
        recommendation_count: 1,
        source_issue_count: 1,
        system_issue_count: 0,
      },
      source_issues: [
        {
          ticker: "005930",
          code: "openai_no_external_sources",
          severity: "WARN",
          message: "No external source provider was configured.",
        },
      ],
      system_issues: [],
    };
    const aiBriefRows: ReportJson[] = [
      {
        ticker: "005930",
        rank: 1,
        confidence: "LOW",
        rationale: ["entry setup remains valid"],
        checklist: ["manually confirm price and risk"],
        sources: [],
      },
    ];

    const html = renderToStaticMarkup(
      createElement(ReportDetail, {
        detail,
        loadingDetail: false,
        error: null,
        showRaw: false,
        summary: detail.summary as ReportJson,
        buyRows: [],
        sellRows: [],
        entryRows: [],
        aiBriefRows,
        rawDetailJson: "",
        onToggleRaw: vi.fn(),
      }),
    );

    expect(html).toContain("brief_state");
    expect(html).toContain("NEEDS_REVIEW_WEAK_NEWS");
    expect(html).toContain("brief_reason");
    expect(html).toContain("weak_news_coverage");
  });

  it.each([
    [
      "no signal",
      {
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
      },
      "NO_SIGNAL",
      "no_enter_candidates",
    ],
    [
      "source-backed final",
      {
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
      },
      "FINAL_JUDGMENT",
      "source_backed_final",
    ],
    [
      "model or system issue",
      {
        summary: {
          preselected_count: 1,
          recommendation_count: 0,
          source_issue_count: 0,
          system_issue_count: 1,
        },
        eligible_tickers: ["005930"],
        recommendations: [],
        source_issues: [],
        system_issues: [{ code: "model_provider_failed" }],
      },
      "NEEDS_REVIEW_WEAK_NEWS",
      "model_or_system_issue",
    ],
    [
      "model deferred",
      {
        summary: {
          preselected_count: 1,
          recommendation_count: 0,
          source_issue_count: 0,
          system_issue_count: 0,
        },
        eligible_tickers: ["005930"],
        recommendations: [],
        source_issues: [],
        system_issues: [],
      },
      "NEEDS_REVIEW_WEAK_NEWS",
      "model_deferred",
    ],
    [
      "stale source issue summary",
      {
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
        source_issues: [{ code: "source_coverage_below_threshold" }],
        system_issues: [],
      },
      "NEEDS_REVIEW_WEAK_NEWS",
      "weak_news_coverage",
    ],
  ])(
    "infers AI brief state for legacy %s artifacts",
    (_, partial, state, reason) => {
      const detail: ReportJson = {
        schema: "sab.ai_brief.v1",
        type: "ai_brief",
        generated_at: "2026-05-05T08:40:00+09:00",
        market: "US",
        model_provider: "openai",
        model_name: "gpt-test",
        source_entry_report: "2026-05-05.entry.json",
        ...partial,
      };

      const html = renderReportDetail(detail);

      expect(html).toContain("brief_state");
      expect(html).toContain(state);
      expect(html).toContain("brief_reason");
      expect(html).toContain(reason);
    },
  );

  it("does not infer AI brief state from display-only recommendation rows", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      market: "US",
      model_provider: "openai",
      model_name: "gpt-test",
      source_entry_report: "2026-05-05.entry.json",
      summary: {
        preselected_count: 0,
        recommendation_count: 0,
        source_issue_count: 0,
        system_issue_count: 0,
      },
      eligible_tickers: [],
      source_issues: [],
      system_issues: [],
    };

    const html = renderReportDetail(detail, [
      {
        ticker: "AAPL.NAS",
        sources: [{ title: "Apple update", url: "https://example.test/aapl" }],
      },
    ]);

    expect(html).toContain("brief_state");
    expect(html).toContain("NO_SIGNAL");
    expect(html).toContain("brief_reason");
    expect(html).toContain("no_enter_candidates");
  });
});
