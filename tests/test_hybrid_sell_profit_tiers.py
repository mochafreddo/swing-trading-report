import datetime as dt
from pathlib import Path
from typing import cast

import pytest
import sab.signals.hybrid_sell as hybrid_sell
from sab.signals.hybrid_sell import (
    HybridSellSettings,
    _apply_exit_overrides,
    evaluate_sell_signals_hybrid,
)


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


def _profit_trail_candles(*, peak_close: float, last_close: float) -> list[dict]:
    return [
        {
            "date": "20250101",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1,
        },
        {
            "date": "20250102",
            "open": peak_close,
            "high": peak_close,
            "low": peak_close,
            "close": peak_close,
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


def _failed_breakout_settings() -> HybridSellSettings:
    return HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        stop_loss_pct_min=0.10,
        stop_loss_pct_max=0.20,
    )


def _patch_indicator_series(
    monkeypatch,
    *,
    ema_short: list[float] | None = None,
    ema_mid: list[float] | None = None,
    sma_trend: list[float] | None = None,
    rsi_values: list[float] | None = None,
) -> None:
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.choose_eval_index",
        lambda data, **_: (len(data) - 1, True),
    )

    def _ema(closes, n):
        if n == 2:
            return ema_short or [0.0] * len(closes)
        return ema_mid or [0.0] * len(closes)

    monkeypatch.setattr("sab.signals.hybrid_sell.ema", _ema)
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.sma",
        lambda closes, n: sma_trend or [0.0] * len(closes),
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.rsi",
        lambda closes, n: rsi_values or [60.0] * len(closes),
    )


def test_hybrid_sell_completed_candles_context_preserves_meta_and_eval_slice(
    monkeypatch, tmp_path: Path
) -> None:
    captured_meta: dict[str, object] = {}

    def _choose_eval_index(
        data: list[dict[str, float]], **kwargs: object
    ) -> tuple[int, bool]:
        captured_meta.update(cast(dict[str, object], kwargs.get("meta") or {}))
        return 1, False

    monkeypatch.setattr("sab.signals.hybrid_sell.choose_eval_index", _choose_eval_index)
    helper = getattr(hybrid_sell, "_resolve_completed_sell_candles", None)

    assert helper is not None

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
            "open": 105.0,
            "high": 106.0,
            "low": 104.0,
            "close": 105.0,
            "volume": 1.0,
        },
        {
            "date": "20250103",
            "open": float("nan"),
            "high": float("nan"),
            "low": float("nan"),
            "close": float("nan"),
            "volume": 1.0,
        },
    ]
    holding = {
        "currency": "KRW",
        "entry_currency": "USD",
        "exchange": "NASDAQ",
        "data_source": "kis",
        "data_dir": tmp_path.as_posix(),
    }

    result = helper(
        candles=cast(list[dict[str, float]], candles),
        holding=holding,
        settings=HybridSellSettings(min_bars=2),
    )

    assert isinstance(result, hybrid_sell._CompletedSellCandles)
    assert result.idx_eval == 1
    assert result.candles_eval == candles[:2]
    assert result.opens == [100.0, 105.0]
    assert result.closes == [100.0, 105.0]
    assert captured_meta == {
        "currency": "USD",
        "exchange": "NASDAQ",
        "data_source": "kis",
        "data_dir": tmp_path.as_posix(),
    }


