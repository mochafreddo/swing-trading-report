from __future__ import annotations

import logging
import math
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sab.config import Config
from sab.scan_evaluation import (
    _decorate_candidates,
    _evaluate_candidates,
    _write_scan_report,
)
from sab.scan_types import _ScanRuntime
from sab.signals.evaluator import EvaluationSettings, evaluate_ticker
from sab.signals.hybrid_buy import HybridEvaluationSettings, evaluate_ticker_hybrid


def _build_runtime() -> _ScanRuntime:
    cfg = replace(Config(), data_dir="data", report_dir="reports")
    runtime = _ScanRuntime(
        cfg=cfg, logger=logging.getLogger(__name__), tickers=["AAPL.NAS"]
    )
    runtime.raw_market_data["AAPL.NAS"] = [{"date": "20250110", "close": 100.0}]
    runtime.market_data["AAPL.NAS"] = [
        {
            "date": "20250110",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        }
    ]
    runtime.ticker_currency["AAPL.NAS"] = "USD"
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
    assert runtime.screen_outs == ["AAPL.NAS: EMA(20/50) cross not satisfied"]


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
    assert runtime.screen_outs == ["AAPL.NAS: Did not meet hybrid signal criteria"]


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
    assert runtime.system_issues == ["AAPL.NAS: Insufficient price data"]
    assert runtime.failures == ["AAPL.NAS: Insufficient price data"]


def test_evaluate_candidates_injects_strategy_mode_into_ema_candidate() -> None:
    runtime = _build_runtime()

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate={"ticker": "AAPL.NAS", "score_value": 1.0},
            reason=None,
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

    assert len(runtime.candidates) == 1
    candidate = runtime.candidates[0]
    assert candidate["ticker"] == "AAPL.NAS"
    assert candidate["score_value"] == 1.0
    assert candidate["strategy_mode"] == "ema_cross"
    assert candidate["signal_price_basis"] == "adjusted"
    assert candidate["entry_reference_close_raw_value"] is None
    assert candidate["entry_reference_eval_date"] is None


def test_evaluate_candidates_injects_strategy_mode_into_hybrid_candidate() -> None:
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
            candidate={"ticker": "AAPL.NAS", "score_value": 2.0},
            reason=None,
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert len(runtime.candidates) == 1
    candidate = runtime.candidates[0]
    assert candidate["ticker"] == "AAPL.NAS"
    assert candidate["score_value"] == 2.0
    assert candidate["strategy_mode"] == "sma_ema_hybrid"
    assert candidate["signal_price_basis"] == "adjusted"
    assert candidate["entry_reference_close_raw_value"] is None
    assert candidate["entry_reference_eval_date"] is None


def test_evaluate_candidates_enriches_raw_entry_reference_close_from_prefetched_market_data() -> (
    None
):
    runtime = _build_runtime()
    runtime.tickers = ["AAPL.NAS"]
    runtime.market_data["AAPL.NAS"] = runtime.market_data.pop("AAPL.NAS")
    runtime.ticker_currency["AAPL.NAS"] = runtime.ticker_currency.pop("AAPL.NAS")

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate={
                "ticker": "AAPL.NAS",
                "score_value": 1.0,
                "close_value": 105.0,
                "price_value": 105.0,
                "eval_date": "20250110",
            },
            reason=None,
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

    assert len(runtime.candidates) == 1
    candidate = runtime.candidates[0]
    assert candidate["signal_price_basis"] == "adjusted"
    assert candidate["signal_close_adjusted_value"] == 105.0
    assert candidate["entry_reference_close_raw_value"] == 100.0
    assert candidate["entry_reference_eval_date"] == "20250110"
    assert runtime.system_issues == []
    assert runtime.raw_market_data["AAPL.NAS"][-1]["close"] == 100.0


