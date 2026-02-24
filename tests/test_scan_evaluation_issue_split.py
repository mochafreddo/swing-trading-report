from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from sab.config import Config
from sab.scan_evaluation import _evaluate_candidates, _write_scan_report
from sab.scan_types import _ScanRuntime


def _build_runtime() -> _ScanRuntime:
    cfg = replace(Config(), data_dir="data", report_dir="reports")
    runtime = _ScanRuntime(
        cfg=cfg, logger=logging.getLogger(__name__), tickers=["AAPL.US"]
    )
    runtime.market_data["AAPL.US"] = [
        {
            "date": "20250110",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        }
    ]
    runtime.ticker_currency["AAPL.US"] = "USD"
    return runtime


def test_evaluate_candidates_routes_reason_to_screen_outs() -> None:
    runtime = _build_runtime()

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason="EMA(20/50) cross not satisfied"
        ),
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert runtime.failures == []
    assert runtime.screen_outs == ["AAPL.US: EMA(20/50) cross not satisfied"]


def test_evaluate_candidates_routes_generic_hybrid_miss_to_screen_outs() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(runtime.cfg, strategy_mode="sma_ema_hybrid")

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None,
            reason="Did not meet hybrid signal criteria",
            reason_kind="signal",
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert runtime.failures == []
    assert runtime.system_issues == []
    assert runtime.screen_outs == ["AAPL.US: Did not meet hybrid signal criteria"]


def test_evaluate_candidates_routes_data_quality_to_system_issues() -> None:
    runtime = _build_runtime()

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason="Insufficient price data"
        ),
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert runtime.screen_outs == []
    assert runtime.system_issues == ["AAPL.US: Insufficient price data"]
    assert runtime.failures == ["AAPL.US: Insufficient price data"]


def test_evaluate_candidates_prefers_reason_kind_over_text_prefix() -> None:
    runtime = _build_runtime()

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None,
            reason="Insufficient price data",
            reason_kind="signal",
        ),
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert runtime.failures == []
    assert runtime.system_issues == []
    assert runtime.screen_outs == ["AAPL.US: Insufficient price data"]


def test_write_scan_report_emits_split_issue_fields_with_legacy_issues() -> None:
    runtime = _build_runtime()
    runtime.failures = ["system-failure-1"]
    runtime.system_issues = ["system-failure-2"]
    runtime.screen_outs = ["AAPL.US: RSI signal not satisfied"]

    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    assert captured["system_issues"] == ["system-failure-2", "system-failure-1"]
    assert captured["screen_outs"] == ["AAPL.US: RSI signal not satisfied"]
    assert captured["failures"] == [
        "system-failure-2",
        "system-failure-1",
        "AAPL.US: RSI signal not satisfied",
    ]