def test_hybrid_sell_context_state_preserves_initial_review_contract(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.ema",
        lambda closes, n: [101.0] * len(closes) if n == 2 else [],
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.sma", lambda closes, n: [99.0] * len(closes)
    )
    monkeypatch.setattr(
        "sab.signals.hybrid_sell.rsi", lambda closes, n: [60.0] * len(closes)
    )
    helper = getattr(hybrid_sell, "_prepare_hybrid_sell_context", None)

    assert helper is not None

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
    result = helper(
        candles_eval=cast(list[dict[str, float]], candles),
        closes=[100.0, 50.0, 51.0],
        holding={"entry_price": "100", "entry_date": "2025-01-10"},
        settings=HybridSellSettings(
            ema_short_period=2,
            ema_mid_period=3,
            sma_trend_period=2,
            rsi_period=2,
        ),
    )

    assert result.action == "REVIEW"
    assert result.reasons == [
        "Time stop skipped: entry_date after eval_date",
        "Indicator data unavailable for hybrid sell: EMA mid",
    ]
    assert result.last_close == 51.0
    assert result.eval_date == "20250103"
    assert result.eval_anchor == dt.date(2025, 1, 3)
    assert result.indicators.ema_short == 101.0
    assert result.indicators.ema_mid is None
    assert result.entry_date_state.after_eval is True
    assert result.closes_since_entry == []
    assert result.corporate_action_move == -0.5
    assert result.entry_price == 100.0
    assert result.pnl_pct == -0.49


@pytest.mark.parametrize(
    ("candles", "holding", "indicator_kwargs", "expected_reason"),
    [
        (
            _simple_candles(100.0),
            {"entry_price": 100.0},
            {
                "ema_short": [2.0, 2.0, 1.0],
                "ema_mid": [1.0, 1.0, 2.0],
            },
            "EMA short crossed below EMA mid (momentum down)",
        ),
        (
            _simple_candles(100.0),
            {"entry_price": 100.0},
            {"rsi_values": [60.0, 60.0, 39.0]},
            "RSI dropped into oversold zone (<40)",
        ),
        (
            _simple_candles(94.0),
            {"entry_price": 100.0},
            {},
            "Hit hard stop max",
        ),
    ],
)
def test_hybrid_sell_strong_exit_rule_contract(
    monkeypatch,
    candles: list[dict],
    holding: dict[str, float],
    indicator_kwargs: dict[str, list[float]],
    expected_reason: str,
) -> None:
    _patch_indicator_series(monkeypatch, **indicator_kwargs)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=3, sma_trend_period=2
    )

    result = evaluate_sell_signals_hybrid("FAKE.US", candles, holding, settings)

    assert result.action == "SELL"
    assert any(expected_reason in reason for reason in result.reasons)


def test_hybrid_sell_custom_stop_keeps_stop_price_when_profit_protection_also_arms(
    monkeypatch,
) -> None:
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-01",
        "stop_override": 99.0,
    }

    result = evaluate_sell_signals_hybrid(
        "FAKE.US",
        _profit_trail_candles(peak_close=112.0, last_close=98.0),
        holding,
        settings,
    )

    assert result.action == "SELL"
    assert result.stop_price == 99.0
    assert result.reasons[0:2] == [
        "Custom stop override in effect",
        "Price hit custom stop override",
    ]
    assert any("High-target profit protection activated" in r for r in result.reasons)


def test_hybrid_sell_exit_override_state_preserves_contract() -> None:
    settings = HybridSellSettings(profit_target_high=0.10)

    result = _apply_exit_overrides(
        holding={
            "stop_override": 95.0,
            "target_override": 123.0,
        },
        entry_price=100.0,
        last_close=94.0,
        settings=settings,
        action="HOLD",
    )

    assert result.action == "SELL"
    assert result.stop_override == 95.0
    assert result.target_override == 123.0
    assert result.stop_price == 95.0
    assert result.target_price == 123.0
    assert result.reasons == [
        "Custom stop override in effect",
        "Price hit custom stop override",
        "Custom target override in effect",
    ]


def test_hybrid_sell_profit_protection_state_preserves_peak_stop_contract() -> None:
    settings = HybridSellSettings()
    helper = getattr(hybrid_sell, "_apply_profit_protection", None)

    assert helper is not None

    result = helper(
        entry_price=100.0,
        pnl_pct=0.04,
        closes_since_entry=[100.0, 112.0, 104.0],
        last_close=104.0,
        corporate_action_move=None,
        entry_date_after_eval=False,
        stop_override=None,
        stop_price=None,
        settings=settings,
        action="HOLD",
    )

    assert result.action == "SELL"
    assert result.stop_price == 105.0
    assert result.reasons == [
        "Profit protection armed at break-even (peak 12.0% ≥ 3.0%)",
        "Profit protection tightened above entry (peak 12.0% ≥ 5.0%)",
        "High-target profit protection activated (peak 12.0% ≥ 10.0%)",
        "Price closed below profit protection stop",
    ]


