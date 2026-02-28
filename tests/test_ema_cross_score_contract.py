from __future__ import annotations

from typing import Any, cast

import pytest
import sab.signals.evaluator as ev


def _candles() -> list[dict[str, Any]]:
    return [
        {
            "date": "20250108",
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": 1_000_000.0,
        },
        {
            "date": "20250109",
            "open": 10.0,
            "high": 11.0,
            "low": 9.8,
            "close": 10.5,
            "volume": 1_100_000.0,
        },
        {
            "date": "20250110",
            "open": 10.5,
            "high": 11.5,
            "low": 10.1,
            "close": 11.0,
            "volume": 1_200_000.0,
        },
    ]


def _patch_positive_signal_indicators(
    monkeypatch: pytest.MonkeyPatch,
    *,
    slope_up: bool,
) -> None:
    monkeypatch.setattr(
        ev,
        "choose_eval_index",
        lambda data, meta=None, provider=None: (len(data) - 1, True),
    )

    def _ema(values: list[float], period: int) -> list[float]:
        if period == 20:
            return [1.0, 1.0, 2.0]
        if slope_up:
            return [1.0, 1.0, 1.5]
        return [1.5, 1.5, 1.5]

    monkeypatch.setattr(ev, "ema", _ema)
    monkeypatch.setattr(ev, "rsi", lambda values, period: [25.0, 30.0, 50.0])
    monkeypatch.setattr(
        ev, "atr", lambda highs, lows, closes, period: [1.0] * len(closes)
    )
    monkeypatch.setattr(ev, "sma", lambda values, period: [0.5] * len(values))


def test_ema_cross_excludes_optional_filters_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_positive_signal_indicators(monkeypatch, slope_up=False)
    result = ev.evaluate_ticker(
        "AAPL.NASD",
        cast(list[dict[str, float]], _candles()),
        ev.EvaluationSettings(
            min_history_bars=2,
            use_sma200_filter=False,
            require_slope_up=False,
            gap_atr_multiplier=1.0,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    notes = result.candidate["score_notes"]
    assert "sma200" not in notes
    assert "slope" not in notes


def test_ema_cross_includes_optional_filters_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_positive_signal_indicators(monkeypatch, slope_up=True)
    result = ev.evaluate_ticker(
        "AAPL.NASD",
        cast(list[dict[str, float]], _candles()),
        ev.EvaluationSettings(
            min_history_bars=2,
            use_sma200_filter=True,
            require_slope_up=True,
            gap_atr_multiplier=1.0,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    notes = result.candidate["score_notes"]
    assert "sma200" in notes
    assert "slope" in notes


def test_ema_cross_candidate_exposes_entry_numeric_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_positive_signal_indicators(monkeypatch, slope_up=True)
    result = ev.evaluate_ticker(
        "AAPL.NASD",
        cast(list[dict[str, float]], _candles()),
        ev.EvaluationSettings(
            min_history_bars=2,
            use_sma200_filter=False,
            require_slope_up=False,
            gap_atr_multiplier=1.0,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["close_value"] == pytest.approx(candidate["price_value"])
    assert candidate["atr14_value"] == pytest.approx(1.0)
    assert candidate["gap_guard_pct_value"] == pytest.approx(1.0 / 11.0)
    assert candidate["gap_guard_up_price_value"] == pytest.approx(
        candidate["close_value"] * (1.0 + candidate["gap_guard_pct_value"])
    )
    assert candidate["gap_guard_down_price_value"] == pytest.approx(
        candidate["close_value"] * (1.0 - candidate["gap_guard_pct_value"])
    )


def test_ema_cross_candidate_exposes_structured_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_positive_signal_indicators(monkeypatch, slope_up=True)
    result = ev.evaluate_ticker(
        "AAPL.NASD",
        cast(list[dict[str, float]], _candles()),
        ev.EvaluationSettings(
            min_history_bars=2,
            use_sma200_filter=True,
            require_slope_up=True,
            gap_atr_multiplier=1.0,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    reasons = result.candidate["reasons"]
    assert isinstance(reasons, list)
    assert all(isinstance(item, dict) for item in reasons)
    ids = {str(item.get("id")) for item in reasons}
    assert {
        "ema_cross",
        "rsi_rebound",
        "gap_within_limit",
        "liquidity",
        "sma200_trend_filter",
        "ema_slope_up",
    }.issubset(ids)
    statuses = {str(item.get("status")) for item in reasons}
    assert statuses.issubset({"pass", "warn"})
