from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .eval_index import choose_eval_index
from .indicators import ema, rsi, sma


@dataclass
class HybridSellSettings:
    # Profit taking
    profit_target_low: float = 0.05
    profit_target_high: float = 0.10
    partial_profit_floor: float = 0.03

    # Trend breakdown
    ema_short_period: int = 10
    ema_mid_period: int = 21
    sma_trend_period: int = 20
    rsi_period: int = 14

    # Hard stop band
    stop_loss_pct_min: float = 0.03
    stop_loss_pct_max: float = 0.05

    # Failed breakout
    failed_breakout_drop_pct: float = 0.03

    # General
    min_bars: int = 20
    time_stop_days: int = 0  # optional; 0 to disable
    time_stop_grace_days: int = 0  # extra days after time_stop_days before a hard exit
    time_stop_profit_floor: float = 0.0  # minimum P&L to avoid forced exit after grace


@dataclass
class HybridSellEvaluation:
    action: str  # HOLD, REVIEW, SELL
    reasons: list[str]
    stop_price: float | None = None
    target_price: float | None = None
    eval_price: float | None = None
    eval_index: int | None = None
    eval_date: str | None = None


def _compute_pnl_pct(
    entry_price: float | None, last_close: float | None
) -> float | None:
    if entry_price is None or last_close is None:
        return None
    if entry_price == 0:
        return None
    try:
        return (last_close - entry_price) / entry_price
    except TypeError:
        return None