def test_hybrid_sell_profit_exit_state_preserves_override_and_profit_order() -> None:
    helper = getattr(hybrid_sell, "_apply_profit_exit_rules", None)

    assert helper is not None

    result = helper(
        holding={"entry_price": 100.0, "stop_override": 99.0},
        settings=HybridSellSettings(profit_target_high=0.10),
        context=hybrid_sell._HybridSellContext(
            last_close=98.0,
            eval_date="20250103",
            eval_anchor=dt.date(2025, 1, 3),
            indicators=hybrid_sell._HybridSellIndicators(
                ema_short=100.0,
                ema_mid=99.0,
                sma_trend=95.0,
                rsi_today=60.0,
                ema_short_prev=99.0,
                ema_mid_prev=98.0,
            ),
            entry_date_state=hybrid_sell._EntryDateState(
                entry_date=dt.date(2025, 1, 1),
                invalid=False,
                after_eval=False,
            ),
            action="HOLD",
            reasons=[],
            closes_since_entry=[100.0, 112.0, 98.0],
            corporate_action_move=None,
            entry_price=100.0,
            pnl_pct=-0.02,
        ),
    )

    assert result.action == "SELL"
    assert result.stop_override == 99.0
    assert result.stop_price == 99.0
    assert result.target_price == pytest.approx(110.0)
    assert result.reasons == [
        "Custom stop override in effect",
        "Price hit custom stop override",
        "Profit protection armed at break-even (peak 12.0% ≥ 3.0%)",
        "Profit protection tightened above entry (peak 12.0% ≥ 5.0%)",
        "High-target profit protection activated (peak 12.0% ≥ 10.0%)",
    ]


def test_hybrid_sell_rule_pipeline_preserves_reason_order_and_output_fields() -> None:
    helper = getattr(hybrid_sell, "_apply_hybrid_sell_rule_pipeline", None)

    assert helper is not None

    result = helper(
        ticker="TEST",
        holding={
            "entry_price": 100.0,
            "entry_date": "2025-01-01",
            "stop_override": 98.0,
            "target_override": 123.0,
            "tags": ["swing_high_breakout"],
        },
        settings=HybridSellSettings(
            failed_breakout_drop_pct=0.03,
            time_stop_days=10,
        ),
        opens=[102.0, 101.0, 97.0],
        closes=[101.0, 100.0, 97.0],
        context=hybrid_sell._HybridSellContext(
            last_close=97.0,
            eval_date="20250103",
            eval_anchor=dt.date(2025, 1, 3),
            indicators=hybrid_sell._HybridSellIndicators(
                ema_short=98.0,
                ema_mid=99.0,
                sma_trend=98.5,
                rsi_today=39.0,
                ema_short_prev=100.0,
                ema_mid_prev=99.0,
            ),
            entry_date_state=hybrid_sell._EntryDateState(
                entry_date=dt.date(2025, 1, 1),
                invalid=False,
                after_eval=False,
            ),
            action="REVIEW",
            reasons=["Indicator data unavailable for hybrid sell: EMA mid"],
            closes_since_entry=[100.0, 101.0, 97.0],
            corporate_action_move=0.5,
            entry_price=100.0,
            pnl_pct=-0.03,
        ),
    )

    assert result.action == "SELL"
    assert result.stop_price == 98.0
    assert result.target_price == 123.0
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert result.days_in_trade_sessions is None
    assert result.time_stop_triggered is False
    assert result.reasons == [
        "Indicator data unavailable for hybrid sell: EMA mid",
        "Custom stop override in effect",
        "Price hit custom stop override",
        "Custom target override in effect",
        "Close below EMA short",
        "Close below SMA trend (SMA20)",
        "EMA short crossed below EMA mid (momentum down)",
        "RSI dropped below 50",
        "RSI dropped into oversold zone (<40)",
        "Failed breakout: price moved -3.0% below entry (threshold 3.0%)",
        "Time stop skipped: unable to resolve holding market",
        "Potential corporate action: abnormal one-day move 50.0%",
    ]


