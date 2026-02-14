import { describe, expect, it } from "vitest";

import { extractReportTickers } from "@/lib/report-tickers";

describe("extractReportTickers", () => {
  it("prefers top-level tickers when present", () => {
    const tickers = extractReportTickers({
      tickers: [" AAPL.NAS ", "005930", "AAPL.NAS", ""]
    });

    expect(tickers).toEqual(["AAPL.NAS", "005930"]);
  });

  it("falls back to candidates[] tickers when tickers missing", () => {
    const tickers = extractReportTickers({
      candidates: [
        { ticker: "GS.NYS" },
        { ticker: "  " },
        { ticker: "SYK.NYS" },
        { ticker: "GS.NYS" }
      ]
    });

    expect(tickers).toEqual(["GS.NYS", "SYK.NYS"]);
  });

  it("falls back to evaluated[] tickers when tickers missing", () => {
    const tickers = extractReportTickers({
      evaluated: [{ ticker: "CMG.NYS" }, { ticker: "005930" }]
    });

    expect(tickers).toEqual(["CMG.NYS", "005930"]);
  });

  it("combines candidates and evaluated when needed", () => {
    const tickers = extractReportTickers({
      candidates: [{ ticker: "AAPL.NAS" }, { ticker: "MSFT.NAS" }],
      evaluated: [{ ticker: "AAPL.NAS" }, { ticker: "005930" }]
    });

    expect(tickers).toEqual(["AAPL.NAS", "MSFT.NAS", "005930"]);
  });
});

