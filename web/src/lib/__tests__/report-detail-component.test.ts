import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ReportDetail } from "@/components/reports/report-detail";
import type { ReportJson } from "@/components/reports/types";

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
});
