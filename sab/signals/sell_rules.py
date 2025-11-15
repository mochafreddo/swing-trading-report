from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .indicators import atr, ema, rsi, sma


@dataclass
class SellSettings:
    atr_trail_multiplier: float = 1.0
    time_stop_days: int = 10
    require_sma200: bool = True
    ema_lengths: tuple[int, int] = (20, 50)
    rsi_period: int = 14
    rsi_floor: float = 50.0
    rsi_floor_alt: float = 30.0
    min_bars: int = 20


@dataclass
class SellEvaluation:
    action: str  # HOLD, REVIEW, SELL
    reasons: list[str]
    stop_price: float | None = None
    target_price: float | None = None


def evaluate_sell_signals(
    ticker: str,
    candles: list[dict[str, float]],
    holding: dict[str, Any],
    settings: SellSettings,
) -> SellEvaluation:
    if len(candles) < settings.min_bars:
        return SellEvaluation(action="REVIEW", reasons=["Insufficient data for sell evaluation"])

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    atr_values = atr(highs, lows, closes, 14)
    stop_override = holding.get("stop_override")
    target_override = holding.get("target_override")

    ema_len_short, ema_len_long = settings.ema_lengths
    ema_short = ema(closes, ema_len_short)
    ema_long = ema(closes, ema_len_long)
    rsi_values = rsi(closes, settings.rsi_period)

    latest = candles[-1]
    close_today = latest["close"]
    atr_today = atr_values[-1]

    reasons: list[str] = []
    action = "HOLD"

    # SMA200 context (optional)
    if settings.require_sma200:
        sma200 = sma(closes, 200)
        sma_val = sma200[-1]
        if not (close_today > sma_val and ema_short[-1] > sma_val and ema_long[-1] > sma_val):
            reasons.append("Below SMA200 context")
            action = "REVIEW"

    # Death cross or EMA short < EMA long
    if ema_short[-1] < ema_long[-1] and ema_short[-2] >= ema_long[-2]:
        reasons.append("Short EMA crossed below long EMA")
        action = "SELL"
    elif close_today < ema_short[-1] and close_today < ema_long[-1]:
        reasons.append("Price below both EMAs")
        action = "REVIEW" if action != "SELL" else action

    # RSI breakdown
    rsi_today = rsi_values[-1]
    if rsi_today < settings.rsi_floor:
        reasons.append(f"RSI dropped below {settings.rsi_floor:.0f}")
        action = "REVIEW" if action != "SELL" else action
    if rsi_today < settings.rsi_floor_alt:
        reasons.append(f"RSI dropped below {settings.rsi_floor_alt:.0f}")
        action = "SELL"

    # ATR trailing stop
    stop_price = None
    if stop_override is not None:
        stop_price = float(stop_override)
        reasons.append("Custom stop override in effect")
    elif atr_today > 0:
        stop_price = close_today - settings.atr_trail_multiplier * atr_today
        reasons.append(f"ATR trail {settings.atr_trail_multiplier}×ATR → {stop_price:.2f}")
        if close_today <= stop_price:
            reasons.append("Price hit ATR trailing stop")
            action = "SELL"

    target_price = float(target_override) if target_override is not None else None

    # Time stop: days since entry
    time_stop_days = settings.time_stop_days
    entry_date_str = holding.get("entry_date")
    if entry_date_str and time_stop_days > 0:
        try:
            entry_date = dt.date.fromisoformat(str(entry_date_str))
            days_in_trade = (dt.date.today() - entry_date).days
            if days_in_trade >= time_stop_days:
                reasons.append(f"Time stop: {days_in_trade} days >= {time_stop_days} days")
                action = "REVIEW" if action != "SELL" else action
        except ValueError:
            pass

    if not reasons:
        reasons.append("No sell criteria triggered")

    return SellEvaluation(
        action=action, reasons=reasons, stop_price=stop_price, target_price=target_price
    )