def test_hybrid_sell_trend_breakdown_state_preserves_review_reason_order() -> None:
    helper = getattr(hybrid_sell, "_apply_trend_breakdown_rules", None)

    assert helper is not None

    result = helper(
        opens=[106.0, 105.0, 104.0],
        closes=[105.0, 104.0, 103.0],
        last_close=103.0,
        indicators=hybrid_sell._HybridSellIndicators(
            ema_short=104.0,
            ema_mid=100.0,
            sma_trend=104.5,
            rsi_today=45.0,
            ema_short_prev=104.5,
            ema_mid_prev=100.0,
        ),
        action="HOLD",
    )

    assert result.action == "REVIEW"
    assert result.reasons == [
        "Close below EMA short",
        "Close below SMA trend (SMA20)",
        "Three consecutive bearish candles",
        "RSI dropped below 50",
    ]


def test_hybrid_sell_trend_breakdown_state_preserves_sell_priority() -> None:
    helper = getattr(hybrid_sell, "_apply_trend_breakdown_rules", None)

    assert helper is not None

    result = helper(
        opens=[102.0, 101.0, 100.0],
        closes=[101.0, 100.0, 99.0],
        last_close=99.0,
        indicators=hybrid_sell._HybridSellIndicators(
            ema_short=100.5,
            ema_mid=101.0,
            sma_trend=100.0,
            rsi_today=39.0,
            ema_short_prev=102.0,
            ema_mid_prev=101.0,
        ),
        action="HOLD",
    )

    assert result.action == "SELL"
    assert result.reasons == [
        "Close below EMA short",
        "Close below SMA trend (SMA20)",
        "EMA short crossed below EMA mid (momentum down)",
        "Three consecutive bearish candles",
        "RSI dropped below 50",
        "RSI dropped into oversold zone (<40)",
    ]


def test_hybrid_sell_corporate_action_guard_state_preserves_review_contract() -> None:
    helper = getattr(hybrid_sell, "_apply_corporate_action_guard", None)

    assert helper is not None

    result = helper(corporate_action_move=0.5, action="HOLD")

    assert result.action == "REVIEW"
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert result.reasons == [
        "Potential corporate action: abnormal one-day move 50.0%",
        "Corporate action suspect: manual review required before sell decision",
    ]


@pytest.mark.parametrize(
    (
        "corporate_action_move",
        "initial_action",
        "expected_action",
        "expected_reasons",
        "expected_flags",
    ),
    [
        (None, "HOLD", "HOLD", [], []),
        (
            0.5,
            "REVIEW",
            "REVIEW",
            ["Potential corporate action: abnormal one-day move 50.0%"],
            ["CORPORATE_ACTION_SUSPECT"],
        ),
        (
            0.5,
            "SELL",
            "SELL",
            ["Potential corporate action: abnormal one-day move 50.0%"],
            ["CORPORATE_ACTION_SUSPECT"],
        ),
    ],
)
def test_hybrid_sell_corporate_action_guard_state_preserves_existing_action_contracts(
    corporate_action_move: float | None,
    initial_action: str,
    expected_action: str,
    expected_reasons: list[str],
    expected_flags: list[str],
) -> None:
    helper = getattr(hybrid_sell, "_apply_corporate_action_guard", None)

    assert helper is not None

    result = helper(
        corporate_action_move=corporate_action_move,
        action=initial_action,
    )

    assert result.action == expected_action
    assert result.reasons == expected_reasons
    assert result.flags == expected_flags


