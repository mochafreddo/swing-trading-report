from sab.signals.hybrid_buy import (
    HybridEvaluationSettings,
    HybridPattern,
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


def test_pullback_bounce_watch(monkeypatch):
    candles = _simple_candles(10)

    # Eval index to last candle
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index", lambda data, **_: (len(data) - 1, True)
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
            {"trigger_hammer_near_ema": True, "rsi_val": 49.0, "close_above_ema_short": False},
        ),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout", lambda *a, **k: (False, [], None, {})
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *a, **k: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(), {"currency": "USD"})
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.TREND_PULLBACK_BOUNCE
    assert result.candidate["entry_state"] == "WATCH"
    assert "wait" in result.candidate["entry_state_reason"].lower()
    assert result.candidate["gap_guard_pct"].startswith("±")
    # Risk guide should be populated
    assert "Target" in result.candidate["risk_guide"]


def test_pullback_bounce_ready(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index", lambda data, **_: (len(data) - 1, True)
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
        "sab.signals.hybrid_buy._detect_swing_high_breakout", lambda *a, **k: (False, [], None, {})
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_rsi_oversold_reversal",
        lambda *a, **k: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(), {"currency": "USD"})
    assert result.candidate is not None
    assert result.candidate["entry_state"] == "READY"
    assert "bounce confirmed" in result.candidate["entry_state_reason"].lower()


def test_breakout_extended_sets_watch(monkeypatch):
    candles = _simple_candles(10, base=100.0)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index", lambda data, **_: (len(data) - 1, True)
    )
    # ATR=2 ensures last_close (approx 104.3) > swing_high(100)+ATR => extended
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [2.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *a, **k: (False, [], None, {}),
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
        lambda *a, **k: (False, [], None, {}),
    )

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(), {"currency": "USD"})
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.SWING_HIGH_BREAKOUT
    assert result.candidate["entry_state"] == "WATCH"
    assert "extended" in result.candidate["entry_state_reason"].lower()


def test_rsi_oversold_ready(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index", lambda data, **_: (len(data) - 1, True)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.5] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *a, **k: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout", lambda *a, **k: (False, [], None, {})
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

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(), {"currency": "USD"})
    assert result.candidate is not None
    assert result.candidate["pattern"] == HybridPattern.RSI_OVERSOLD_REVERSAL
    assert result.candidate["entry_state"] == "READY"


def test_rsi_oversold_watch(monkeypatch):
    candles = _simple_candles(10)
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.choose_eval_index", lambda data, **_: (len(data) - 1, True)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy.atr", lambda highs, lows, closes, n: [1.5] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_trend_pullback_bounce",
        lambda *a, **k: (False, [], None, {}),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_buy._detect_swing_high_breakout", lambda *a, **k: (False, [], None, {})
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

    result = evaluate_ticker_hybrid("FAKE.US", candles, _settings(), {"currency": "USD"})
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
        "sab.signals.hybrid_buy.choose_eval_index", lambda data, **_: (len(data) - 1, True)
    )

    settings = _settings()
    settings.exclude_etf_etn = True

    meta = {"currency": "USD", "name": "Vanguard Total Stock Market ETF"}

    result = evaluate_ticker_hybrid("VTI.AMS", candles, settings, meta)
    assert result.candidate is None
    assert result.reason == "ETF/ETN excluded"
