import { describe, expect, it } from "vitest";

import { buildBuyCandidateViewModel } from "@/components/reports/buy-candidate-view-model";
import type { ReportJson } from "@/components/reports/types";

describe("buildBuyCandidateViewModel", () => {
  it("builds ema_cross reason and risk summaries", () => {
    const row: ReportJson = {
      ticker: "AAPL.NAS",
      score_notes: "ema_cross, rsi, gap, liquidity, rs_below",
      gap: "0.4%",
      gap_threshold: "3.0%",
      avg_dollar_volume: "2,000,000",
      risk_guide: "Stop 100 / Target 120 (~1:2)",
      gap_guard_pct_value: 0.03,
      ema20: "100",
      ema50: "99",
      rsi14: "52",
      atr14: "2.1",
      eval_date: "20260227",
      currency: "USD",
    };

    const model = buildBuyCandidateViewModel(row, "ema_cross");

    expect(model.reasonChips.map((chip) => chip.label)).toEqual([
      "EMA 크로스",
      "RSI 반등",
      "갭 OK",
      "유동성 OK",
      "RS 약함",
    ]);
    expect(model.reasonSummary).toContain("EMA20/50 크로스 + RSI 반등");
    expect(model.reasonSummary).toContain("갭 0.4% / 한도 3.0%");
    expect(model.reasonSummary).toContain("유동성 2,000,000");
    expect(model.riskSummary).toContain("Stop 100 / Target 120 (~1:2)");
    expect(model.riskSummary).toContain("gap guard ±3.0%");
    expect(model.detailSections.map((section) => section.title)).toEqual([
      "근거 상세",
      "지표 스냅샷",
      "리스크 상세",
      "컨텍스트",
    ]);
  });

  it("builds hybrid reason chips and summaries", () => {
    const row: ReportJson = {
      ticker: "SYK.NYS",
      pattern: "trend_pullback_bounce",
      pattern_reasons:
        "Bullish candle with rising volume, Reversal candle near EMA short",
      entry_state: "READY",
      entry_state_reason: "Pullback bounce confirmed on close",
      risk_guide: "Stop 352.33 / Target 378.52 (~1:2)",
      gap_guard_pct: "±2.4%",
      atr14: "8.73",
      eval_date: "20260211",
      currency: "USD",
      market_status: "US market closed",
    };

    const model = buildBuyCandidateViewModel(row, "sma_ema_hybrid");

    expect(model.reasonChips.map((chip) => chip.label)).toEqual([
      "눌림 반등",
      "READY(확인)",
      "양봉+거래량",
      "EMA 부근 반전",
      "gap guard ±2.4%",
    ]);
    expect(model.reasonSummary).toContain("눌림 반등 / READY(확인)");
    expect(model.reasonSummary).toContain("양봉+거래량");
    expect(model.reasonSummary).toContain("EMA 부근 반전");
    expect(model.riskSummary).toContain("Stop 352.33 / Target 378.52 (~1:2)");
    expect(model.riskSummary).toContain("gap guard ±2.4%");

    const reasonSection = model.detailSections.find(
      (section) => section.title === "근거 상세",
    );
    expect(reasonSection?.lines[0]).toBe("눌림 반등: 종가 확인");
  });

  it("prefers structured reasons when provided", () => {
    const row: ReportJson = {
      ticker: "AAPL.NAS",
      reasons: [
        {
          id: "ema_cross",
          label: "EMA20/50 골든크로스",
          kind: "signal",
          status: "pass",
          points: 1,
        },
        {
          id: "rsi_rebound",
          label: "RSI 반등",
          kind: "signal",
          status: "pass",
          points: 1,
        },
        {
          id: "gap_within_limit",
          label: "갭 허용 범위",
          kind: "filter",
          status: "pass",
          value: 0.4,
          threshold: 3.0,
          points: 1,
        },
        {
          id: "rs_below_benchmark",
          label: "RS 약함",
          kind: "filter",
          status: "warn",
          points: 0,
        },
      ],
      risk_guide: "Stop 100 / Target 120 (~1:2)",
    };

    const model = buildBuyCandidateViewModel(row, "ema_cross");

    expect(model.reasonChips.map((chip) => chip.label)).toEqual([
      "EMA20/50 골든크로스",
      "RSI 반등",
      "갭 허용 범위",
      "RS 약함",
    ]);
    expect(model.reasonSummary).toContain("EMA20/50 골든크로스");
    expect(model.reasonSummary).toContain("RSI 반등");
    expect(model.reasonSummary).toContain("갭 허용 범위");
  });
});