def test_evaluate_candidates_records_raw_entry_reference_miss_without_provider_fetch() -> (
    None
):
    runtime = _build_runtime()
    runtime.raw_market_data.clear()

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate={
                "ticker": "AAPL.NAS",
                "score_value": 1.0,
                "close_value": 105.0,
                "price_value": 105.0,
                "eval_date": "20250110",
            },
            reason=None,
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

    candidate = runtime.candidates[0]
    assert candidate["entry_reference_close_raw_value"] is None
    assert candidate["entry_reference_eval_date"] == "20250110"
    assert runtime.system_issues == [
        "AAPL.NAS: raw entry reference close unavailable from batched market data"
    ]


def test_evaluate_candidates_injects_market_benchmark_context() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(
        runtime.cfg,
        rs_lookback_days=2,
        min_history_bars=2,
        rs_benchmark_return=None,
        rs_benchmark_ticker_us="SPY.AMS",
    )

    class _FakeKISClient:
        def overseas_daily_candles(
            self,
            *,
            symbol: str,
            exchange: str,
            count: int,
            adjusted: bool,
        ) -> list[dict[str, Any]]:
            if symbol == "SPY" and exchange == "AMS" and adjusted is True:
                return [
                    {"date": "20250108", "close": 100.0},
                    {"date": "20250109", "close": 105.0},
                    {"date": "20250110", "close": 110.0},
                ]
            if symbol == "AAPL" and exchange == "NAS" and adjusted is False:
                return [{"date": "20250110", "close": 100.0}]
            raise AssertionError((symbol, exchange, count, adjusted))

    runtime.kis_client = cast(Any, _FakeKISClient())
    captured: dict[str, Any] = {}

    def _evaluate(
        _ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        captured.update(meta or {})
        return SimpleNamespace(
            candidate={
                "ticker": "AAPL.NAS",
                "score_value": 1.0,
                "close_value": 105.0,
                "price_value": 105.0,
                "eval_date": "20250110",
            },
            reason=None,
        )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=_evaluate,
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert captured["rs_benchmark_ticker"] == "SPY.AMS"
    assert captured["rs_benchmark_return"] == pytest.approx(0.1)
    assert runtime.system_issues == []


def test_evaluate_candidates_disables_rs_when_benchmark_unavailable() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(
        runtime.cfg,
        rs_lookback_days=2,
        min_history_bars=2,
        rs_benchmark_return=None,
        rs_benchmark_ticker_us="SPY.AMS",
    )

    class _FakeKISClient:
        def overseas_daily_candles(
            self,
            *,
            symbol: str,
            exchange: str,
            count: int,
            adjusted: bool,
        ) -> list[dict[str, Any]]:
            if symbol == "SPY" and exchange == "AMS" and adjusted is True:
                return []
            if symbol == "AAPL" and exchange == "NAS" and adjusted is False:
                return [{"date": "20250110", "close": 100.0}]
            raise AssertionError((symbol, exchange, count, adjusted))

    runtime.kis_client = cast(Any, _FakeKISClient())
    captured: dict[str, Any] = {}

    def _evaluate(
        _ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        captured.update(meta or {})
        return SimpleNamespace(
            candidate={
                "ticker": "AAPL.NAS",
                "score_value": 1.0,
                "close_value": 105.0,
                "price_value": 105.0,
                "eval_date": "20250110",
            },
            reason=None,
        )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=_evaluate,
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert "rs_benchmark_return" not in captured
    assert runtime.system_issues == [
        "RS benchmark disabled: SPY.AMS: RS benchmark unavailable (insufficient completed history)"
    ]


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
    assert runtime.screen_outs == ["AAPL.NAS: Insufficient price data"]


def test_evaluate_candidates_routes_non_finite_ohlc_to_system_issues() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(runtime.cfg, min_history_bars=2)
    runtime.market_data["AAPL.NAS"] = [
        {
            "date": "20250108",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250109",
            "open": 101.0,
            "high": math.inf,
            "low": 100.0,
            "close": 101.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250110",
            "open": 102.0,
            "high": 103.0,
            "low": 101.0,
            "close": 102.0,
            "volume": 1_000_000.0,
        },
    ]

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=EvaluationSettings,
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=evaluate_ticker,
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
    assert runtime.system_issues == [
        "AAPL.NAS: Invalid candle data: non-finite OHLC values"
    ]
    assert runtime.failures == ["AAPL.NAS: Invalid candle data: non-finite OHLC values"]


def test_evaluate_candidates_routes_hybrid_non_finite_ohlc_to_system_issues(
    monkeypatch: Any,
) -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(
        runtime.cfg,
        strategy_mode="sma_ema_hybrid",
        min_history_bars=2,
    )
    runtime.market_data["AAPL.NAS"] = [
        {
            "date": "20250108",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250109",
            "open": 101.0,
            "high": math.inf,
            "low": 100.0,
            "close": 101.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250110",
            "open": 102.0,
            "high": 103.0,
            "low": 101.0,
            "close": 102.0,
            "volume": 1_000_000.0,
        },
    ]
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=EvaluationSettings,
        HybridEvaluationSettingsCls=HybridEvaluationSettings,
        evaluate_ticker_fn=evaluate_ticker,
        evaluate_ticker_hybrid_fn=evaluate_ticker_hybrid,
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert runtime.screen_outs == []
    assert runtime.system_issues == [
        "AAPL.NAS: Invalid candle data: non-finite OHLC values"
    ]
    assert runtime.failures == ["AAPL.NAS: Invalid candle data: non-finite OHLC values"]


def test_write_scan_report_emits_split_issue_fields_with_legacy_issues() -> None:
    runtime = _build_runtime()
    runtime.failures = ["system-failure-1"]
    runtime.system_issues = ["system-failure-2"]
    runtime.screen_outs = ["AAPL.NAS: RSI signal not satisfied"]

    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    assert captured["system_issues"] == ["system-failure-2", "system-failure-1"]
    assert captured["screen_outs"] == ["AAPL.NAS: RSI signal not satisfied"]
    assert captured["failures"] == [
        "system-failure-2",
        "system-failure-1",
        "AAPL.NAS: RSI signal not satisfied",
    ]


def test_write_scan_report_uses_resolved_session_state(monkeypatch: Any) -> None:
    runtime = _build_runtime()
    runtime.failures = []
    runtime.system_issues = []
    runtime.screen_outs = []

    monkeypatch.setattr(
        "sab.scan_evaluation.resolve_run_session_state",
        lambda *_args, **_kwargs: "PRE_OPEN",
        raising=False,
    )

    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    assert (
        captured["run_meta"]["eval_context"]["session_state"]  # type: ignore[index]
        == "PRE_OPEN"
    )


def test_write_scan_report_uses_latest_market_date_when_candidates_are_empty() -> None:
    runtime = _build_runtime()
    runtime.candidates = []
    runtime.latest_dates = {
        "005930": "20250226",
        "AAPL.NAS": "20250225",
    }

    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    assert captured["artifact_date"] == "20250226"


def test_write_scan_report_emits_session_state_by_market_for_mixed_run(
    monkeypatch: Any,
) -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(runtime.cfg, universe_markets=["KR", "US"])
    runtime.failures = []
    runtime.system_issues = []
    runtime.screen_outs = []

    monkeypatch.setattr(
        "sab.scan_evaluation.resolve_run_session_state",
        lambda *_args, **_kwargs: "PRE_OPEN",
        raising=False,
    )
    monkeypatch.setattr(
        "sab.scan_evaluation.resolve_run_session_state_map",
        lambda *_args, **_kwargs: {"KR": "AFTER_CLOSE", "US": "PRE_OPEN"},
        raising=False,
    )

    captured: dict[str, Any] = {}

    def _fake_write_report(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "dummy-report.json"

    _write_scan_report(runtime, write_report_fn=_fake_write_report)

    eval_context = captured["run_meta"]["eval_context"]  # type: ignore[index]
    assert eval_context["market"] == "MIXED"
    assert eval_context["session_state_by_market"] == {
        "KR": "AFTER_CLOSE",
        "US": "PRE_OPEN",
    }


def test_evaluate_candidates_isolates_unexpected_ticker_exceptions() -> None:
    runtime = _build_runtime()
    runtime.tickers = ["AAPL.NAS", "MSFT.NAS"]
    runtime.market_data["MSFT.NAS"] = [
        {
            "date": "20250110",
            "open": 200.0,
            "high": 201.0,
            "low": 199.0,
            "close": 200.0,
            "volume": 1_000_000.0,
        }
    ]
    runtime.ticker_currency["MSFT.NAS"] = "USD"

    def _evaluate_ticker(
        ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        _meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        if ticker == "AAPL.NAS":
            raise RuntimeError("evaluation exploded")
        return SimpleNamespace(
            candidate={"ticker": ticker, "score_value": 1.0},
            reason=None,
        )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=_evaluate_ticker,
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert len(runtime.candidates) == 1
    candidate = runtime.candidates[0]
    assert candidate["ticker"] == "MSFT.NAS"
    assert candidate["score_value"] == 1.0
    assert candidate["strategy_mode"] == "ema_cross"
    assert candidate["signal_price_basis"] == "adjusted"
    assert candidate["entry_reference_close_raw_value"] is None
    assert runtime.screen_outs == []
    assert runtime.system_issues == [
        "AAPL.NAS: Unexpected evaluation error (RuntimeError: evaluation exploded)"
    ]
    assert runtime.failures == [
        "AAPL.NAS: Unexpected evaluation error (RuntimeError: evaluation exploded)"
    ]


def test_decorate_candidates_passes_data_dir_to_market_status_fallback() -> None:
    runtime = _build_runtime()
    runtime.cfg = replace(runtime.cfg, data_dir="custom-data-dir")
    runtime.candidates = [
        {
            "ticker": "AAPL.NAS",
            "currency": "USD",
            "price_value": 100.0,
            "score_value": 1.0,
        }
    ]

    called: dict[str, str] = {}

    def _fake_market_status(*, data_dir: str) -> str:
        called["data_dir"] = data_dir
        return "closed"

    _decorate_candidates(
        runtime,
        apply_currency_display_fn=lambda *_args, **_kwargs: None,
        lookup_holiday_fn=lambda *_args, **_kwargs: None,
        us_market_status_fn=_fake_market_status,
    )

    assert called == {"data_dir": "custom-data-dir"}
    assert runtime.candidates[0]["market_status"] == "US market closed"


def test_decorate_candidates_breaks_score_ties_with_quality_metrics() -> None:
    runtime = _build_runtime()
    runtime.candidates = [
        {
            "ticker": "LOW.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 5.0,
            "rs_diff_value": 0.1,
            "avg_dollar_volume_value": 100_000.0,
            "pct_change_value": 0.01,
        },
        {
            "ticker": "HIGH.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 5.0,
            "rs_diff_value": 0.3,
            "avg_dollar_volume_value": 300_000.0,
            "pct_change_value": 0.03,
        },
    ]

    _decorate_candidates(
        runtime,
        apply_currency_display_fn=lambda *_args, **_kwargs: None,
        lookup_holiday_fn=lambda *_args, **_kwargs: None,
        us_market_status_fn=lambda **_kwargs: "closed",
    )

    assert [candidate["ticker"] for candidate in runtime.candidates] == [
        "HIGH.KR",
        "LOW.KR",
    ]


def test_decorate_candidates_treats_missing_rs_as_neutral() -> None:
    runtime = _build_runtime()
    runtime.candidates = [
        {
            "ticker": "MISSING.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 5.0,
            "avg_dollar_volume_value": 100_000.0,
            "pct_change_value": 0.01,
        },
        {
            "ticker": "NEGATIVE.KR",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 5.0,
            "rs_diff_value": -0.2,
            "avg_dollar_volume_value": 100_000.0,
            "pct_change_value": 0.01,
        },
    ]

    _decorate_candidates(
        runtime,
        apply_currency_display_fn=lambda *_args, **_kwargs: None,
        lookup_holiday_fn=lambda *_args, **_kwargs: None,
        us_market_status_fn=lambda **_kwargs: "closed",
    )

    assert [candidate["ticker"] for candidate in runtime.candidates] == [
        "MISSING.KR",
        "NEGATIVE.KR",
    ]


def test_evaluate_candidates_keeps_available_rs_benchmark_for_other_market(
    monkeypatch: Any,
) -> None:
    runtime = _build_runtime()
    runtime.tickers = ["005930", "AAPL.NAS"]
    runtime.market_data = {
        "005930": runtime.market_data["AAPL.NAS"],
        "AAPL.NAS": runtime.market_data["AAPL.NAS"],
    }
    runtime.ticker_currency = {"005930": "KRW", "AAPL.NAS": "USD"}
    runtime.cfg = replace(
        runtime.cfg,
        rs_lookback_days=20,
        rs_benchmark_ticker_kr=None,
        rs_benchmark_ticker_us="SPY.AMS",
    )
    monkeypatch.setattr(
        "sab.scan_evaluation._compute_rs_benchmark_return",
        lambda runtime_obj, *, ticker, market: (
            (0.12, None)
            if market == "US"
            else (None, "KR: benchmark ticker not configured")
        ),
    )

    captured_meta: dict[str, dict[str, Any]] = {}

    def _evaluate_ticker(
        ticker: str,
        _candles: list[dict[str, float]],
        _settings: Any,
        meta: dict[str, Any] | None = None,
    ) -> SimpleNamespace:
        captured_meta[ticker] = dict(meta or {})
        return SimpleNamespace(
            candidate={"ticker": ticker, "score_value": 1.0}, reason=None
        )

    _evaluate_candidates(
        runtime,
        EvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        HybridEvaluationSettingsCls=lambda **kwargs: SimpleNamespace(**kwargs),
        evaluate_ticker_fn=_evaluate_ticker,
        evaluate_ticker_hybrid_fn=lambda *_args, **_kwargs: SimpleNamespace(
            candidate=None, reason=None
        ),
        split_overseas_fn=lambda ticker: (
            ticker.split(".")[0],
            ticker.split(".")[1] if "." in ticker else None,
        ),
        excd_from_suffix_fn=lambda suffix: suffix,
    )

    assert "rs_benchmark_return" not in captured_meta["005930"]
    assert captured_meta["AAPL.NAS"]["rs_benchmark_return"] == pytest.approx(0.12)
    assert any(
        issue.startswith("RS benchmark partially disabled:")
        for issue in runtime.system_issues
    )


def test_decorate_candidates_converts_us_liquidity_for_mixed_market_sort() -> None:
    runtime = _build_runtime()
    runtime.fx_rate = 1500.0
    runtime.candidates = [
        {
            "ticker": "KR1",
            "currency": "KRW",
            "price_value": 100.0,
            "score_value": 5.0,
            "rs_diff_value": 0.1,
            "avg_dollar_volume_value": 1_000_000_000.0,
            "pct_change_value": 0.01,
        },
        {
            "ticker": "US1",
            "currency": "USD",
            "price_value": 100.0,
            "score_value": 5.0,
            "rs_diff_value": 0.1,
            "avg_dollar_volume_value": 2_000_000.0,
            "pct_change_value": 0.01,
        },
    ]

    _decorate_candidates(
        runtime,
        apply_currency_display_fn=lambda *_args, **_kwargs: None,
        lookup_holiday_fn=lambda *_args, **_kwargs: None,
        us_market_status_fn=lambda **_kwargs: "closed",
    )

    assert [candidate["ticker"] for candidate in runtime.candidates] == [
        "US1",
        "KR1",
    ]
