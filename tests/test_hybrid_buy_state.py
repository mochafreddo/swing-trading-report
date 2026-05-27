import math

from sab.signals.hybrid_buy import (
    HybridEvaluationSettings,
    HybridPattern,
    _detect_rsi_oversold_reversal,
    _detect_swing_high_breakout,
    _detect_trend_pullback_bounce,
    evaluate_ticker_hybrid,
)


def _simple_candles(n: int, base: float = 100.0) -> list[dict]:
    """Builds a small list of candles with gently rising prices/volume."""
    candles = []
    for i in range(n):
        o = base + i * 0.5
        h = o + 1.0
        low = o - 1.0
        c = o + 0.2
        v = 1_000_000 + i * 10_000
        candles.append(
            {
                "date": f"202501{10 + i:02d}",
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v,
            }
        )
    return candles


def _settings(min_history: int = 5) -> HybridEvaluationSettings:
    return HybridEvaluationSettings(
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
        gap_atr_multiplier=1.0,
        min_history_bars=min_history,
        min_price=0.0,
        us_min_price=0.0,
        min_dollar_volume=0.0,
        us_min_dollar_volume=0.0,
        exclude_etf_etn=False,
    )


def _kr_breakout_confirmation_candles(
    *,
    second_open: float = 101.2,
    second_high: float = 102.0,
    second_low: float = 100.8,
    second_close: float = 101.5,
    second_volume: float = 55.0,
) -> list[dict]:
    candles = [
        {
            "date": f"202501{idx + 1:02d}",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 50.0,
        }
        for idx in range(5)
    ]
    candles.append(
        {
            "date": "20250106",
            "open": 101.0,
            "high": 104.0,
            "low": 100.5,
            "close": 102.0,
            "volume": 80.0,
        }
    )
    candles.append(
        {
            "date": "20250107",
            "open": second_open,
            "high": second_high,
            "low": second_low,
            "close": second_close,
            "volume": second_volume,
        }
    )
    return candles


def _patch_kr_breakout_confirmation_indicators(
    monkeypatch,
    *,
    rsi_tail: tuple[float, float] | None = None,
    atr_value: float = 1.0,
) -> None:
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.sma", lambda values, n: [95.0] * len(values)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.ema",
        lambda values, n: [101.0] * len(values) if n == 2 else [100.0] * len(values),
    )

    def rsi_values(values, n):
        if rsi_tail is None:
            return [55.0] * len(values)
        tail = list(rsi_tail)[-len(values) :]
        return [55.0] * max(len(values) - len(tail), 0) + tail

    monkeypatch.setattr("sab.signals.hybrid_buy.rsi", rsi_values)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [atr_value] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )


def test_pullback_bounce_watch(monkeypatch):
    candles = _simple_candles(10)

    # Eval index to last candle
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )

    # Make ATR deterministic
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [2.0] * len(closes)
    )

    # Force pullback pattern with only hammer trigger and no EMA reclaim / RSI>50
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Reversal candle near EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_hammer_near_ema": True,
                "rsi_val": 49.0,
                "close_above_ema_short": False,
            },
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.TREND_PULLBACK_BOUNCE
    assert result.candidate["entry_state"] == "WATCH"
    assert "wait" in result.candidate["entry_state_reason"].lower()
    assert result.candidate["gap_guard_pct"].startswith("±")
    assert result.candidate["close_value"] == result.candidate["price_value"]
    assert result.candidate["signal_price_basis"] == "adjusted"
    assert (
        result.candidate["signal_close_adjusted_value"]
        == result.candidate["close_value"]
    )
    assert result.candidate["atr14_value"] == 2.0
    assert result.candidate["gap_guard_pct_value"] is not None
    assert result.candidate["gap_guard_up_price_value"] is not None
    assert result.candidate["gap_guard_down_price_value"] is not None
    # Risk guide should be populated
    assert "Target" in result.candidate["risk_guide"]