def evaluate_sell_signals_hybrid(
    ticker: str,
    candles: list[dict[str, float]],
    holding: dict[str, Any],
    settings: HybridSellSettings,
) -> HybridSellEvaluation:
    if len(candles) < max(settings.min_bars, 2):
        return HybridSellEvaluation(
            action="REVIEW", reasons=["Insufficient data for hybrid sell evaluation"]
        )

    meta_currency = holding.get("entry_currency") or holding.get("currency")
    meta = {"currency": meta_currency} if meta_currency else {}
    meta["exchange"] = holding.get("exchange")
    meta["data_source"] = holding.get("data_source")
    provider = str(meta.get("data_source") or holding.get("provider") or "kis").lower()
    idx_eval, _ = choose_eval_index(candles, meta=meta, provider=provider)
    if idx_eval < 1:
        return HybridSellEvaluation(
            action="REVIEW", reasons=["Not enough completed candles for hybrid sell"]
        )

    candles_eval = candles[: idx_eval + 1]
    closes = [float(c["close"]) for c in candles_eval]
    latest = candles[idx_eval]
    last_close = float(latest.get("close") or 0.0)
    eval_date = str(latest.get("date") or "") or None

    ema_short = ema(closes, settings.ema_short_period)
    ema_mid = ema(closes, settings.ema_mid_period)
    sma_trend = sma(closes, settings.sma_trend_period)
    rsi_values = rsi(closes, settings.rsi_period)

    reasons: list[str] = []
    action = "HOLD"

    entry_price = holding.get("entry_price")
    entry_price = float(entry_price) if isinstance(entry_price, (int | float)) else None

    pnl_pct = _compute_pnl_pct(entry_price, last_close)

    # --- 1) Profit taking logic ---
    stop_price: float | None = None
    target_price: float | None = None

    if pnl_pct is not None and pnl_pct >= settings.profit_target_high:
        reasons.append(
            f"Reached high profit target ({pnl_pct * 100:.1f}% ≥ {settings.profit_target_high * 100:.1f}%)"
        )
        action = "SELL"
    elif pnl_pct is not None and pnl_pct >= settings.profit_target_low:
        reasons.append(
            f"Reached profit target zone ({pnl_pct * 100:.1f}% ≥ {settings.profit_target_low * 100:.1f}%)"
        )
        if action != "SELL":
            action = "REVIEW"
    elif pnl_pct is not None and pnl_pct >= settings.partial_profit_floor:
        reasons.append(
            f"Reached partial profit zone ({pnl_pct * 100:.1f}% ≥ {settings.partial_profit_floor * 100:.1f}%)"
        )
        if action != "SELL":
            action = "REVIEW"

    # Suggest a notional target price (can be surfaced in report)
    if entry_price is not None:
        target_price = entry_price * (1.0 + settings.profit_target_high)

    # --- 2) Trend breakdown (EMA/SMA + RSI) ---
    ema_s = ema_short[-1]
    sma_t = sma_trend[-1]
    rsi_today = rsi_values[-1]

    # Price relative to EMA/SMA
    if last_close < ema_s:
        reasons.append("Close below EMA short")
        if action != "SELL":
            action = "REVIEW"
    if last_close < sma_t:
        reasons.append("Close below SMA trend (SMA20)")
        if action != "SELL":
            action = "REVIEW"

    # Momentum shift: EMA short falling below EMA mid
    if (
        len(ema_short) >= 2
        and len(ema_mid) >= 2
        and ema_short[-1] < ema_mid[-1]
        and ema_short[-2] >= ema_mid[-2]
    ):
        reasons.append("EMA short crossed below EMA mid (momentum down)")
        action = "SELL"

    # Consecutive bearish candles
    if len(candles_eval) >= 3:
        last_three = candles_eval[-3:]
        if all(float(c["close"]) < float(c["open"]) for c in last_three):
            reasons.append("Three consecutive bearish candles")
            if action != "SELL":
                action = "REVIEW"

    # RSI breakdowns
    if rsi_today < 50.0:
        reasons.append("RSI dropped below 50")
        if action != "SELL":
            action = "REVIEW"
    if rsi_today < 40.0:
        reasons.append("RSI dropped into oversold zone (<40)")
        action = "SELL"

    # --- 3) Failed breakout ---
    # If holding strategy is breakout-like, consider a sharp drop > failed_breakout_drop_pct
    strategy_tag = str(holding.get("strategy") or "").lower()
    if (
        entry_price is not None
        and pnl_pct is not None
        and "breakout" in strategy_tag
        and pnl_pct <= -settings.failed_breakout_drop_pct
    ):
        reasons.append(
            f"Failed breakout: price moved {pnl_pct * 100:.1f}% below entry "
            f"(threshold {settings.failed_breakout_drop_pct * 100:.1f}%)"
        )
        action = "SELL"

    # --- 4) Hard stop loss band (3–5%) ---
    if entry_price is not None:
        loss_pct = _compute_pnl_pct(entry_price, last_close)
        if loss_pct is not None and loss_pct < 0:
            loss_abs = abs(loss_pct)
            if loss_abs >= settings.stop_loss_pct_min:
                reasons.append(
                    f"Hit hard stop band (loss {loss_abs * 100:.1f}% ≥ "
                    f"{settings.stop_loss_pct_min * 100:.1f}% min)"
                )
                action = "SELL"
                # Set stop at the midpoint of the band for reporting
                mid_band = (
                    settings.stop_loss_pct_min + settings.stop_loss_pct_max
                ) / 2.0
                stop_price = entry_price * (1.0 - mid_band)

    # --- 5) Optional time stop ---
    time_stop_days = settings.time_stop_days
    time_stop_grace_days = settings.time_stop_grace_days
    time_stop_profit_floor = settings.time_stop_profit_floor
    entry_date_str = holding.get("entry_date")
    days_in_trade: int | None = None
    if entry_date_str and time_stop_days > 0:
        try:
            entry_date = dt.date.fromisoformat(str(entry_date_str))
            days_in_trade = (dt.date.today() - entry_date).days
            if days_in_trade >= time_stop_days:
                reasons.append(
                    f"Time stop: {days_in_trade} days ≥ {time_stop_days} days"
                )
                if action != "SELL":
                    action = "REVIEW"
        except ValueError:
            pass

    # Extended time stop: only if a grace window is configured
    if (
        days_in_trade is not None
        and time_stop_days > 0
        and time_stop_grace_days > 0
        and days_in_trade >= (time_stop_days + time_stop_grace_days)
        and action != "SELL"
    ):
        pnl_ok = pnl_pct is not None and pnl_pct >= time_stop_profit_floor
        trend_ok = last_close >= sma_t and ema_short[-1] >= ema_mid[-1]
        weak_bits = []
        if not pnl_ok:
            if pnl_pct is None:
                weak_bits.append("P&L unavailable")
            else:
                weak_bits.append(
                    f"P&L {pnl_pct * 100:.1f}% < floor {time_stop_profit_floor * 100:.1f}%"
                )
        if not trend_ok:
            weak_bits.append("trend below SMA/EMA")

        if not pnl_ok or not trend_ok:
            reason_detail = "; ".join(weak_bits) if weak_bits else "weak trend/return"
            reasons.append(
                f"Extended time stop: {days_in_trade} days ≥ "
                f"{time_stop_days + time_stop_grace_days} days ({reason_detail})"
            )
            action = "SELL"

    if not reasons:
        reasons.append("No hybrid sell criteria triggered")

    return HybridSellEvaluation(
        action=action,
        reasons=reasons,
        stop_price=stop_price,
        target_price=target_price,
        eval_price=last_close,
        eval_index=idx_eval,
        eval_date=eval_date,
    )


__all__ = [
    "HybridSellSettings",
    "HybridSellEvaluation",
    "evaluate_sell_signals_hybrid",
]
