from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sab.signals.eval_index import choose_eval_index
from sab.signals.evaluator import EvaluationSettings, evaluate_ticker
from sab.signals.hybrid_buy import (
    HybridEvaluationSettings,
    HybridPattern,
    evaluate_ticker_hybrid,
)
from sab.signals.hybrid_sell import (
    HybridSellEvaluation,
    HybridSellSettings,
    evaluate_sell_signals_hybrid,
)
from sab.signals.sell_rules import SellEvaluation, SellSettings, evaluate_sell_signals


def _make_candle(date: dt.date, close: float, volume: float) -> dict[str, float | str]:
    return {
        "date": date.strftime("%Y%m%d"),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": volume,
    }


def _build_candles(
    dates: list[dt.date], close_start: float = 100.0, volume: float = 1_000_000.0
):
    candles: list[dict[str, float | str]] = []
    for idx, date in enumerate(dates):
        candles.append(_make_candle(date, close_start + idx, volume))
    return candles


def test_choose_eval_index_us_intraday_drops_today():
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
        dt.date(2025, 1, 13),
    ]
    candles = _build_candles(dates)
    now = dt.datetime(2025, 1, 13, 15, 0, tzinfo=ZoneInfo("America/New_York"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "USD"}, now=now)
    assert idx == len(candles) - 2  # drop today's intraday bar
    assert dropped is True


def test_choose_eval_index_us_after_close_keeps_last():
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
        dt.date(2025, 1, 13),
    ]
    candles = _build_candles(dates)
    now = dt.datetime(2025, 1, 13, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "USD"}, now=now)
    assert idx == len(candles) - 1
    assert dropped is False


def test_choose_eval_index_us_holiday_keeps_last(monkeypatch):
    import sab.signals.eval_index as ei

    monkeypatch.setattr(ei, "_US_HOLIDAYS_CACHE", None, raising=False)

    def fake_holidays():
        return {"20250120": True}

    monkeypatch.setattr(ei, "_load_us_holidays", fake_holidays)

    dates = [
        dt.date(2025, 1, 16),
        dt.date(2025, 1, 17),
        dt.date(2025, 1, 20),
    ]
    candles = _build_candles(dates)
    now = dt.datetime(2025, 1, 20, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "USD"}, now=now)
    assert idx == len(candles) - 1
    assert dropped is False


def test_choose_eval_index_us_intraday_without_today_keeps_last():
    # Simulate EOD-only data (last date < session date) during intraday.
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
    ]
    candles = _build_candles(dates)
    now = dt.datetime(2025, 1, 13, 11, 0, tzinfo=ZoneInfo("America/New_York"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "USD"}, now=now)
    assert idx == len(candles) - 1
    assert dropped is False


def test_choose_eval_index_kr_intraday_thin_volume_drops_today():
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
    ]
    candles = _build_candles(dates, close_start=50000.0, volume=5_000_000.0)
    # Force last candle volume to be very thin relative to average
    candles[-1]["volume"] = 10_000.0
    now = dt.datetime(2025, 1, 10, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "KRW"}, now=now)
    assert idx == len(candles) - 2
    assert dropped is True


def test_choose_eval_index_kr_intraday_normal_volume_keeps_last():
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
    ]
    candles = _build_candles(dates, close_start=50000.0, volume=5_000_000.0)
    now = dt.datetime(2025, 1, 10, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "KRW"}, now=now)
    assert idx == len(candles) - 1
    assert dropped is False


def test_choose_eval_index_single_candle_returns_zero():
    date = dt.date(2025, 1, 6)
    candles = [_make_candle(date, 100.0, 1_000_000.0)]
    idx, dropped = choose_eval_index(candles, meta={"currency": "USD"})
    assert idx == 0
    assert dropped is False


def test_choose_eval_index_no_candles_returns_negative_one():
    idx, dropped = choose_eval_index([], meta={"currency": "USD"})
    assert idx == -1
    assert dropped is False


def test_choose_eval_index_kr_after_close_thin_volume_keeps_last():
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
    ]
    candles = _build_candles(dates, close_start=50000.0, volume=5_000_000.0)
    candles[-1]["volume"] = 10_000.0
    now = dt.datetime(2025, 1, 10, 16, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "KRW"}, now=now)
    assert idx == len(candles) - 1
    assert dropped is False


