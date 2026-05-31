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
            rs_lookback_days=1,
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
            rs_lookback_days=1,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["close_value"] == pytest.approx(candidate["price_value"])
    assert candidate["signal_price_basis"] == "adjusted"
    assert candidate["signal_close_adjusted_value"] == pytest.approx(
        candidate["close_value"]
    )
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


def test_ema_cross_candidate_contract_fields_are_stable(
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
            rs_lookback_days=1,
            rs_benchmark_return=0.01,
        ),
        {"currency": "USD", "name": "Apple Inc."},
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["ticker"] == "AAPL.NASD"
    assert candidate["name"] == "Apple Inc."
    assert candidate["currency"] == "USD"
    assert candidate["eval_date"] == "20250110"
    assert (
        candidate["score_notes"] == "ema_cross, rsi, sma200, slope, gap, liquidity, rs"
    )
    assert candidate["score_value"] == pytest.approx(7.0)
    assert candidate["gap"] == "0.0%"
    assert candidate["gap_threshold"] == "9.5%"
    assert candidate["risk_guide"] == "Stop 10 / Target 13 (~1:2)"
    assert candidate["signal_price_basis"] == "adjusted"
    assert [reason["id"] for reason in candidate["reasons"]] == [
        "ema_cross",
        "rsi_rebound",
        "sma200_trend_filter",
        "ema_slope_up",
        "gap_within_limit",
        "liquidity",
        "rs_above_benchmark",
    ]


@pytest.mark.parametrize(
    ("case", "expected_reason", "expected_kind"),
    [
        ("history", "Not enough completed history (<4 bars)", "system"),
        ("ohlc", "Invalid candle data: non-finite OHLC values", "system"),
        ("volume", "Invalid candle data: non-finite volume values", "system"),
        (
            "gap_unavailable",
            "Gap filter unavailable: ATR/price inputs invalid",
            "system",
        ),
        ("price", "Price 11 < MIN_PRICE 20", "signal"),
        ("sma200", "Below SMA200 filter", "signal"),
        ("slope", "EMA slope not rising", "signal"),
        ("liquidity", "Avg dollar volume 11,583,333 < 999,999,999,999", "signal"),
        ("etf", "ETF/ETN excluded", "signal"),
    ],
)
def test_ema_cross_failure_reason_kind_contract(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_reason: str,
    expected_kind: str,
) -> None:
    candles = _candles()
    settings = ev.EvaluationSettings(
        min_history_bars=2,
        use_sma200_filter=False,
        require_slope_up=False,
        gap_atr_multiplier=1.0,
        min_price=0.0,
        min_dollar_volume=0.0,
        exclude_etf_etn=False,
    )
    meta = {"currency": "USD", "name": "Apple Inc."}

    if case == "history":
        settings.min_history_bars = 4
    elif case == "ohlc":
        candles[-1]["high"] = float("nan")
    elif case == "volume":
        candles[-1]["volume"] = "N/A"
    elif case == "gap_unavailable":
        monkeypatch.setattr(
            ev, "atr", lambda highs, lows, closes, period: [1.0, float("nan"), 1.0]
        )
    elif case == "price":
        settings.min_price = 20.0
    elif case == "sma200":
        settings.use_sma200_filter = True
        monkeypatch.setattr(ev, "sma", lambda values, period: [99.0] * len(values))
    elif case == "slope":
        settings.require_slope_up = True

        def _ema_slope_fail(values: list[float], period: int) -> list[float]:
            if period == 20:
                return [3.0, 3.0, 3.1]
            return [2.0, 3.0, 2.9]

        monkeypatch.setattr(ev, "ema", _ema_slope_fail)
    elif case == "liquidity":
        settings.min_dollar_volume = 999_999_999_999.0
    elif case == "etf":
        settings.exclude_etf_etn = True
        meta["name"] = "Vanguard Total Market ETF"

    if case not in {"slope"}:
        _patch_positive_signal_indicators(monkeypatch, slope_up=True)
    else:
        monkeypatch.setattr(
            ev,
            "choose_eval_index",
            lambda data, meta=None, provider=None: (len(data) - 1, True),
        )
        monkeypatch.setattr(ev, "rsi", lambda values, period: [25.0, 30.0, 50.0])
        monkeypatch.setattr(
            ev, "atr", lambda highs, lows, closes, period: [1.0] * len(closes)
        )
        monkeypatch.setattr(ev, "sma", lambda values, period: [0.5] * len(values))

    if case == "gap_unavailable":
        monkeypatch.setattr(
            ev, "atr", lambda highs, lows, closes, period: [1.0, float("nan"), 1.0]
        )
    if case == "sma200":
        monkeypatch.setattr(ev, "sma", lambda values, period: [99.0] * len(values))

    result = ev.evaluate_ticker(
        "AAPL.NASD",
        cast(list[dict[str, float]], candles),
        settings,
        meta,
    )

    assert result.candidate is None
    assert result.reason == expected_reason
    assert result.reason_kind == expected_kind


def test_ema_cross_uses_market_benchmark_from_meta(
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
            rs_lookback_days=2,
            rs_benchmark_return=None,
        ),
        {
            "currency": "USD",
            "rs_benchmark_return": 0.05,
            "rs_benchmark_ticker": "SPY.AMS",
        },
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["rs_return_value"] == pytest.approx(0.1)
    assert candidate["rs_diff_value"] == pytest.approx(0.05)
    assert candidate["rs_benchmark_value"] == pytest.approx(0.05)
    assert candidate["rs_benchmark_ticker"] == "SPY.AMS"
    assert "rs" in candidate["score_notes"]


def test_ema_cross_disables_rs_score_when_benchmark_missing(
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
            rs_lookback_days=2,
            rs_benchmark_return=None,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["rs_return_value"] == pytest.approx(0.1)
    assert candidate["rs_diff_value"] is None
    assert candidate["rs_benchmark_value"] is None
    reason_ids = {str(item.get("id")) for item in candidate["reasons"]}
    assert "rs_above_benchmark" not in reason_ids
    assert "rs_below_benchmark" not in reason_ids


def test_ema_cross_uses_market_benchmark_return_from_meta(
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
            rs_lookback_days=1,
        ),
        {
            "currency": "USD",
            "rs_benchmark_return": 0.05,
            "rs_benchmark_ticker": "SPY.AMS",
        },
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["rs_return_value"] == pytest.approx((11.0 - 10.5) / 10.5)
    assert candidate["rs_diff_value"] == pytest.approx(((11.0 - 10.5) / 10.5) - 0.05)
    assert candidate["rs_benchmark_value"] == pytest.approx(0.05)
    assert candidate["rs_benchmark_ticker"] == "SPY.AMS"


def test_ema_cross_does_not_award_rs_without_benchmark(
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
            rs_lookback_days=1,
        ),
        {"currency": "USD"},
    )

    assert result.candidate is not None
    candidate = result.candidate
    assert candidate["rs_return_value"] == pytest.approx((11.0 - 10.5) / 10.5)
    assert candidate["rs_diff_value"] is None
    assert candidate["rs_benchmark"] == "-"
    assert "rs" not in candidate["score_notes"].split(", ")
