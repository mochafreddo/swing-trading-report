from __future__ import annotations

import pytest
import sab.signals.sell_rules as sr
from sab.signals.sell_rules import SellSettings, evaluate_sell_signals


def _patch_atr_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_choose_eval_index(data, meta=None, provider=None):
        return len(data) - 1, False

    def fake_ema(values, period):
        return [0.0] * len(values)

    def fake_rsi(values, period):
        return [60.0] * len(values)

    def fake_atr(highs, lows, closes, period):
        return [1.0] * len(closes)

    monkeypatch.setattr(sr, "choose_eval_index", fake_choose_eval_index)
    monkeypatch.setattr(sr, "ema", fake_ema)
    monkeypatch.setattr(sr, "rsi", fake_rsi)
    monkeypatch.setattr(sr, "atr", fake_atr)


def test_atr_trail_uses_peak_close_since_entry_date(monkeypatch: pytest.MonkeyPatch):
    _patch_atr_only(monkeypatch)
    candles = [
        {"date": "20250101", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"date": "20250102", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
        {"date": "20250103", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
        {"date": "20250104", "open": 13, "high": 14, "low": 12, "close": 13, "volume": 1000},
        {"date": "20250105", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
    ]
    holding = {"entry_price": 10.0, "entry_date": "2025-01-03"}
    settings = SellSettings(require_sma200=False, min_bars=3, atr_trail_multiplier=1.0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "SELL"
    assert result.stop_price == pytest.approx(12.0)
    assert "Price hit ATR trailing stop" in result.reasons


def test_atr_trail_falls_back_to_recent_window_when_entry_date_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_atr_only(monkeypatch)
    candles = [
        {"date": "20250101", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"date": "20250102", "open": 11, "high": 12, "low": 10, "close": 11, "volume": 1000},
        {"date": "20250103", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
        {"date": "20250104", "open": 13, "high": 14, "low": 12, "close": 13, "volume": 1000},
        {"date": "20250105", "open": 12, "high": 13, "low": 11, "close": 12, "volume": 1000},
    ]
    holding = {"entry_price": 10.0, "entry_date": None}
    settings = SellSettings(require_sma200=False, min_bars=3, atr_trail_multiplier=1.0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "SELL"
    assert result.stop_price == pytest.approx(12.0)
    assert "Entry date missing/invalid; ATR trail uses recent window" in result.reasons
    assert "Price hit ATR trailing stop" in result.reasons
