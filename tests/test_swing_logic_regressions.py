from __future__ import annotations

import datetime as dt
from typing import cast

from sab.sell_evaluation import _extract_system_issues_from_reasons
from sab.signals.hybrid_buy import HybridEvaluationSettings, evaluate_ticker_hybrid
from sab.signals.sell_rules import Candle, SellSettings, evaluate_sell_signals


def _candles(count: int) -> list[dict]:
    start = dt.date(2026, 1, 2)
    rows = []
    for idx in range(count):
        close = 100.0 + idx
        rows.append(
            {
                "date": (start + dt.timedelta(days=idx)).strftime("%Y%m%d"),
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return rows


def _hybrid_settings() -> HybridEvaluationSettings:
    return HybridEvaluationSettings(
        sma_trend_period=20,
        ema_short_period=10,
        ema_mid_period=21,
        rsi_period=14,
        rsi_zone_low=45.0,
        rsi_zone_high=60.0,
        rsi_oversold_low=30.0,
        rsi_oversold_high=40.0,
        pullback_max_bars=10,
        breakout_consolidation_min_bars=5,
        breakout_consolidation_max_bars=15,
        breakout_consolidation_max_range_pct=0.10,
        volume_lookback_days=5,
        max_gap_pct=0.05,
        use_sma60_filter=False,
        sma60_period=60,
        kr_breakout_requires_confirmation=False,
        gap_atr_multiplier=1.0,
        min_history_bars=5,
        min_price=0.0,
        us_min_price=0.0,
        min_dollar_volume=0.0,
        us_min_dollar_volume=0.0,
        exclude_etf_etn=False,
    )


def test_hybrid_buy_reports_missing_core_indicators_as_system_issue() -> None:
    result = evaluate_ticker_hybrid(
        "AAPL.NASD",
        _candles(5),
        _hybrid_settings(),
        {"currency": "USD", "exchange": "NASD"},
    )

    assert result.candidate is None
    assert result.reason_kind == "system"
    assert result.reason == "Indicator data unavailable for hybrid buy: SMA trend, RSI"


def test_hybrid_buy_reports_missing_sma60_filter_as_system_issue() -> None:
    settings = _hybrid_settings()
    settings.use_sma60_filter = True

    result = evaluate_ticker_hybrid(
        "AAPL.NASD",
        _candles(20),
        settings,
        {"currency": "USD", "exchange": "NASD"},
    )

    assert result.candidate is None
    assert result.reason_kind == "system"
    assert result.reason == "Indicator data unavailable for hybrid buy: SMA60"


def test_generic_sell_reports_missing_sma200_as_system_issue() -> None:
    result = evaluate_sell_signals(
        "AAPL.NASD",
        cast(list[Candle], _candles(20)),
        {"entry_price": 100.0, "entry_currency": "USD", "exchange": "NASD"},
        SellSettings(require_sma200=True, min_bars=20),
    )

    assert result.action == "REVIEW"
    assert result.reasons[0] == "Indicator data unavailable for sell evaluation: SMA200"


def test_sell_evaluation_collects_hybrid_indicator_unavailable_as_failure() -> None:
    issues = _extract_system_issues_from_reasons(
        "AAPL.NASD",
        ["Indicator data unavailable for hybrid sell: SMA trend"],
    )

    assert issues == [
        "AAPL.NASD: Indicator data unavailable for hybrid sell: SMA trend"
    ]
