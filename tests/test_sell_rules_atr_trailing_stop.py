from __future__ import annotations

import datetime as dt

import pytest
import sab.signals.sell_rules as sr
from sab.signals.sell_rules import Candle, SellSettings, evaluate_sell_signals


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
    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250102",
            "open": 11,
            "high": 12,
            "low": 10,
            "close": 11,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 12,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 1000,
        },
        {
            "date": "20250104",
            "open": 13,
            "high": 14,
            "low": 12,
            "close": 13,
            "volume": 1000,
        },
        {
            "date": "20250105",
            "open": 12,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 1000,
        },
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
    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250102",
            "open": 11,
            "high": 12,
            "low": 10,
            "close": 11,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 12,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 1000,
        },
        {
            "date": "20250104",
            "open": 13,
            "high": 14,
            "low": 12,
            "close": 13,
            "volume": 1000,
        },
        {
            "date": "20250105",
            "open": 12,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 10.0, "entry_date": None}
    settings = SellSettings(require_sma200=False, min_bars=3, atr_trail_multiplier=1.0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "SELL"
    assert result.stop_price == pytest.approx(12.0)
    assert "Entry date missing/invalid; ATR trail uses recent window" in result.reasons
    assert "Price hit ATR trailing stop" in result.reasons


def test_stop_override_triggers_sell_when_close_below_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250102",
            "open": 99,
            "high": 100,
            "low": 97,
            "close": 98,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 98,
            "high": 99,
            "low": 95,
            "close": 96,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 100.0, "entry_date": "2025-01-01", "stop_override": 97.0}
    settings = SellSettings(require_sma200=False, min_bars=3, time_stop_days=0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "SELL"
    assert result.stop_price == pytest.approx(97.0)
    assert "Custom stop override in effect" in result.reasons
    assert "Price hit custom stop override" in result.reasons


def test_stop_override_keeps_non_sell_when_close_above_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250102",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 100.0, "entry_date": "2025-01-01", "stop_override": 95.0}
    settings = SellSettings(require_sma200=False, min_bars=3, time_stop_days=0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "HOLD"
    assert result.stop_price == pytest.approx(95.0)
    assert "Custom stop override in effect" in result.reasons
    assert "Price hit custom stop override" not in result.reasons


def test_time_stop_uses_eval_date_instead_of_local_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedDate(dt.date):
        @classmethod
        def today(cls) -> _FixedDate:
            return cls(2025, 1, 15)

    monkeypatch.setattr(sr.dt, "date", _FixedDate)
    monkeypatch.setattr(
        sr,
        "choose_eval_index",
        lambda data, meta=None, provider=None: (len(data) - 1, False),
    )
    monkeypatch.setattr(sr, "ema", lambda values, period: [90.0] * len(values))
    monkeypatch.setattr(sr, "rsi", lambda values, period: [60.0] * len(values))
    monkeypatch.setattr(
        sr, "atr", lambda highs, lows, closes, period: [0.0] * len(closes)
    )

    candles: list[Candle] = [
        {
            "date": "20250108",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250109",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250110",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 100.0, "entry_date": "2025-01-09"}
    settings = SellSettings(
        require_sma200=False,
        min_bars=2,
        ema_lengths=(2, 3),
        time_stop_days=3,
    )

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "HOLD"
    assert result.reasons == ["No sell criteria triggered"]


def test_time_stop_skips_when_eval_date_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FixedDate(dt.date):
        @classmethod
        def today(cls) -> _FixedDate:
            return cls(2025, 1, 15)

    monkeypatch.setattr(sr.dt, "date", _FixedDate)
    monkeypatch.setattr(
        sr,
        "choose_eval_index",
        lambda data, meta=None, provider=None: (len(data) - 1, False),
    )
    monkeypatch.setattr(sr, "ema", lambda values, period: [90.0] * len(values))
    monkeypatch.setattr(sr, "rsi", lambda values, period: [60.0] * len(values))
    monkeypatch.setattr(
        sr, "atr", lambda highs, lows, closes, period: [0.0] * len(closes)
    )

    candles: list[Candle] = [
        {
            "date": "20250108",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "BAD-DATE",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 100.0, "entry_date": "2025-01-01"}
    settings = SellSettings(
        require_sma200=False,
        min_bars=2,
        ema_lengths=(2, 3),
        time_stop_days=3,
    )

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "HOLD"
    assert any(
        "Time stop skipped: invalid eval_date" in reason for reason in result.reasons
    )


def test_corporate_action_guard_returns_review(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250102",
            "open": 50,
            "high": 51,
            "low": 49,
            "close": 50,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 51,
            "high": 52,
            "low": 50,
            "close": 51,
            "volume": 1000,
        },
    ]
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-01",
        "stop_override": 1.0,
    }
    settings = SellSettings(require_sma200=False, min_bars=3, time_stop_days=0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "REVIEW"
    assert any("Potential corporate action" in reason for reason in result.reasons)


def test_corporate_action_guard_downgrades_sell_signal_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250102",
            "open": 50,
            "high": 51,
            "low": 49,
            "close": 50,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 48,
            "high": 49,
            "low": 47,
            "close": 48,
            "volume": 1000,
        },
    ]
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-01",
        "stop_override": 49.0,
    }
    settings = SellSettings(require_sma200=False, min_bars=3, time_stop_days=0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "REVIEW"
    assert "Price hit custom stop override" in result.reasons
    assert any("Potential corporate action" in reason for reason in result.reasons)
