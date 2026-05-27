from __future__ import annotations

import datetime as dt
from typing import Any

from sab.signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid


def _flat_candles(count: int) -> list[dict[str, Any]]:
    start = dt.date(2026, 1, 2)
    return [
        {
            "date": (start + dt.timedelta(days=idx)).isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
        }
        for idx in range(count)
    ]


def test_hybrid_sell_reviews_when_required_indicator_is_unavailable() -> None:
    settings = HybridSellSettings(
        min_bars=20,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=60,
        rsi_period=14,
        time_stop_days=0,
    )

    result = evaluate_sell_signals_hybrid(
        "AAPL.NASD",
        _flat_candles(20),
        {"entry_price": 100.0, "entry_currency": "USD", "exchange": "NASD"},
        settings,
    )

    assert result.action == "REVIEW"
    assert result.reasons == ["Indicator data unavailable for hybrid sell: SMA trend"]


def test_hybrid_sell_does_not_sell_extended_time_stop_when_only_trend_unavailable() -> (
    None
):
    settings = HybridSellSettings(
        min_bars=20,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=60,
        rsi_period=14,
        time_stop_days=1,
        time_stop_grace_days=1,
        time_stop_profit_floor=0.01,
    )

    result = evaluate_sell_signals_hybrid(
        "AAPL.NASD",
        _flat_candles(20),
        {
            "entry_price": 98.0,
            "entry_currency": "USD",
            "exchange": "NASD",
            "entry_date": "2026-01-02",
        },
        settings,
    )

    assert result.action == "REVIEW"
    assert "Indicator data unavailable for hybrid sell: SMA trend" in result.reasons
    assert not any(
        reason.startswith("Extended time stop:") for reason in result.reasons
    )