def test_pullback_bounce_hammer_without_ema_reclaim_stays_watch(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Reversal candle near EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_hammer_near_ema": True,
                "rsi_val": 51.0,
                "close_above_ema_short": False,
            },
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )

    assert result.candidate is not None
    assert result.candidate["entry_state"] == "WATCH"
    assert "wait" in result.candidate["entry_state_reason"].lower()
    assert result.candidate["entry_trigger_price_value"] is None


def test_pullback_bounce_ready(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short", "RSI crossed above 50"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_rsi50": True,
                "rsi_val": 51.0,
                "close_above_ema_short": True,
            },
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )
    assert result.candidate is not None
    assert result.candidate["entry_state"] == "READY"
    assert "bounce confirmed" in result.candidate["entry_state_reason"].lower()


def test_hybrid_candidate_exposes_structured_reasons(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short", "RSI crossed above 50"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_rsi50": True,
                "rsi_val": 51.0,
                "close_above_ema_short": True,
            },
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )
    assert result.candidate is not None
    reasons = result.candidate["reasons"]
    assert isinstance(reasons, list)
    ids = {str(item.get("id")) for item in reasons}
    assert {
        "pattern_trend_pullback_bounce",
        "entry_state_ready",
        "trigger_close_reclaimed_ema_short",
        "trigger_rsi_crossed_above_50",
    }.issubset(ids)


def test_hybrid_score_prioritizes_ready_with_confirmation(monkeypatch):
    candles = _simple_candles(10, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [2.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Bullish candle with rising volume"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_bullish_vol": True,
                "rsi_val": 55.0,
                "close_above_ema_short": True,
                "avg_vol": 1_000_000.0,
            },
        ),
    )
    ready_result = evaluate_ticker_hybrid(
        "READY.US", candles, _settings(), {"currency": "USD"}
    )
    assert ready_result.candidate is not None
    assert ready_result.candidate["entry_state"] == "READY"

    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *args, **kwargs: (
            True,
            ["Close broke above recent swing high with volume > 5d avg"],
            HybridPattern.SWING_HIGH_BREAKOUT,
            {"swing_high": 95.0, "avg_vol": 5_000_000.0},
        ),
    )
    watch_result = evaluate_ticker_hybrid(
        "WATCH.US", candles, _settings(), {"currency": "USD"}
    )
    assert watch_result.candidate is not None
    assert watch_result.candidate["entry_state"] == "WATCH"
    assert ready_result.candidate["score_value"] > watch_result.candidate["score_value"]
    assert "entry_state=" in ready_result.candidate["score_notes"]


def test_hybrid_buy_non_finite_ohlc_returns_system_issue(monkeypatch):
    candles = _simple_candles(10)
    candles[-1]["high"] = math.inf

    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(min_history=2), {"currency": "USD"}
    )

    assert result.candidate is None
    assert result.reason == "Invalid candle data: non-finite OHLC values"
    assert result.reason_kind == "system"