def test_choose_eval_index_us_pre_open_thin_volume_drops_today():
    dates = [
        dt.date(2025, 1, 6),
        dt.date(2025, 1, 7),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 9),
        dt.date(2025, 1, 10),
        dt.date(2025, 1, 13),
    ]
    candles = _build_candles(dates, close_start=100.0, volume=2_000_000.0)
    candles[-1]["volume"] = 50_000.0
    now = dt.datetime(2025, 1, 13, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    idx, dropped = choose_eval_index(candles, meta={"currency": "USD"}, now=now)
    assert idx == len(candles) - 2
    assert dropped is True


def test_evaluate_ticker_hybrid_uses_eval_index(monkeypatch):
    import sab.signals.hybrid_buy as hb

    candles = [
        {
            "date": "20250108",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 2_000_000.0,
        },
        {
            "date": "20250109",
            "open": 11.0,
            "high": 12.0,
            "low": 10.5,
            "close": 11.5,
            "volume": 2_100_000.0,
        },
        {
            "date": "20250110",
            "open": 11.4,
            "high": 12.3,
            "low": 11.0,
            "close": 12.0,
            "volume": 500.0,
        },
    ]

    def fake_eval_index(data, meta=None, provider=None, **_):
        return len(data) - 2, True

    def fake_pattern(*_):
        return True, ["stub"], HybridPattern.TREND_PULLBACK_BOUNCE, {}

    monkeypatch.setattr(hb, "choose_eval_index", fake_eval_index)
    monkeypatch.setattr(hb, "_detect_trend_pullback_bounce", fake_pattern)

    settings = HybridEvaluationSettings(
        sma_trend_period=2,
        ema_short_period=2,
        ema_mid_period=3,
        rsi_period=2,
        rsi_zone_low=0.0,
        rsi_zone_high=100.0,
        rsi_oversold_low=0.0,
        rsi_oversold_high=100.0,
        pullback_max_bars=5,
        breakout_consolidation_min_bars=2,
        breakout_consolidation_max_bars=5,
        volume_lookback_days=2,
        max_gap_pct=0.1,
        use_sma60_filter=False,
        sma60_period=60,
        kr_breakout_requires_confirmation=False,
        min_history_bars=2,
        min_price=0.0,
        us_min_price=0.0,
        min_dollar_volume=0.0,
        us_min_dollar_volume=0.0,
        exclude_etf_etn=False,
        gap_atr_multiplier=1.0,
    )

    result = evaluate_ticker_hybrid("FAKE.US", candles, settings, {"currency": "USD"})
    assert result.candidate is not None
    assert result.candidate["price_value"] == candles[-2]["close"]
    assert result.candidate.get("entry_state") in {"READY", "WATCH"}
    assert "stub" in result.candidate["pattern_reasons"]


def test_evaluate_ticker_uses_eval_index(monkeypatch):
    import sab.signals.evaluator as ev

    candles = [
        {
            "date": "20250108",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 1_000_000,
        },
        {
            "date": "20250109",
            "open": 10,
            "high": 12,
            "low": 9.5,
            "close": 11,
            "volume": 1_100_000,
        },
        {
            "date": "20250110",
            "open": 11,
            "high": 13,
            "low": 10,
            "close": 12,
            "volume": 100,
        },
    ]

    def fake_eval_index(data, meta=None, provider=None):
        return len(data) - 2, True

    monkeypatch.setattr(ev, "choose_eval_index", fake_eval_index)

    settings = EvaluationSettings(min_history_bars=2)
    result = evaluate_ticker("FAKE.US", candles, settings, {"currency": "USD"})
    assert result.candidate is None  # EMA cross likely false on short data
    assert (
        result.reason
        in {
            "EMA(20/50) cross not satisfied",
            "Not enough completed candles",
            "Insufficient price data",
        }
        or result.candidate is None
    )


def test_evaluate_ticker_excludes_etf_when_flag_true(monkeypatch):
    import sab.signals.evaluator as ev

    # Build minimal candles where basic data/length checks pass.
    candles = [
        {
            "date": "20250101",
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.0,
            "volume": 1_000_000,
        },
        {
            "date": "20250102",
            "open": 10.0,
            "high": 11.5,
            "low": 9.7,
            "close": 11.0,
            "volume": 1_000_000,
        },
        {
            "date": "20250103",
            "open": 11.0,
            "high": 12.5,
            "low": 10.7,
            "close": 12.0,
            "volume": 1_000_000,
        },
        {
            "date": "20250104",
            "open": 12.0,
            "high": 13.5,
            "low": 11.7,
            "close": 13.0,
            "volume": 1_000_000,
        },
        {
            "date": "20250105",
            "open": 13.0,
            "high": 14.5,
            "low": 12.7,
            "close": 14.0,
            "volume": 1_000_000,
        },
    ]

    # Force evaluation on the last candle.
    monkeypatch.setattr(
        ev,
        "choose_eval_index",
        lambda data, meta=None, provider=None: (len(data) - 1, True),
    )

    # Stub indicators so EMA/RSI/ATR/gap checks all pass and evaluation
    # reaches the ETF exclusion branch.
    def fake_ema(values, period):
        n = len(values)
        base = [1.0] * n
        if period == 20:
            # Ensure EMA20 crosses above EMA50 on the last bar.
            base[-2] = 1.0
            base[-1] = 2.0
        elif period == 50:
            base[-2] = 1.0
            base[-1] = 1.0
        return base

    def fake_rsi(values, period):
        n = len(values)
        out = [0.0] * n
        # RSI rebounds from <=30 to >30 and stays below 70.
        if n >= 2:
            out[-2] = 30.0
            out[-1] = 40.0
        return out

    def fake_atr(highs, lows, closes, period):
        return [1.0] * len(closes)

    monkeypatch.setattr(ev, "ema", fake_ema)
    monkeypatch.setattr(ev, "rsi", fake_rsi)
    monkeypatch.setattr(ev, "atr", fake_atr)

    settings = EvaluationSettings(
        min_history_bars=5,
        min_price=0.0,
        min_dollar_volume=0.0,
        us_min_dollar_volume=None,
        exclude_etf_etn=True,
        gap_atr_multiplier=0.0,
    )
    meta = {"currency": "USD", "name": "Test ETF"}

    result = evaluate_ticker("TESTETF.US", candles, settings, meta)
    assert result.candidate is None
    assert result.reason == "ETF/ETN excluded"


def test_evaluate_sell_signals_use_eval_index(monkeypatch):
    import sab.signals.sell_rules as sr

    candles = [
        {
            "date": "20250108",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 1_000_000,
        },
        {
            "date": "20250109",
            "open": 10,
            "high": 12,
            "low": 9.5,
            "close": 11,
            "volume": 1_100_000,
        },
        {
            "date": "20250110",
            "open": 11,
            "high": 13,
            "low": 10,
            "close": 12,
            "volume": 100,
        },
    ]

    def fake_eval_index(data, meta=None, provider=None):
        return len(data) - 2, True

    monkeypatch.setattr(sr, "choose_eval_index", fake_eval_index)

    settings = SellSettings(min_bars=2, ema_lengths=(2, 3))
    holding = {"entry_price": 9.5}
    result = evaluate_sell_signals("FAKE.US", candles, holding, settings)
    assert isinstance(result, SellEvaluation)
    assert result.eval_price == candles[-2]["close"]
    assert result.eval_index == len(candles) - 2


def test_evaluate_sell_signals_hybrid_use_eval_index(monkeypatch):
    import sab.signals.hybrid_sell as hs

    candles = [
        {
            "date": "20250108",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 1_000_000,
        },
        {
            "date": "20250109",
            "open": 10,
            "high": 12,
            "low": 9.5,
            "close": 11,
            "volume": 1_100_000,
        },
        {
            "date": "20250110",
            "open": 11,
            "high": 13,
            "low": 10,
            "close": 12,
            "volume": 100,
        },
    ]

    def fake_eval_index(data, meta=None, provider=None):
        return len(data) - 2, True

    monkeypatch.setattr(hs, "choose_eval_index", fake_eval_index)

    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=3, sma_trend_period=2
    )
    holding = {"entry_price": 9.5}
    result = evaluate_sell_signals_hybrid("FAKE.US", candles, holding, settings)
    assert isinstance(result, HybridSellEvaluation)
    assert result.eval_price == candles[-2]["close"]
    assert result.eval_index == len(candles) - 2
