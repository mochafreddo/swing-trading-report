from sab.signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid


def _simple_candles(last_close: float) -> list[dict]:
    return [
        {"date": "20250101", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
        {"date": "20250102", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
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
        "sab.signals.hybrid_sell.choose_eval_index", lambda data, **_: (len(data) - 1, True)
    )
    monkeypatch.setattr("sab.signals.hybrid_sell.ema", lambda closes, n: [0.0] * len(closes))
    monkeypatch.setattr("sab.signals.hybrid_sell.sma", lambda closes, n: [0.0] * len(closes))
    monkeypatch.setattr("sab.signals.hybrid_sell.rsi", lambda closes, n: [60.0] * len(closes))


def test_hybrid_sell_profit_high_triggers_sell(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid("FAKE.US", _simple_candles(110.0), holding, settings)
    assert result.action == "SELL"
    assert any("Reached high profit target" in r for r in result.reasons)


def test_hybrid_sell_profit_target_zone_sets_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid("FAKE.US", _simple_candles(105.0), holding, settings)
    assert result.action == "REVIEW"
    assert any("Reached profit target zone" in r for r in result.reasons)
    assert not any("Reached partial profit zone" in r for r in result.reasons)


def test_hybrid_sell_partial_profit_zone_sets_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid("FAKE.US", _simple_candles(103.0), holding, settings)
    assert result.action == "REVIEW"
    assert any("Reached partial profit zone" in r for r in result.reasons)
    assert not any("Reached profit target zone" in r for r in result.reasons)


def test_hybrid_sell_profit_below_partial_keeps_hold(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid("FAKE.US", _simple_candles(102.0), holding, settings)
    assert result.action == "HOLD"
    assert result.reasons == ["No hybrid sell criteria triggered"]
