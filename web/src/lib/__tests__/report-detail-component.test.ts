import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import aiBriefStateContract from "@/components/reports/ai-brief-state-contract.json";
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
    expect(html).toContain("+1.5%");
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

  it("renders AI brief vetoed candidates", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      market: "US",
      model_provider: "openai",
      model_name: "gpt-test",
      brief_state: "NEEDS_REVIEW_WEAK_NEWS",
      brief_reason: "model_deferred",
      source_entry_report: "2026-05-05.entry.json",
      summary: {
        preselected_count: 1,
        recommendation_count: 0,
        vetoed_count: 1,
      },
      recommendations: [],
      vetoed_candidates: [
        {
          ticker: "AAPL.NAS",
          action: "SKIP",
          reason: "earnings event risk blocks the setup",
        },
      ],
      source_issues: [],
      system_issues: [],
    };

    const html = renderReportDetail(detail);

    expect(html).toContain("Vetoed candidates (1)");
    expect(html).toContain("AAPL.NAS");
    expect(html).toContain("SKIP");
    expect(html).toContain("earnings event risk blocks the setup");
  });

  it("renders AI brief watch candidates and source provider coverage", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      market: "US",
      model_provider: "openai",
      model_name: "gpt-test",
      source_entry_report: "2026-05-05.entry.json",
      summary: {
        recommendable_count: 7,
        watch_count: 2,
        preselected_count: 5,
        recommendation_count: 0,
      },
      eligible_tickers: ["AAPL.NAS"],
      watch_tickers: ["MSFT.NAS", "NVDA.NAS"],
      watch_candidates: [
        {
          ticker: "MSFT.NAS",
          action: "WATCH",
          reason: "hybrid trigger guard failed",
          retrigger_conditions: ["close back above ema10"],
          sources: [
            {
              title: "Microsoft source",
              url: "https://example.test/msft",
            },
          ],
        },
        {
          ticker: "NVDA.NAS",
          action: "WATCH",
          reason: "gap guard needs reset",
          retrigger_conditions: ["gap normalizes"],
          sources: [],
        },
      ],
      source_provider_summary: {
        chain: ["finnhub", "benzinga-news"],
        providers: [
          { provider: "finnhub", status: "success", covered: 3, total: 7 },
          {
            provider: "benzinga-news",
            status: "success",
            covered: 0,
            total: 4,
          },
        ],
        final: {
          recommendable_covered: 3,
          recommendable_total: 7,
          watch_covered: 1,
          watch_total: 2,
        },
      },
      recommendations: [],
      source_issues: [],
      system_issues: [],
    };

    const html = renderReportDetail(detail);

    expect(html).toContain("watch_tickers");
    expect(html).toContain("MSFT.NAS, NVDA.NAS");
    expect(html).toContain("source_chain");
    expect(html).toContain("finnhub,benzinga-news");
    expect(html).toContain("source_final_coverage");
    expect(html).toContain("recommendable=3/7 watch=1/2");
    expect(html).toContain("source_provider_statuses");
    expect(html).toContain("benzinga-news success 0/4");
    expect(html).toContain("Watch candidates (2)");
    expect(html).toContain("hybrid trigger guard failed");
    expect(html).toContain("close back above ema10");
    expect(html).toContain("Microsoft source");
  });

  it("renders AI brief skip guard state without recommendation rows", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief_skip.v1",
      type: "ai_brief_skip",
      generated_at: "2026-05-28T13:31:00+00:00",
      report_date: "2026-05-28",
      market: "US",
      skip_state: "RUNTIME_GUARD_SKIPPED",
      skip_reason: "scheduled_run_after_pre_open_window",
      session_state: "INTRADAY",
      expected_state: "PRE_OPEN",
      trading_session: true,
      summary: {
        skip_reason: "scheduled_run_after_pre_open_window",
      },
    };

    const html = renderReportDetail(detail);

    expect(html).toContain("skip_state");
    expect(html).toContain("RUNTIME_GUARD_SKIPPED");
    expect(html).toContain("skip_reason");
    expect(html).toContain("scheduled_run_after_pre_open_window");
    expect(html).toContain("expected_state");
    expect(html).toContain("PRE_OPEN");
    expect(html).toContain("AI Brief Skip");
    expect(html).not.toContain("Recommendations (");
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
    expect(html).not.toContain("watch_tickers");
    expect(html).not.toContain("source_chain");
    expect(html).not.toContain("source_final_coverage");
    expect(html).not.toContain("source_provider_statuses");
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

  it("renders legacy AI brief fallback states from the shared contract", () => {
    for (const [ruleId, rule] of Object.entries(aiBriefStateContract.rules)) {
      const detail: ReportJson = {
        schema: "sab.ai_brief.v1",
        type: "ai_brief",
        generated_at: "2026-05-05T08:40:00+09:00",
        market: "US",
        model_provider: "openai",
        model_name: "gpt-test",
        source_entry_report: "2026-05-05.entry.json",
        ...legacyAiBriefFixtureForRule(ruleId),
      };

      const html = renderReportDetail(detail);

      expect(html).toContain("brief_state");
      expect(html).toContain(rule.state);
      expect(html).toContain("brief_reason");
      expect(html).toContain(rule.reason);
    }
  });

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

function legacyAiBriefFixtureForRule(ruleId: string): ReportJson {
  if (ruleId === "no_signal") {
    return {
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
  }
  if (ruleId === "source_backed_final") {
    return {
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
  }
  if (ruleId === "system_issue") {
    return {
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
    };
  }
  if (ruleId === "weak_news_coverage") {
    return {
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
  }
  return {
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
  };
}