@pytest.mark.parametrize(
    (
        "entry_price",
        "last_close",
        "stop_override",
        "initial_action",
        "expected_action",
        "expected_stop_price",
        "expected_reasons",
    ),
    [
        (
            100.0,
            94.0,
            None,
            "HOLD",
            "SELL",
            95.0,
            ["Hit hard stop max (loss 6.0% ≥ 5.0% max)"],
        ),
        (
            100.0,
            96.5,
            None,
            "HOLD",
            "REVIEW",
            95.0,
            ["Loss within hard stop band (3.5% in 3.0%–5.0%)"],
        ),
        (
            100.0,
            96.5,
            None,
            "SELL",
            "SELL",
            95.0,
            ["Loss within hard stop band (3.5% in 3.0%–5.0%)"],
        ),
        (100.0, 94.0, 90.0, "HOLD", "HOLD", None, []),
        (None, 94.0, None, "HOLD", "HOLD", None, []),
    ],
)
def test_hybrid_sell_hard_stop_band_state_preserves_contract(
    entry_price: float | None,
    last_close: float,
    stop_override: float | None,
    initial_action: str,
    expected_action: str,
    expected_stop_price: float | None,
    expected_reasons: list[str],
) -> None:
    helper = getattr(hybrid_sell, "_apply_hard_stop_band", None)

    assert helper is not None

    result = helper(
        entry_price=entry_price,
        last_close=last_close,
        stop_override=stop_override,
        settings=HybridSellSettings(stop_loss_pct_min=0.03, stop_loss_pct_max=0.05),
        action=initial_action,
    )

    assert result.action == expected_action
    assert result.stop_price == expected_stop_price
    assert result.reasons == expected_reasons


@pytest.mark.parametrize(
    (
        "holding",
        "entry_price",
        "pnl_pct",
        "initial_action",
        "expected_action",
        "expected_reasons",
    ),
    [
        (
            {"tags": ["swing_high_breakout"]},
            100.0,
            -0.035,
            "HOLD",
            "SELL",
            ["Failed breakout: price moved -3.5% below entry (threshold 3.0%)"],
        ),
        ({"tags": ["swing_high_breakout"]}, None, -0.035, "HOLD", "HOLD", []),
        ({"tags": ["swing_high_breakout"]}, 100.0, None, "HOLD", "HOLD", []),
        ({"tags": ["swing_high_breakout"]}, 100.0, -0.020, "HOLD", "HOLD", []),
        ({"tags": ["mean_reversion"]}, 100.0, -0.035, "HOLD", "HOLD", []),
        (
            {"tags": ["swing_high_breakout"]},
            100.0,
            -0.035,
            "SELL",
            "SELL",
            ["Failed breakout: price moved -3.5% below entry (threshold 3.0%)"],
        ),
    ],
)
def test_hybrid_sell_failed_breakout_state_preserves_contract(
    holding: dict[str, object],
    entry_price: float | None,
    pnl_pct: float | None,
    initial_action: str,
    expected_action: str,
    expected_reasons: list[str],
) -> None:
    helper = getattr(hybrid_sell, "_apply_failed_breakout_rules", None)

    assert helper is not None

    result = helper(
        holding=holding,
        entry_price=entry_price,
        pnl_pct=pnl_pct,
        settings=HybridSellSettings(failed_breakout_drop_pct=0.03),
        action=initial_action,
    )

    assert result.action == expected_action
    assert result.reasons == expected_reasons


def test_hybrid_sell_profit_high_arms_protection_without_forcing_sell(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(110.0), holding, settings
    )
    assert result.action == "HOLD"
    assert result.stop_price == 105.0
    assert any("High-target profit protection activated" in r for r in result.reasons)


def test_hybrid_sell_profit_protection_uses_peak_since_entry(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0, "entry_date": "2025-01-01"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US",
        _profit_trail_candles(peak_close=112.0, last_close=104.0),
        holding,
        settings,
    )

    assert result.action == "SELL"
    assert result.stop_price == 105.0
    assert any("peak" in reason.lower() for reason in result.reasons)
    assert "Price closed below profit protection stop" in result.reasons


