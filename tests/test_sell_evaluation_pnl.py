from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sab.report.sell_report import SellReportRow
from sab.sell_evaluation import _evaluate_holdings


def _make_cfg() -> SimpleNamespace:
    hybrid_sell = SimpleNamespace(
        profit_target_low=0.05,
        profit_target_high=0.1,
        partial_profit_floor=0.03,
        ema_short_period=10,
        ema_mid_period=21,
        sma_trend_period=20,
        rsi_period=14,
        stop_loss_pct_min=0.03,
        stop_loss_pct_max=0.05,
        failed_breakout_drop_pct=0.03,
        min_bars=20,
        time_stop_days=0,
        time_stop_grace_days=0,
        time_stop_profit_floor=0.0,
    )
    return SimpleNamespace(
        sell_atr_multiplier=1.0,
        sell_time_stop_days=10,
        sell_require_sma200=True,
        sell_ema_short=20,
        sell_ema_long=50,
        sell_rsi_period=14,
        sell_rsi_floor=50.0,
        sell_rsi_floor_alt=30.0,
        sell_min_bars=20,
        sell_mode="generic",
        hybrid_sell=hybrid_sell,
        data_provider="kis",
        data_dir="data",
    )


def _make_runtime(*, entry_price: float) -> Any:
    holding = SimpleNamespace(
        ticker="AAPL.NASD",
        quantity=1.0,
        entry_price=entry_price,
        entry_date="2025-01-01",
        stop_override=None,
        target_override=None,
        strategy=None,
        entry_currency="USD",
        notes=None,
    )
    return SimpleNamespace(
        cfg=_make_cfg(),
        holdings=[holding],
        market_data={
            "AAPL.NASD": [
                {
                    "date": "20250102",
                    "open": 100.0,
                    "high": 100.0,
                    "low": 0.0,
                    "close": 0.0,
                    "volume": 1.0,
                }
            ]
        },
        missing_logged=set(),
        failures=[],
        ticker_currency={"AAPL.NASD": "USD"},
        ticker_data_source={},
    )


def test_evaluate_holdings_reports_minus_100_pct_when_last_price_is_zero() -> None:
    runtime = _make_runtime(entry_price=100.0)

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="HOLD",
            reasons=["ok"],
            stop_price=None,
            target_price=None,
            eval_price=0.0,
            eval_date="20250102",
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].pnl_pct == -1.0


def test_evaluate_holdings_keeps_pnl_none_when_entry_price_is_zero() -> None:
    runtime = _make_runtime(entry_price=0.0)

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="HOLD",
            reasons=["ok"],
            stop_price=None,
            target_price=None,
            eval_price=50.0,
            eval_date="20250102",
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].pnl_pct is None


def test_evaluate_holdings_passes_tags_to_hybrid_sell() -> None:
    runtime = _make_runtime(entry_price=100.0)
    runtime.cfg.sell_mode = "sma_ema_hybrid"
    runtime.holdings[0].tags = ["swing_high_breakout"]
    captured: dict[str, Any] = {}

    def _evaluate(
        _ticker: str,
        _candles: list[dict[str, float]],
        holding: dict[str, Any],
        _settings: Any,
    ) -> SimpleNamespace:
        captured.update(holding)
        return SimpleNamespace(
            action="HOLD",
            reasons=["ok"],
            stop_price=None,
            target_price=None,
            eval_price=100.0,
            eval_date="20250102",
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=lambda *_args, **_kwargs: pytest.fail(
            "generic sell evaluator should not be called"
        ),
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert captured["tags"] == ["swing_high_breakout"]


def test_evaluate_holdings_skips_last_price_fallback_for_invalid_candle_data() -> None:
    runtime = _make_runtime(entry_price=100.0)
    runtime.market_data["AAPL.NASD"] = [
        {
            "date": "20250102",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250103",
            "open": 110.0,
            "high": 111.0,
            "low": 109.0,
            "close": 110.0,
            "volume": 1.0,
        },
    ]

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action="REVIEW",
            reasons=["Invalid candle data: non-finite OHLC values"],
            stop_price=None,
            target_price=None,
            eval_price=None,
            eval_date="20250103",
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].last_price is None
    assert rows[0].pnl_pct is None


def test_evaluate_holdings_emits_review_row_when_market_data_missing() -> None:
    runtime = _make_runtime(entry_price=100.0)
    runtime.market_data = {}

    def _evaluate(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise AssertionError("evaluation should not be called without market data")

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 1
    assert rows[0].ticker == "AAPL.NASD"
    assert rows[0].action == "REVIEW"
    assert rows[0].reasons == ["No market data available for sell evaluation"]
    assert rows[0].last_price is None
    assert rows[0].pnl_pct is None
    assert "AAPL.NASD: No market data available for sell evaluation" in runtime.failures


def test_evaluate_holdings_isolates_unexpected_ticker_exceptions() -> None:
    runtime = _make_runtime(entry_price=100.0)
    runtime.holdings.append(
        SimpleNamespace(
            ticker="MSFT.NASD",
            quantity=2.0,
            entry_price=100.0,
            entry_date="2025-01-01",
            stop_override=None,
            target_override=None,
            strategy=None,
            entry_currency="USD",
            notes=None,
        )
    )
    runtime.market_data["MSFT.NASD"] = [
        {
            "date": "20250103",
            "open": 110.0,
            "high": 111.0,
            "low": 109.0,
            "close": 110.0,
            "volume": 1.0,
        }
    ]
    runtime.ticker_currency["MSFT.NASD"] = "USD"

    def _evaluate(
        ticker: str,
        _candles: list[dict[str, float]],
        _holding: dict[str, Any],
        _settings: Any,
    ) -> SimpleNamespace:
        if ticker == "AAPL.NASD":
            raise RuntimeError("sell evaluation exploded")
        return SimpleNamespace(
            action="HOLD",
            reasons=["ok"],
            stop_price=None,
            target_price=None,
            eval_price=110.0,
            eval_date="20250103",
        )

    rows = _evaluate_holdings(
        runtime,
        SellSettingsCls=SimpleNamespace,
        HybridSellSettingsCls=SimpleNamespace,
        evaluate_sell_signals_fn=_evaluate,
        evaluate_sell_signals_hybrid_fn=_evaluate,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=lambda ticker: (ticker, "NASD"),
        exchange_from_suffix_fn=lambda _suffix: "NAS",
    )

    assert len(rows) == 2
    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["AAPL.NASD"].action == "REVIEW"
    assert by_ticker["AAPL.NASD"].last_price is None
    assert by_ticker["AAPL.NASD"].pnl_pct is None
    assert by_ticker["AAPL.NASD"].reasons == [
        "Unexpected sell evaluation error (RuntimeError: sell evaluation exploded)"
    ]
    assert by_ticker["MSFT.NASD"].action == "HOLD"
    assert by_ticker["MSFT.NASD"].last_price == 110.0
    assert by_ticker["MSFT.NASD"].pnl_pct == 0.1
    assert runtime.failures == [
        "AAPL.NASD: Unexpected sell evaluation error (RuntimeError: sell evaluation exploded)"
    ]
