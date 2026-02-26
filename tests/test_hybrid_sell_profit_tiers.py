import datetime as dt
from pathlib import Path
from typing import cast

from sab.signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid


def _simple_candles(last_close: float) -> list[dict]:
    return [
        {
            "date": "20250101",
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1,
        },
        {
            "date": "20250102",
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1,
        },
        {
            "date": "20250103",
            "open": last_close,
            "high": last_close,
            "low": last_close,
            "close": last_close,
            "volume": 1,
        },
    ]


def _patch_indicators(monkeypatch):
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.ema", lambda closes, n: [0.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.sma", lambda closes, n: [0.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.rsi", lambda closes, n: [60.0] * len(closes)
    )


def test_hybrid_sell_profit_high_triggers_sell(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(110.0), holding, settings
    )
    assert result.action == "SELL"
    assert any("Reached high profit target" in r for r in result.reasons)


def test_hybrid_sell_profit_target_zone_sets_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(105.0), holding, settings
    )
    assert result.action == "REVIEW"
    assert any("Reached profit target zone" in r for r in result.reasons)
    assert not any("Reached partial profit zone" in r for r in result.reasons)


def test_hybrid_sell_partial_profit_zone_sets_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(103.0), holding, settings
    )
    assert result.action == "REVIEW"
    assert any("Reached partial profit zone" in r for r in result.reasons)
    assert not any("Reached profit target zone" in r for r in result.reasons)


def test_hybrid_sell_profit_below_partial_keeps_hold(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(102.0), holding, settings
    )
    assert result.action == "HOLD"
    assert result.reasons == ["No hybrid sell criteria triggered"]


def test_hybrid_sell_loss_between_min_and_max_sets_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        stop_loss_pct_min=0.03,
        stop_loss_pct_max=0.05,
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "REVIEW"
    assert any("within hard stop band" in r for r in result.reasons)


def test_hybrid_sell_stop_override_triggers_sell(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0, "stop_override": 95.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(94.0), holding, settings
    )

    assert result.action == "SELL"
    assert result.stop_price == 95.0
    assert "Custom stop override in effect" in result.reasons
    assert "Price hit custom stop override" in result.reasons


def test_hybrid_sell_target_override_prioritizes_display_target(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0, "target_override": 123.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(102.0), holding, settings
    )

    assert result.target_price == 123.0
    assert "Custom target override in effect" in result.reasons


def test_hybrid_sell_time_stop_uses_eval_date_not_local_today(monkeypatch):
    class _FixedDate(dt.date):
        @classmethod
        def today(cls) -> "_FixedDate":
            return cls(2025, 1, 15)

    monkeypatch.setattr("sab.signals.hybrid_sell.dt.date", _FixedDate)
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.ema", lambda closes, n: [50.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.sma", lambda closes, n: [50.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.rsi", lambda closes, n: [60.0] * len(closes)
    )

    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=3,
    )
    holding = {"entry_price": 100.0, "entry_date": "2025-01-09"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(100.0), holding, settings
    )

    assert result.action == "HOLD"
    assert result.reasons == ["No hybrid sell criteria triggered"]
    assert result.days_in_trade_sessions == 0
    assert result.time_stop_triggered is False


def test_hybrid_sell_time_stop_skips_when_eval_date_invalid(monkeypatch):
    class _FixedDate(dt.date):
        @classmethod
        def today(cls) -> "_FixedDate":
            return cls(2025, 1, 15)

    monkeypatch.setattr("sab.signals.hybrid_sell.dt.date", _FixedDate)
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.ema", lambda closes, n: [50.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.sma", lambda closes, n: [50.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.rsi", lambda closes, n: [60.0] * len(closes)
    )

    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=3,
    )
    holding = {"entry_price": 100.0, "entry_date": "2025-01-01"}
    candles = [
        {
            "date": "20250101",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "BAD-DATE",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "HOLD"
    assert any(
        "Time stop skipped: invalid eval_date" in reason for reason in result.reasons
    )
    assert result.days_in_trade_sessions is None
    assert result.time_stop_triggered is False


def test_hybrid_sell_corporate_action_guard_adds_flag_without_action_override(
    monkeypatch,
):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 50.0, "entry_date": "2025-01-01"}
    candles = [
        {
            "date": "20250101",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250102",
            "open": 50.0,
            "high": 51.0,
            "low": 49.0,
            "close": 50.0,
            "volume": 1.0,
        },
        {
            "date": "20250103",
            "open": 51.0,
            "high": 52.0,
            "low": 50.0,
            "close": 51.0,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "HOLD"
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("Potential corporate action" in reason for reason in result.reasons)


def test_hybrid_sell_corporate_action_guard_keeps_sell_with_flag(
    monkeypatch,
):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-01",
        "stop_override": 49.0,
    }
    candles = [
        {
            "date": "20250101",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250102",
            "open": 50.0,
            "high": 51.0,
            "low": 49.0,
            "close": 50.0,
            "volume": 1.0,
        },
        {
            "date": "20250103",
            "open": 48.0,
            "high": 49.0,
            "low": 47.0,
            "close": 48.0,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "SELL"
    assert "Price hit custom stop override" in result.reasons
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("Potential corporate action" in reason for reason in result.reasons)


def test_hybrid_sell_time_stop_uses_trading_sessions_not_calendar_days(
    monkeypatch, tmp_path: Path
):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=2,
    )
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-10",
        "currency": "USD",
        "data_dir": tmp_path.as_posix(),
    }
    candles = [
        {
            "date": "20250110",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250113",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "HOLD"
    assert result.days_in_trade_sessions == 1
    assert result.time_stop_triggered is False


def test_hybrid_sell_time_stop_market_unresolved_promotes_hold_to_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=100,
    )
    holding = {"entry_price": 100.0, "entry_date": "2025-01-10"}
    candles = [
        {
            "date": "20250110",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250113",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "TEST", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "REVIEW"
    assert any(
        "Time stop skipped: unable to resolve holding market" in reason
        for reason in result.reasons
    )
    assert result.days_in_trade_sessions is None
    assert result.time_stop_triggered is False


def test_hybrid_sell_time_stop_market_unresolved_keeps_sell_action(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=100,
    )
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-10",
        "stop_override": 95.0,
    }
    candles = [
        {
            "date": "20250110",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250113",
            "open": 94.0,
            "high": 95.0,
            "low": 93.0,
            "close": 94.0,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "TEST", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "SELL"
    assert "Price hit custom stop override" in result.reasons
    assert any(
        "Time stop skipped: unable to resolve holding market" in reason
        for reason in result.reasons
    )
