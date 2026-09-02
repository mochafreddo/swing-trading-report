import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

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

const loadDecisionFixture = (name: string): ReportJson =>
  JSON.parse(
    readFileSync(
      fileURLToPath(
        new URL(
          `../../../../tests/fixtures/decision_board/${name}`,
          import.meta.url,
        ),
      ),
      "utf8",
    ),
  ) as ReportJson;

describe("ReportDetail component", () => {
  it("renders a dedicated published Decision Board ENTRY detail", () => {
    const detail = loadDecisionFixture("published-entry.json");

    const html = renderReportDetail(detail);

    expect(html).toContain("Decision Board");
    expect(html).toContain("entry-2026-08-06T010000Z");
    expect(html).toContain("ENTRY");
    expect(html).toContain("AUR.NAS");
    expect(html).toContain("BUY");
    expect(html).toContain("Aurora demand update");
    expect(html).toContain("https://evidence.example/aurora-demand");
    expect(html).toContain("noopener noreferrer");
    expect(html).toContain("Synthetic Wire");
    expect(html).toContain("WITHIN_POLICY");
    expect(html).toContain("SUPPORTED");
    expect(html).toContain("Aurora demand remains strong.");
    expect(html).toContain("sha256:1111111111111111");
    expect(html).toContain("[0,29)");
    expect(html).toContain("EVIDENCE_UNCLEAR");
  });

  it("keeps HOLDING SELL visually explicit", () => {
    const html = renderReportDetail(
      loadDecisionFixture("published-holding.json"),
    );

    expect(html).toContain("HOLDING");
    expect(html).toContain("ELM.NYS");
    expect(html).toContain("SELL");
    expect(html).toContain("decisionSell");
  });

  it("renders BLOCKED without a directional table", () => {
    const html = renderReportDetail(loadDecisionFixture("blocked.json"));

    expect(html).toContain("BLOCKED");
    expect(html).toContain("IDENTITY_UNRESOLVED");
    expect(html).toContain("어떤 매수·매도·보유 조언도 발행하지 않았습니다");
    expect(html).not.toContain("Decision items");
    expect(html).not.toContain(">BUY<");
    expect(html).not.toContain(">SELL<");
  });

  it("renders an empty published Decision Board universe as a valid state", () => {
    const detail = loadDecisionFixture("published-entry.json") as {
      decision_payload: { items: unknown[] };
    } & ReportJson;
    detail.decision_payload.items = [];

    const html = renderReportDetail(detail);

    expect(html).toContain("No eligible Decision Board items");
    expect(html).not.toContain("리포트를 선택하세요");
  });

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
        implementation_ready: false,
        investment_readiness: "CONTEXT_REQUIRED",
        investment_readiness_reasons: [
          "nav_risk_budget_unavailable",
          "liquidity_exit_capacity_unavailable",
        ],
        liquidity_exit_capacity: {
          status: "available",
          currency: "USD",
          position_value: 100000,
          avg_traded_value: 2000000,
          position_adv_percent: 5,
          exit_days_normal: 0.5,
          exit_days_stressed: 1.6667,
        },
        liquidity_warnings: ["small_cap_liquidity_risk"],
        downside_risk: {
          status: "available",
          currency: "USD",
          position_value: 100000,
          entry_price: 101.5,
          stop_price: 96.5,
          target_price: 112,
          position_loss_amount: 4926.1084,
          position_loss_pct: 4.9261,
          portfolio_value: 1000000,
          portfolio_loss_pct: 0.4926,
          portfolio_loss_bps: 49.2611,
          caveat: "stop_target_decision_guide_only_gap_slippage_may_exceed",
        },
        portfolio_exposure_buckets: ["currency=USD", "theme=ai-megacap"],
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
    expect(html).toContain("Readiness");
    expect(html).toContain("CONTEXT_REQUIRED");
    expect(html).toContain(
      "nav_risk_budget_unavailable · liquidity_exit_capacity_unavailable",
    );
    expect(html).toContain("Exit Capacity");
    expect(html).toContain("ADV 5% · normal 0.5d · stressed 1.7d");
    expect(html).toContain("small_cap_liquidity_risk");
    expect(html).toContain("Downside");
    expect(html).toContain("USD 4,926.11");
    expect(html).toContain("49.3bps");
    expect(html).toContain("가이드");
    expect(html).toContain("갭/슬리피지");
    expect(html).toContain("Exposure");
    expect(html).toContain("currency=USD · theme=ai-megacap");
    expect(html).toContain("2026-02-25.buy.json");
  });

  it("renders sell stop and target values as decision guides", () => {
    const detail: ReportJson = {
      schema: "sab.report.v1",
      type: "sell",
      generated_at: "2026-02-11 21:03 KST",
      provider: "kis",
      summary: {
        evaluated_count: 1,
      },
    };
    const sellRows: ReportJson[] = [
      {
        ticker: "AAPL.NASD",
        action: "REVIEW",
        last_price: 190,
        pnl_pct: 0.2,
        stop_price: 170,
        target_price: 210,
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
        sellRows,
        entryRows: [],
        aiBriefRows: [],
        rawDetailJson: "",
        onToggleRaw: vi.fn(),
      }),
    );

    expect(html).toContain("Stop Guide");
    expect(html).toContain("Target Guide");
    expect(html).toContain("의사결정 가이드");
    expect(html).toContain("170");
    expect(html).toContain("210");
    expect(html).toContain("갭/슬리피지");
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
        candidate_role: "executable",
        entry_action: "ENTER",
        candidate_role_reason: "entry report action was ENTER",
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
    expect(html).toContain("Role");
    expect(html).toContain("executable");
    expect(html).toContain("Entry Action");
    expect(html).toContain("ENTER");
    expect(html).toContain("entry report action was ENTER");
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

  it("renders Sell AI Brief judgments", () => {
    const detail: ReportJson = {
      schema: "sab.sell_ai_brief.v1",
      type: "sell-ai-brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      model_provider: "openai",
      model_name: "gpt-test",
      source_sell_report: "2026-05-05.sell.json",
      brief_state: "FINAL_JUDGMENT",
      brief_reason: "model_judgment_ready",
      summary: {
        judgment_count: 1,
      },
      judgments: [
        {
          ticker: "AAPL.NAS",
          name: "Apple",
          sell_action: "SELL",
          ai_stance: "AGREE",
          confidence: "LOW",
          deterministic_reasons: ["stop loss breached"],
          rationale: ["model agrees with the deterministic sell signal"],
          checklist: ["confirm size and liquidity"],
          sources: [
            {
              title: "Apple risk update",
              url: "https://example.test/aapl",
            },
          ],
        },
      ],
      vetoed_candidates: [],
      source_issues: [],
      system_issues: [],
    };

    const html = renderReportDetail(detail);

    expect(html).toContain("source_sell_report");
    expect(html).toContain("brief_state");
    expect(html).toContain("FINAL_JUDGMENT");
    expect(html).toContain("Judgments (1)");
    expect(html).toContain("AAPL.NAS");
    expect(html).toContain("SELL");
    expect(html).toContain("AGREE");
    expect(html).toContain("stop loss breached");
    expect(html).toContain("model agrees with the deterministic sell signal");
    expect(html).toContain("confirm size and liquidity");
    expect(html).toContain("Apple risk update");
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
        executable_count: 1,
        blocked_but_valid_count: 6,
        watch_count: 2,
        preselected_count: 5,
        recommendation_count: 0,
      },
      executable_tickers: ["AAPL.NAS"],
      blocked_but_valid_tickers: ["MSFT.NAS", "NVDA.NAS"],
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
    expect(html).toContain("executable_tickers");
    expect(html).toContain("AAPL.NAS");
    expect(html).toContain("blocked_but_valid_tickers");
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

  it("renders a source-backed AI brief as a positive review state", () => {
    const detail: ReportJson = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      generated_at: "2026-05-05T08:40:00+09:00",
      market: "US",
      model_provider: "openai",
      model_name: "gpt-test",
      source_entry_report: "2026-05-05.entry.json",
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

    const html = renderReportDetail(detail);

    expect(html).toContain("FINAL_JUDGMENT");
    expect(html).toContain('data-tone="positive"');
    expect(html).toContain("소스 확인 완료");
  });

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
  if (ruleId === "watch_only") {
    return {
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