def test_hybrid_sell_profit_protection_checks_stale_corporate_action_since_entry(
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
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1,
        },
        {
            "date": "20250102",
            "open": 50.0,
            "high": 50.0,
            "low": 50.0,
            "close": 50.0,
            "volume": 1,
        },
        *[
            {
                "date": f"202501{day:02d}",
                "open": 51.0,
                "high": 51.0,
                "low": 51.0,
                "close": 51.0,
                "volume": 1,
            }
            for day in range(3, 9)
        ],
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "REVIEW"
    assert result.stop_price is None
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert not any(
        "Price closed below profit protection stop" in r for r in result.reasons
    )


def test_hybrid_sell_reviews_future_entry_without_post_entry_candle(
    monkeypatch,
):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0, "entry_date": "2025-01-10"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(112.0), holding, settings
    )

    assert result.action == "REVIEW"
    assert result.stop_price is None
    assert any("entry_date after eval_date" in reason for reason in result.reasons)
    assert not any("Profit protection" in reason for reason in result.reasons)


def test_hybrid_sell_future_entry_ignores_corporate_action_current_pnl(
    monkeypatch,
):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 50.0, "entry_date": "2025-01-10"}
    candles = [
        {
            "date": "20250101",
            "open": 50.0,
            "high": 50.0,
            "low": 50.0,
            "close": 50.0,
            "volume": 1,
        },
        {
            "date": "20250102",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1,
        },
        {
            "date": "20250103",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", cast(list[dict[str, float]], candles), holding, settings
    )

    assert result.action == "REVIEW"
    assert result.stop_price is None
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("entry_date after eval_date" in reason for reason in result.reasons)
    assert not any("Profit protection" in reason for reason in result.reasons)


def test_hybrid_sell_profit_target_zone_tightens_stop_without_review(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(105.0), holding, settings
    )
    assert result.action == "HOLD"
    assert result.stop_price == 103.0
    assert any("Profit protection tightened above entry" in r for r in result.reasons)


def test_hybrid_sell_partial_profit_zone_sets_break_even_stop(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2, ema_short_period=2, ema_mid_period=2, sma_trend_period=2
    )
    holding = {"entry_price": 100.0}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(103.0), holding, settings
    )
    assert result.action == "HOLD"
    assert result.stop_price == 100.0
    assert any("Profit protection armed at break-even" in r for r in result.reasons)
    assert not any(
        "Profit protection tightened above entry" in r for r in result.reasons
    )


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


