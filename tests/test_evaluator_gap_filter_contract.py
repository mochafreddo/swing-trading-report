from __future__ import annotations

import pytest
import sab.signals.evaluator as ev


def _candles_for_gap_test() -> list[dict[str, float | str]]:
    return [
        {
            "date": "20250106",
            "open": 95.0,
            "high": 101.0,
            "low": 94.0,
            "close": 100.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250107",
            "open": 99.0,
            "high": 102.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 1_100_000.0,
        },
        {
            "date": "20250108",
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_200_000.0,
        },
        {
            "date": "20250109",
            "open": 100.0,
            "high": 104.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_300_000.0,
        },
        {
            "date": "20250110",
            "open": 110.0,
            "high": 111.0,
            "low": 109.0,
            "close": 110.0,
            "volume": 1_400_000.0,
        },
    ]


def test_gap_filter_uses_pre_signal_atr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ev,
        "choose_eval_index",
        lambda data, meta=None: (len(data) - 1, False),
    )

    def _ema(values: list[float], period: int) -> list[float]:
        if period == 20:
            return [1.0, 1.0, 1.0, 1.0, 2.0]
        return [1.0, 1.0, 1.0, 1.0, 1.0]

    monkeypatch.setattr(ev, "ema", _ema)
    monkeypatch.setattr(
        ev, "rsi", lambda values, period: [25.0, 25.0, 25.0, 30.0, 40.0]
    )
    # ATR spikes on signal bar. Gap filter must use ATR from t-1 to avoid self-relaxation.
    monkeypatch.setattr(
        ev,
        "atr",
        lambda highs, lows, closes, period: [1.0, 1.0, 1.0, 1.0, 20.0],
    )
    monkeypatch.setattr(ev, "sma", lambda values, period: [0.0] * len(values))

    result = ev.evaluate_ticker(
        "AAPL.US",
        _candles_for_gap_test(),  # type: ignore[arg-type]
        ev.EvaluationSettings(
            min_history_bars=2,
            min_price=0.0,
            min_dollar_volume=0.0,
            gap_atr_multiplier=1.0,
            use_sma200_filter=False,
            require_slope_up=False,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is None
    assert result.reason_kind == "signal"
    assert result.reason is not None
    assert "exceeds threshold" in result.reason