def test_breakout_extended_sets_watch(monkeypatch):
    candles = _simple_candles(10, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    # ATR=2 ensures last_close (approx 104.3) > swing_high(100)+ATR => extended
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [2.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *args, **kwargs: (
            True,
            ["Close broke above recent swing high with volume > 5d avg"],
            HybridPattern.SWING_HIGH_BREAKOUT,
            {"swing_high": 100.0},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.SWING_HIGH_BREAKOUT
    assert result.candidate["entry_state"] == "WATCH"
    assert "extended" in result.candidate["entry_state_reason"].lower()


def test_rsi_oversold_ready(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.5] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *args, **kwargs: (
            True,
            ["Reversal off EMA short/mid with volume"],
            HybridPattern.RSI_OVERSOLD_REVERSAL,
            {"rsi_val": 50.0, "close_above_ema_short": True},
        ),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.RSI_OVERSOLD_REVERSAL
    assert result.candidate["entry_state"] == "READY"


def test_rsi_oversold_watch(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.5] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *args, **kwargs: (
            True,
            ["Reversal off EMA short/mid with volume"],
            HybridPattern.RSI_OVERSOLD_REVERSAL,
            {"rsi_val": 42.0, "close_above_ema_short": False},
        ),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(), {"currency": "USD"}
    )
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.RSI_OVERSOLD_REVERSAL
    assert result.candidate["entry_state"] == "WATCH"
    assert (
        "need rsi" in result.candidate["entry_state_reason"].lower()
        or "need rsi" in result.candidate["entry_state_reason"]
    )


def test_hybrid_evaluator_excludes_etf_when_flag_true(monkeypatch):
    candles = _simple_candles(10)

    # Evaluate on the last candle.
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )

    settings = _settings()
    settings.exclude_etf_etn = True

    meta = {"currency": "USD", "name": "Vanguard Total Stock Market ETF"}

    result = evaluate_ticker_hybrid("VTI.AMS", candles, settings, meta)
    assert result.candidate is None
    assert result.reason == "ETF/ETN excluded"


def test_pullback_heavy_selling_check_skips_when_no_pullback() -> None:
    settings = _settings()
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    sma_trend = [9.0, 10.0, 11.0, 12.0, 13.0]
    ema_short = [9.0, 10.0, 11.0, 12.0, 13.0]
    ema_mid = [8.0, 9.0, 10.0, 11.0, 12.0]
    rsi_vals = [45.0, 47.0, 49.0, 51.0, 53.0]
    candles = [
        {"open": 15.0, "close": 10.0, "low": 9.0, "volume": 10_000_000.0},
        {"open": 11.0, "close": 11.0, "low": 10.0, "volume": 1_000_000.0},
        {"open": 12.0, "close": 12.0, "low": 11.0, "volume": 1_000_000.0},
        {"open": 13.0, "close": 13.0, "low": 12.0, "volume": 1_000_000.0},
        {"open": 13.5, "close": 14.0, "low": 13.0, "volume": 1_100_000.0},
    ]

    ok, reasons, _, _ = _detect_trend_pullback_bounce(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )
    assert not (ok is False and reasons == ["Heavy selling volume during pullback"])


def test_pullback_bounce_requires_actual_pullback_bars() -> None:
    settings = _settings()
    closes = [10.0, 11.0, 12.0, 13.0, 14.0]
    sma_trend = [9.0, 10.0, 11.0, 12.0, 13.0]
    ema_short = [8.0, 9.0, 10.0, 11.0, 12.0]
    ema_mid = [7.0, 8.0, 9.0, 10.0, 11.0]
    rsi_vals = [45.0, 48.0, 50.0, 52.0, 54.0]
    candles = [
        {"open": 10.0, "close": 10.0, "low": 9.0, "volume": 1_000_000.0},
        {"open": 11.0, "close": 11.0, "low": 10.0, "volume": 1_000_000.0},
        {"open": 12.0, "close": 12.0, "low": 11.0, "volume": 1_000_000.0},
        {"open": 13.0, "close": 13.0, "low": 12.0, "volume": 1_000_000.0},
        {"open": 14.0, "close": 14.0, "low": 13.0, "volume": 1_200_000.0},
    ]

    ok, reasons, _, _ = _detect_trend_pullback_bounce(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert ok is False
    assert reasons == ["No pullback bars near EMA short"]


def test_pullback_bounce_accepts_reclaim_after_prior_pullback() -> None:
    settings = _settings()
    closes = [100.0, 99.0, 98.0, 99.0, 101.0]
    sma_trend = [95.0, 95.0, 95.0, 95.0, 95.0]
    ema_short = [100.5, 100.0, 99.5, 99.2, 100.0]
    ema_mid = [99.0, 99.0, 99.0, 99.0, 99.0]
    rsi_vals = [46.0, 47.0, 48.0, 49.0, 52.0]
    candles = [
        {"open": 100.5, "close": 100.0, "low": 99.0, "volume": 1_000_000.0},
        {"open": 99.5, "close": 99.0, "low": 98.0, "volume": 1_000_000.0},
        {"open": 98.5, "close": 98.0, "low": 97.5, "volume": 1_000_000.0},
        {"open": 99.2, "close": 99.0, "low": 98.5, "volume": 1_000_000.0},
        {"open": 99.5, "close": 101.0, "low": 99.0, "volume": 1_200_000.0},
    ]

    ok, reasons, pattern, _ = _detect_trend_pullback_bounce(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert ok is True
    assert pattern == HybridPattern.TREND_PULLBACK_BOUNCE
    assert "Close reclaimed EMA short" in reasons


def test_hybrid_respects_max_gap_pct(monkeypatch):
    candles = _simple_candles(10)
    candles[-2]["close"] = 100.0
    candles[-1]["open"] = 120.0
    candles[-1]["close"] = 121.0

    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["stub"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {"rsi_val": 55.0, "close_above_ema_short": True},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    settings = _settings()
    settings.max_gap_pct = 0.05
    result = evaluate_ticker_hybrid(
        "FAKE.US",
        candles,
        settings,
        {"currency": "USD"},
    )
    assert result.candidate is None
    assert result.reason is not None
    assert "HYBRID_MAX_GAP_PCT" in result.reason


def test_hybrid_respects_sma60_filter(monkeypatch):
    candles = [
        {
            "date": "20250101",
            "open": 110.0,
            "high": 111.0,
            "low": 109.0,
            "close": 110.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250102",
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250103",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        },
    ]
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["stub"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {"rsi_val": 55.0, "close_above_ema_short": True},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    settings = _settings(min_history=3)
    settings.use_sma60_filter = True
    settings.sma60_period = 3
    result = evaluate_ticker_hybrid("FAKE.KR", candles, settings, {"currency": "KRW"})
    assert result.candidate is None
    assert result.reason is not None
    assert "SMA3" in result.reason


def test_hybrid_kr_breakout_confirmation_watch(monkeypatch):
    candles = _simple_candles(6, base=90.0)
    candles[-2]["close"] = 99.0
    candles[-1]["open"] = 100.0
    candles[-1]["close"] = 100.5

    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [1.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *args, **kwargs: (
            True,
            ["breakout"],
            HybridPattern.SWING_HIGH_BREAKOUT,
            {"swing_high": 100.0},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    settings = _settings(min_history=3)
    settings.kr_breakout_requires_confirmation = True
    result = evaluate_ticker_hybrid("FAKE.KR", candles, settings, {"currency": "KRW"})
    assert result.candidate is not None
    assert result.candidate["entry_state"] == "WATCH"
    assert "confirmation" in result.candidate["entry_state_reason"].lower()


def test_hybrid_breakout_candidate_exposes_entry_trigger_guard(monkeypatch):
    candles = _simple_candles(6, base=90.0)
    candles[-2]["close"] = 99.0
    candles[-1]["open"] = 100.0
    candles[-1]["close"] = 100.5

    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [1.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *args, **kwargs: (
            True,
            ["breakout"],
            HybridPattern.SWING_HIGH_BREAKOUT,
            {"swing_high": 100.0},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    settings = _settings(min_history=3)
    settings.kr_breakout_requires_confirmation = False
    result = evaluate_ticker_hybrid("FAKE.KR", candles, settings, {"currency": "KRW"})

    assert result.candidate is not None
    assert result.candidate["entry_trigger_price_value"] == 100.0
    assert result.candidate["entry_trigger_price_basis"] == "adjusted"
    assert result.candidate["entry_trigger_operator"] == "gte"
    assert result.candidate["entry_trigger_label"] == "swing_high"


def test_hybrid_kr_breakout_second_close_confirms_original_swing_high(monkeypatch):
    candles = _kr_breakout_confirmation_candles()
    _patch_kr_breakout_confirmation_indicators(monkeypatch)

    settings = _settings(min_history=5)
    settings.kr_breakout_requires_confirmation = True
    result = evaluate_ticker_hybrid("005930", candles, settings, {"currency": "KRW"})

    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.SWING_HIGH_BREAKOUT
    assert result.candidate["entry_state"] == "READY"
    assert result.candidate["entry_trigger_price_value"] == 101.0
    assert "confirmed" in result.candidate["pattern_reasons"].lower()


def test_hybrid_kr_breakout_second_close_prefers_original_swing_high(monkeypatch):
    candles = _kr_breakout_confirmation_candles(
        second_open=104.2,
        second_high=105.0,
        second_low=103.8,
        second_close=104.5,
        second_volume=100.0,
    )
    _patch_kr_breakout_confirmation_indicators(monkeypatch, atr_value=10.0)

    settings = _settings(min_history=5)
    settings.kr_breakout_requires_confirmation = True
    result = evaluate_ticker_hybrid("005930", candles, settings, {"currency": "KRW"})

    assert result.candidate is not None
    assert result.candidate["entry_state"] == "READY"
    assert result.candidate["entry_trigger_price_value"] == 101.0
    assert "confirmed" in result.candidate["pattern_reasons"].lower()


def test_hybrid_kr_breakout_confirmation_requires_prior_bar_eligibility(monkeypatch):
    candles = _kr_breakout_confirmation_candles()
    _patch_kr_breakout_confirmation_indicators(monkeypatch, rsi_tail=(65.0, 55.0))

    settings = _settings(min_history=5)
    settings.kr_breakout_requires_confirmation = True
    result = evaluate_ticker_hybrid("005930", candles, settings, {"currency": "KRW"})

    assert result.candidate is None


def test_hybrid_kr_breakout_confirmation_uses_prior_bar_rsi_cap(monkeypatch):
    candles = _kr_breakout_confirmation_candles()
    _patch_kr_breakout_confirmation_indicators(monkeypatch, rsi_tail=(55.0, 65.0))

    settings = _settings(min_history=5)
    settings.kr_breakout_requires_confirmation = True
    result = evaluate_ticker_hybrid("005930", candles, settings, {"currency": "KRW"})

    assert result.candidate is not None
    assert result.candidate["entry_state"] == "READY"
    assert result.candidate["entry_trigger_price_value"] == 101.0


def test_hybrid_kr_breakout_confirmation_disabled_allows_ready(monkeypatch):
    candles = _simple_candles(6, base=90.0)
    candles[-2]["close"] = 99.0
    candles[-1]["open"] = 100.0
    candles[-1]["close"] = 100.5

    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [1.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *args, **kwargs: (
            True,
            ["breakout"],
            HybridPattern.SWING_HIGH_BREAKOUT,
            {"swing_high": 100.0},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    settings = _settings(min_history=3)
    settings.kr_breakout_requires_confirmation = False
    result = evaluate_ticker_hybrid("FAKE.KR", candles, settings, {"currency": "KRW"})
    assert result.candidate is not None
    assert result.candidate["entry_state"] == "READY"


def test_hybrid_rejects_non_finite_volume_as_system_issue(monkeypatch):
    candles = _simple_candles(10)
    candles[-1]["volume"] = "N/A"

    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US", candles, _settings(min_history=2), {"currency": "USD"}
    )

    assert result.candidate is None
    assert result.reason == "Invalid candle data: non-finite volume values"
    assert result.reason_kind == "system"


def test_pullback_bounce_handles_zero_close_without_crash() -> None:
    settings = _settings()
    closes = [1.0, 0.0]
    sma_trend = [0.5, -1.0]
    ema_short = [0.4, -0.1]
    ema_mid = [0.3, -0.2]
    rsi_vals = [49.0, 51.0]
    candles = [
        {"open": 1.0, "close": 1.0, "low": 0.9, "volume": 10.0},
        {"open": 1.0, "close": 0.0, "low": -2.0, "volume": 10.0},
    ]

    ok, reasons, pattern, _ = _detect_trend_pullback_bounce(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert isinstance(ok, bool)
    assert isinstance(reasons, list)
    assert pattern in {None, HybridPattern.TREND_PULLBACK_BOUNCE}


def test_rsi_oversold_reversal_handles_zero_close_without_crash() -> None:
    settings = _settings()
    closes = [1.0, 0.0]
    sma_trend = [0.5, -1.0]
    ema_short = [0.4, -0.1]
    ema_mid = [0.3, -0.2]
    rsi_vals = [35.0, 41.0]
    candles = [
        {"open": 1.0, "close": 1.0, "low": 0.9, "volume": 10.0},
        {"open": -1.0, "close": 0.0, "low": -3.0, "volume": 10.0},
    ]

    ok, reasons, pattern, _ = _detect_rsi_oversold_reversal(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )

    assert isinstance(ok, bool)
    assert isinstance(reasons, list)
    assert pattern in {None, HybridPattern.RSI_OVERSOLD_REVERSAL}


def test_hybrid_candidate_exposes_configured_indicator_period_keys(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [1.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_rsi50": True,
                "rsi_val": 55.0,
                "close_above_ema_short": True,
            },
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    settings = _settings(min_history=2)
    settings.sma_trend_period = 30
    settings.ema_short_period = 8
    settings.ema_mid_period = 34

    result = evaluate_ticker_hybrid("FAKE.US", candles, settings, {"currency": "USD"})

    assert result.candidate is not None
    assert result.candidate["sma_trend_period"] == 30
    assert result.candidate["ema_short_period"] == 8
    assert result.candidate["ema_mid_period"] == 34
    assert result.candidate["sma30"] == result.candidate["sma_trend"]
    assert result.candidate["ema8"] == result.candidate["ema_short"]
    assert result.candidate["ema34"] == result.candidate["ema_mid"]


def test_swing_breakout_uses_pre_breakout_consolidation_range() -> None:
    settings = _settings(min_history=2)
    settings.breakout_consolidation_min_bars = 5
    settings.breakout_consolidation_max_bars = 15

    candles = []
    for idx in range(14):
        candles.append(
            {
                "date": f"202501{idx + 1:02d}",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000.0,
            }
        )
    candles.append(
        {
            "date": "20250115",
            "open": 102.0,
            "high": 110.0,
            "low": 101.0,
            "close": 109.0,
            "volume": 2_000_000.0,
        }
    )

    closes = [100.0] * 14 + [109.0]
    sma_trend = [95.0] * len(candles)
    ema_short = [101.0] * len(candles)
    ema_mid = [100.0] * len(candles)
    rsi_vals = [55.0] * len(candles)

    ok, reasons, pattern, _ = _detect_swing_high_breakout(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
        "USD",
    )

    assert ok is True
    assert reasons
    assert pattern == HybridPattern.SWING_HIGH_BREAKOUT


def test_swing_breakout_volume_check_uses_pre_breakout_average() -> None:
    settings = _settings(min_history=2)
    settings.breakout_consolidation_min_bars = 5
    settings.breakout_consolidation_max_bars = 10
    settings.volume_lookback_days = 5

    candles = [
        {
            "date": "20250101",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 200.0,
        },
        {
            "date": "20250102",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 50.0,
        },
        {
            "date": "20250103",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 50.0,
        },
        {
            "date": "20250104",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 50.0,
        },
        {
            "date": "20250105",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 50.0,
        },
        {
            "date": "20250106",
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.0,
            "volume": 70.0,
        },
    ]
    closes = [100.0, 100.0, 100.0, 100.0, 100.0, 102.0]
    sma_trend = [95.0] * len(candles)
    ema_short = [101.0] * len(candles)
    ema_mid = [100.0] * len(candles)
    rsi_vals = [55.0] * len(candles)

    ok, reasons, pattern, context = _detect_swing_high_breakout(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
        "USD",
    )

    assert ok is False
    assert pattern is None
    assert reasons == ["No confirmed breakout over swing high"]
    assert context["swing_high"] == 101.0


def test_hybrid_candidate_formats_usd_price_with_decimals(monkeypatch):
    candles = _simple_candles(10, base=123.45)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index",
        lambda data, **_: (len(data) - 1, False),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr",
        lambda highs, lows, closes, n: [1.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *args, **kwargs: (
            True,
            ["Close reclaimed EMA short"],
            HybridPattern.TREND_PULLBACK_BOUNCE,
            {
                "trigger_rsi50": True,
                "rsi_val": 55.0,
                "close_above_ema_short": True,
            },
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *_args, **_kwargs: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid(
        "FAKE.US",
        candles,
        _settings(min_history=2),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    assert "." in result.candidate["price"]