def test_hybrid_sell_failed_breakout_accepts_entry_tags(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = _failed_breakout_settings()
    holding = {"entry_price": 100.0, "tags": ["swing_high_breakout"]}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "SELL"
    assert any("Failed breakout" in reason for reason in result.reasons)


@pytest.mark.parametrize("field_name", ["pattern", "entry_pattern", "signal_pattern"])
def test_hybrid_sell_failed_breakout_accepts_structured_pattern_field(
    monkeypatch, field_name: str
):
    _patch_indicators(monkeypatch)
    settings = _failed_breakout_settings()
    holding = {"entry_price": 100.0, field_name: "swing_high_breakout"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "SELL"
    assert any("Failed breakout" in reason for reason in result.reasons)


@pytest.mark.parametrize("field_name", ["pattern", "entry_pattern", "signal_pattern"])
@pytest.mark.parametrize(
    "pattern_value",
    ["trend_pullback_bounce", "rsi_oversold_reversal", "not_a_breakout"],
)
def test_hybrid_sell_failed_breakout_ignores_non_breakout_structured_patterns(
    monkeypatch, field_name: str, pattern_value: str
):
    _patch_indicators(monkeypatch)
    settings = _failed_breakout_settings()
    holding = {"entry_price": 100.0, field_name: pattern_value}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "HOLD"
    assert not any("Failed breakout" in reason for reason in result.reasons)


@pytest.mark.parametrize("field_name", ["pattern", "entry_pattern", "signal_pattern"])
@pytest.mark.parametrize(
    "pattern_value",
    [
        ["swing_high_breakout"],
        {"value": "swing_high_breakout"},
        True,
        123,
    ],
)
def test_hybrid_sell_failed_breakout_ignores_malformed_structured_patterns(
    monkeypatch, field_name: str, pattern_value: object
):
    _patch_indicators(monkeypatch)
    settings = _failed_breakout_settings()
    holding = {"entry_price": 100.0, field_name: pattern_value}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "HOLD"
    assert not any("Failed breakout" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "holding",
    [
        {"entry_price": 100.0, "strategy": "legacy breakout setup"},
        {"entry_price": 100.0, "tags": ["legacy breakout setup"]},
    ],
)
def test_hybrid_sell_failed_breakout_keeps_legacy_substring_markers(
    monkeypatch, holding: dict[str, object]
):
    _patch_indicators(monkeypatch)
    settings = _failed_breakout_settings()

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(96.5), holding, settings
    )

    assert result.action == "SELL"
    assert any("Failed breakout" in reason for reason in result.reasons)


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


@pytest.mark.parametrize(
    (
        "days_in_trade_sessions",
        "pnl_pct",
        "last_close",
        "indicators",
        "initial_action",
        "expected_action",
        "expected_reasons",
    ),
    [
        (
            12,
            0.005,
            101.0,
            hybrid_sell._HybridSellIndicators(
                ema_short=101.0,
                ema_mid=100.0,
                sma_trend=99.0,
                rsi_today=60.0,
                ema_short_prev=100.0,
                ema_mid_prev=99.0,
            ),
            "REVIEW",
            "SELL",
            ["Extended time stop: 12 sessions ≥ 12 sessions (P&L 0.5% < floor 1.0%)"],
        ),
        (
            12,
            0.02,
            99.0,
            hybrid_sell._HybridSellIndicators(
                ema_short=98.0,
                ema_mid=100.0,
                sma_trend=100.0,
                rsi_today=60.0,
                ema_short_prev=99.0,
                ema_mid_prev=99.0,
            ),
            "REVIEW",
            "SELL",
            ["Extended time stop: 12 sessions ≥ 12 sessions (trend below SMA/EMA)"],
        ),
        (
            12,
            None,
            99.0,
            hybrid_sell._HybridSellIndicators(
                ema_short=None,
                ema_mid=100.0,
                sma_trend=None,
                rsi_today=60.0,
                ema_short_prev=99.0,
                ema_mid_prev=99.0,
            ),
            "REVIEW",
            "SELL",
            [
                "Extended time stop: 12 sessions ≥ 12 sessions "
                "(P&L unavailable; trend indicators unavailable)"
            ],
        ),
        (
            12,
            0.02,
            99.0,
            hybrid_sell._HybridSellIndicators(
                ema_short=None,
                ema_mid=100.0,
                sma_trend=None,
                rsi_today=60.0,
                ema_short_prev=99.0,
                ema_mid_prev=99.0,
            ),
            "REVIEW",
            "REVIEW",
            [],
        ),
        (
            11,
            0.005,
            101.0,
            hybrid_sell._HybridSellIndicators(
                ema_short=101.0,
                ema_mid=100.0,
                sma_trend=99.0,
                rsi_today=60.0,
                ema_short_prev=100.0,
                ema_mid_prev=99.0,
            ),
            "REVIEW",
            "REVIEW",
            [],
        ),
        (
            12,
            0.005,
            101.0,
            hybrid_sell._HybridSellIndicators(
                ema_short=101.0,
                ema_mid=100.0,
                sma_trend=99.0,
                rsi_today=60.0,
                ema_short_prev=100.0,
                ema_mid_prev=99.0,
            ),
            "SELL",
            "SELL",
            [],
        ),
    ],
)
def test_hybrid_sell_extended_time_stop_state_preserves_contract(
    days_in_trade_sessions: int,
    pnl_pct: float | None,
    last_close: float,
    indicators: hybrid_sell._HybridSellIndicators,
    initial_action: str,
    expected_action: str,
    expected_reasons: list[str],
) -> None:
    helper = getattr(hybrid_sell, "_apply_extended_time_stop", None)

    assert helper is not None

    result = helper(
        days_in_trade_sessions=days_in_trade_sessions,
        settings=HybridSellSettings(
            time_stop_days=10,
            time_stop_grace_days=2,
            time_stop_profit_floor=0.01,
        ),
        action=initial_action,
        pnl_pct=pnl_pct,
        last_close=last_close,
        indicators=indicators,
    )

    assert result.action == expected_action
    assert result.reasons == expected_reasons


def test_hybrid_sell_public_pipeline_applies_extended_time_stop_after_grace(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_indicator_series(
        monkeypatch,
        ema_short=[100.0, 100.0, 100.0],
        ema_mid=[99.0, 99.0, 99.0],
        sma_trend=[99.0, 99.0, 99.0],
        rsi_values=[60.0, 60.0, 60.0],
    )
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=3,
        sma_trend_period=2,
        time_stop_days=1,
        time_stop_grace_days=1,
        time_stop_profit_floor=0.01,
    )
    holding = {
        "entry_price": 100.0,
        "entry_date": "2025-01-06",
        "entry_currency": "USD",
        "data_dir": tmp_path.as_posix(),
    }
    candles = [
        {
            "date": "20250106",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1.0,
        },
        {
            "date": "20250107",
            "open": 100.5,
            "high": 100.5,
            "low": 100.5,
            "close": 100.5,
            "volume": 1.0,
        },
        {
            "date": "20250108",
            "open": 100.5,
            "high": 100.5,
            "low": 100.5,
            "close": 100.5,
            "volume": 1.0,
        },
    ]

    result = evaluate_sell_signals_hybrid(
        "FAKE.US",
        cast(list[dict[str, float]], candles),
        holding,
        settings,
    )

    assert result.action == "SELL"
    assert result.days_in_trade_sessions == 2
    assert result.time_stop_triggered is True
    assert result.reasons == [
        "Time stop: 2 sessions ≥ 1 sessions",
        "Extended time stop: 2 sessions ≥ 2 sessions (P&L 0.5% < floor 1.0%)",
    ]


def test_hybrid_sell_time_stop_uses_eval_date_not_local_today(monkeypatch):
    class _FixedDate(dt.date):
        @classmethod
        def today(cls) -> _FixedDate:
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
    holding = {"entry_price": 100.0, "entry_date": "2025-01-03"}

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
        def today(cls) -> _FixedDate:
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


def test_hybrid_sell_time_stop_reviews_future_entry_date(monkeypatch):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=3,
    )
    holding = {"entry_price": 100.0, "entry_date": "2025-01-10"}

    result = evaluate_sell_signals_hybrid(
        "FAKE.US", _simple_candles(100.0), holding, settings
    )

    assert result.action == "REVIEW"
    assert any(
        "Time stop skipped: entry_date after eval_date" in reason
        for reason in result.reasons
    )
    assert result.days_in_trade_sessions is None
    assert result.time_stop_triggered is False


def test_hybrid_sell_corporate_action_guard_promotes_hold_to_review(
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

    assert result.action == "REVIEW"
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("Potential corporate action" in reason for reason in result.reasons)
    assert any(
        "manual review required before sell decision" in reason
        for reason in result.reasons
    )


def test_hybrid_sell_corporate_action_guard_preserves_existing_review(
    monkeypatch,
):
    _patch_indicators(monkeypatch)
    settings = HybridSellSettings(
        min_bars=2,
        ema_short_period=2,
        ema_mid_period=2,
        sma_trend_period=2,
        time_stop_days=1,
    )
    holding = {
        "entry_price": 50.0,
        "entry_date": "2025-01-10",
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

    assert result.action == "REVIEW"
    assert result.flags == ["CORPORATE_ACTION_SUSPECT"]
    assert any("entry_date after eval_date" in reason for reason in result.reasons)
    assert any("Potential corporate action" in reason for reason in result.reasons)
    assert not any(
        "manual review required before sell decision" in reason
        for reason in result.reasons
    )


def test_hybrid_sell_corporate_action_guard_preserves_sell_with_flag(
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
