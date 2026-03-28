from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

import pytest
from sab.config import Config
from sab.report.sell_report import SellReportRow
from sab.report.summary_metrics import build_market_data_summary
from sab.sell_evaluation import _write_sell_report
from sab.sell_types import _SellRuntime


def test_build_market_data_summary_returns_null_ratios_when_no_requests() -> None:
    summary = build_market_data_summary(
        requested_count=0,
        covered_count=0,
        fallback_count=0,
    )

    assert summary["data_requested_count"] == 0
    assert summary["data_covered_count"] == 0
    assert summary["data_missing_count"] == 0
    assert summary["data_coverage_ratio"] is None
    assert summary["provider_fallback_count"] == 0
    assert summary["provider_fallback_ratio"] is None


def test_build_market_data_summary_uses_requested_count_for_fallback_ratio() -> None:
    summary = build_market_data_summary(
        requested_count=10,
        covered_count=3,
        fallback_count=1,
    )

    assert summary["provider_fallback_ratio"] == pytest.approx(0.1)


def test_write_sell_report_includes_market_data_summary_fields() -> None:
    runtime = _SellRuntime(
        cfg=replace(Config(), data_provider="kis"),
        logger=logging.getLogger("tests.sell_metrics_summary"),
        holdings=[],
        unique_tickers=["AAPL.NAS", "005930"],
        ticker_currency={"AAPL.NAS": "USD", "005930": "KRW"},
    )
    runtime.market_data = {
        "AAPL.NAS": [{"date": "20260106", "close": 190.0}],
    }
    runtime.ticker_data_source = {
        "AAPL.NAS": "pykrx",
    }
    results = [
        SellReportRow(
            ticker="AAPL.NAS",
            name="Apple",
            quantity=1.0,
            entry_price=150.0,
            entry_date="2026-01-02",
            last_price=190.0,
            pnl_pct=0.2,
            action="HOLD",
            reasons=["test"],
            stop_price=170.0,
            target_price=210.0,
            currency="USD",
            eval_date="20260106",
        )
    ]

    captured: dict[str, Any] = {}

    def _fake_write_sell_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_sell_report(runtime, results, write_sell_report_fn=_fake_write_sell_report)

    summary_fields = captured["summary_fields"]
    assert summary_fields["data_requested_count"] == 2
    assert summary_fields["data_covered_count"] == 1
    assert summary_fields["data_missing_count"] == 1
    assert summary_fields["data_coverage_ratio"] == pytest.approx(0.5)
    assert summary_fields["provider_fallback_count"] == 1
    assert summary_fields["provider_fallback_ratio"] == pytest.approx(0.5)
