from __future__ import annotations

import datetime as dt

import sab.signals.hybrid_sell as hybrid_sell
from sab.signals.hybrid_sell import HybridSellSettings


def test_hybrid_sell_exit_trend_helper_preserves_reason_order() -> None:
    helper = getattr(hybrid_sell, "_apply_hybrid_sell_exit_trend_rules", None)

    assert helper is not None

    context = hybrid_sell._HybridSellContext(
        last_close=101.0,
        eval_date="20250103",
        eval_anchor=dt.date(2025, 1, 3),
        indicators=hybrid_sell._HybridSellIndicators(
            ema_short=102.0,
            ema_mid=103.0,
            sma_trend=104.0,
            rsi_today=45.0,
            ema_short_prev=104.0,
            ema_mid_prev=103.0,
        ),
        entry_date_state=hybrid_sell._EntryDateState(
            entry_date=dt.date(2025, 1, 1),
            invalid=False,
            after_eval=False,
        ),
        action="HOLD",
        reasons=[],
        closes_since_entry=[100.0, 104.0, 101.0],
        corporate_action_move=None,
        entry_price=100.0,
        pnl_pct=0.01,
    )

    state = helper(
        holding={"target_override": 112.0},
        settings=HybridSellSettings(
            ema_short_period=2,
            ema_mid_period=3,
            sma_trend_period=2,
            rsi_period=2,
        ),
        opens=[100.0, 103.0, 102.0],
        closes=[100.0, 102.0, 101.0],
        context=context,
    )

    assert state.action == "SELL"
    assert state.stop_override is None
    assert state.target_price == 112.0
    assert state.reasons == [
        "Custom target override in effect",
        "Profit protection armed at break-even (peak 4.0% ≥ 3.0%)",
        "Close below EMA short",
        "Close below SMA trend (SMA20)",
        "EMA short crossed below EMA mid (momentum down)",
        "RSI dropped below 50",
    ]
