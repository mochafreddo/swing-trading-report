from __future__ import annotations

from typing import cast

import pytest
from sab.signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid


def _patch_hold_indicators(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.ema", lambda closes, n: [98.0, 98.0, 99.0]
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.sma", lambda closes, n: [98.0, 98.0, 98.0]
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.rsi", lambda closes, n: [60.0, 60.0, 60.0]
    )


def test_hybrid_sell_uses_pattern_specific_time_stop_before_global_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_hold_indicators(monkeypatch)
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.count_trading_sessions",
        lambda *_args, **_kwargs: 11,
    )

    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=3,
        sma_trend_period=2,
        time_stop_days=30,
        time_stop_grace_days=15,
        time_stop_profit_floor=0.03,
        pattern_time_stops={
            "swing_high_breakout": {
                "time_stop_days": 10,
                "time_stop_grace_days": 2,
                "time_stop_profit_floor": 0.01,
            }
        },
    )
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-06",
        "entry_pattern": "swing_high_breakout",
        "entry_currency": "USD",
        "data_dir": tmp_path.as_posix(),
    }
    candles = [
        {
            "date": "20250106",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250107",
            "open": 100.5,
            "high": 100.5,
            "low": 100.5,
            "close": 100.5,
            "volume": 1.0,
        },
        {
            "date": "20250121",
            "open": 100.5,
            "high": 100.5,
            "low": 100.5,
            "close": 100.5,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "AAPL.NAS",
        cast(list[dict[str, float]], candles),
        holding,
        settings,
    )

    assert result.action == "REVIEW"
    assert result.days_in_trade_sessions == 10
    assert result.time_stop_triggered is True
    assert result.reasons == ["Time stop: 10 sessions ≥ 10 sessions"]
