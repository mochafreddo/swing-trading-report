from __future__ import annotations

import datetime as dt
from pathlib import Path

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


def test_atr_trail_does_not_loosen_when_latest_atr_spikes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sr, "choose_eval_index", lambda data, meta=None: (len(data) - 1, False)
    )
    monkeypatch.setattr(sr, "ema", lambda values, period: [80.0] * len(values))
    monkeypatch.setattr(sr, "rsi", lambda values, period: [60.0] * len(values))
    monkeypatch.setattr(
        sr,
        "atr",
        lambda highs, lows, closes, period: [2.0, 2.0, 2.0, 2.0, 10.0],
    )

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
            "open": 110,
            "high": 111,
            "low": 109,
            "close": 110,
            "volume": 1000,
        },
        {
            "date": "20250103",
            "open": 120,
            "high": 121,
            "low": 119,
            "close": 120,
            "volume": 1000,
        },
        {
            "date": "20250104",
            "open": 118,
            "high": 119,
            "low": 117,
            "close": 118,
            "volume": 1000,
        },
        {
            "date": "20250105",
            "open": 117,
            "high": 118,
            "low": 116,
            "close": 117,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 100.0, "entry_date": "2025-01-01"}
    settings = SellSettings(require_sma200=False, min_bars=3, atr_trail_multiplier=1.0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "SELL"
    assert result.stop_price == pytest.approx(118.0)
    assert "Price hit ATR trailing stop" in result.reasons


def test_atr_trail_does_not_use_future_peak_with_earlier_atr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sr, "choose_eval_index", lambda data, meta=None: (len(data) - 1, False)
    )
    monkeypatch.setattr(sr, "ema", lambda values, period: [80.0] * len(values))
    monkeypatch.setattr(sr, "rsi", lambda values, period: [60.0] * len(values))
    monkeypatch.setattr(
        sr,
        "atr",
        lambda highs, lows, closes, period: [1.0, 1.0, 20.0],
    )

    candles: list[Candle] = [
        {
            "date": "20250101",
            "open": 90,
            "high": 91,
            "low": 89,
            "close": 90,
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
            "open": 110,
            "high": 111,
            "low": 109,
            "close": 110,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 90.0, "entry_date": "2025-01-01"}
    settings = SellSettings(require_sma200=False, min_bars=3, atr_trail_multiplier=1.0)

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.stop_price == pytest.approx(99.0)


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
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-09",
        "currency": "USD",
    }
    settings = SellSettings(
        require_sma200=False,
        min_bars=2,
        ema_lengths=(2, 3),
        time_stop_days=3,
    )

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "HOLD"
    assert result.reasons == ["No sell criteria triggered"]
    assert result.days_in_trade_sessions == 1
    assert result.time_stop_triggered is False


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
    assert result.days_in_trade_sessions is None
    assert result.time_stop_triggered is False


def test_corporate_action_guard_adds_flag_without_overriding_action(
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

    assert result.action == "HOLD"
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("Potential corporate action" in reason for reason in result.reasons)


def test_corporate_action_guard_keeps_sell_action_with_flag(
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

    assert result.action == "SELL"
    assert "Price hit custom stop override" in result.reasons
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("Potential corporate action" in reason for reason in result.reasons)


def test_time_stop_uses_trading_sessions_not_calendar_days(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250110",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250113",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
    ]
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-10",
        "currency": "USD",
        "data_dir": tmp_path.as_posix(),
    }
    settings = SellSettings(
        require_sma200=False,
        min_bars=2,
        ema_lengths=(2, 3),
        time_stop_days=2,
    )

    result = evaluate_sell_signals("AAPL.NASD", candles, holding, settings)

    assert result.action == "HOLD"
    assert result.days_in_trade_sessions == 1
    assert result.time_stop_triggered is False


def test_time_stop_market_unresolved_promotes_hold_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250110",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250113",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
    ]
    holding = {"entry_price": 100.0, "entry_date": "2025-01-10"}
    settings = SellSettings(
        require_sma200=False,
        min_bars=2,
        ema_lengths=(2, 3),
        time_stop_days=100,
    )

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "REVIEW"
    assert any(
        "Time stop skipped: unable to resolve holding market" in reason
        for reason in result.reasons
    )
    assert result.days_in_trade_sessions is None
    assert result.time_stop_triggered is False


def test_time_stop_market_unresolved_keeps_sell_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_atr_only(monkeypatch)
    candles: list[Candle] = [
        {
            "date": "20250110",
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 1000,
        },
        {
            "date": "20250113",
            "open": 94,
            "high": 95,
            "low": 93,
            "close": 94,
            "volume": 1000,
        },
    ]
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-10",
        "stop_override": 95.0,
    }
    settings = SellSettings(
        require_sma200=False,
        min_bars=2,
        ema_lengths=(2, 3),
        time_stop_days=100,
    )

    result = evaluate_sell_signals("TEST", candles, holding, settings)

    assert result.action == "SELL"
    assert "Price hit custom stop override" in result.reasons
    assert any(
        "Time stop skipped: unable to resolve holding market" in reason
        for reason in result.reasons
    )
