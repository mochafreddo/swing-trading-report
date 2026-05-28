from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import pytest
from sab.config import Config
from sab.scan_evaluation import (
    _resolve_rs_benchmark_context_by_ticker,
    _write_scan_report,
)
from sab.scan_types import _ScanRuntime


def _build_runtime(*, tickers: list[str], cfg: Config | None = None) -> _ScanRuntime:
    resolved_cfg = cfg or replace(
        Config(),
        data_provider="kis",
        rs_lookback_days=5,
        rs_benchmark_ticker_kr="069500",
        rs_benchmark_ticker_us="SPY.AMS",
        universe_markets=["KR", "US"],
    )
    runtime = _ScanRuntime(
        cfg=resolved_cfg,
        logger=logging.getLogger("tests.scan_metrics_summary"),
        tickers=tickers,
    )
    runtime.ticker_currency = {
        ticker: ("USD" if "." in ticker else "KRW") for ticker in tickers
    }
    runtime.ticker_data_source = dict.fromkeys(tickers, resolved_cfg.data_provider)
    runtime.latest_dates = dict.fromkeys(tickers, "20260105")
    return runtime


def test_resolve_rs_benchmark_context_by_ticker_tracks_summary_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _build_runtime(tickers=["AAPL.NAS", "MSFT.NAS", "005930"])

    def _fake_compute(
        runtime_obj: _ScanRuntime,
        *,
        ticker: str,
        market: str,
        market_date_key: str | None = None,
    ) -> tuple[float | None, str | None]:
        del runtime_obj, ticker, market_date_key
        if market == "US":
            return (
                None,
                "SPY.AMS: RS benchmark unavailable (insufficient completed history)",
            )
        return 0.12, None

    monkeypatch.setattr(
        "sab.scan_evaluation._compute_rs_benchmark_return",
        _fake_compute,
    )

    benchmark_returns, benchmark_tickers, dynamic_requested = (
        _resolve_rs_benchmark_context_by_ticker(
            runtime,
            eval_date_by_ticker={
                "AAPL.NAS": "20260105",
                "MSFT.NAS": "20260105",
                "005930": "20260105",
            },
        )
    )

    assert dynamic_requested is True
    assert benchmark_returns == {"005930": 0.12}
    assert benchmark_tickers == {"005930": "069500"}
    assert runtime.rs_benchmark_requested_count == 3
    assert runtime.rs_benchmark_unavailable_count == 2
    assert runtime.system_issues == [
        "RS benchmark partially disabled: SPY.AMS: RS benchmark unavailable (insufficient completed history)"
    ]


def test_write_scan_report_includes_market_data_and_rs_summary_fields() -> None:
    runtime = _build_runtime(
        tickers=["AAPL.NAS", "MSFT.NAS", "005930"],
        cfg=replace(Config(), data_provider="kis", universe_markets=["US"]),
    )
    runtime.market_data = {
        "AAPL.NAS": [{"date": "20260105", "close": 100.0}],
        "MSFT.NAS": [{"date": "20260105", "close": 100.0}],
    }
    runtime.ticker_data_source = {
        "AAPL.NAS": "kis",
        "MSFT.NAS": "pykrx",
    }
    runtime.candidates = [
        {
            "ticker": "AAPL.NAS",
            "currency": "USD",
            "score_value": 1.0,
            "eval_date": "20260105",
        }
    ]
    runtime.rs_benchmark_requested_count = 2
    runtime.rs_benchmark_unavailable_count = 1

    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    summary_fields = captured["summary_fields"]
    assert summary_fields["data_requested_count"] == 3
    assert summary_fields["data_covered_count"] == 2
    assert summary_fields["data_missing_count"] == 1
    assert summary_fields["data_coverage_ratio"] == pytest.approx(2 / 3)
    assert summary_fields["provider_fallback_count"] == 1
    assert summary_fields["provider_fallback_ratio"] == pytest.approx(1 / 3)
    assert summary_fields["rs_benchmark_requested_count"] == 2
    assert summary_fields["rs_benchmark_unavailable_count"] == 1
    assert summary_fields["rs_benchmark_unavailable_ratio"] == pytest.approx(0.5)
