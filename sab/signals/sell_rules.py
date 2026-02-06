from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from .eval_index import choose_eval_index
from .indicators import atr, ema, rsi, sma


def _normalize_candle_date(value: Any) -> str:
    date_text = str(value or "").strip().replace("-", "")
    return date_text[:8]


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
    eval_price: float | None = None
    eval_index: int | None = None
    eval_date: str | None = None


def evaluate_sell_signals(
    ticker: str,
    candles: list[dict[str, float]],
    holding: dict[str, Any],
    settings: SellSettings,
) -> SellEvaluation:
    if len(candles) < settings.min_bars:
        return SellEvaluation(
            action="REVIEW", reasons=["Insufficient data for sell evaluation"]
        )

    meta_currency = holding.get("entry_currency") or holding.get("currency")
    meta = {"currency": meta_currency} if meta_currency else {}
    meta["exchange"] = holding.get("exchange")
    meta["data_source"] = holding.get("data_source")
    provider = str(meta.get("data_source") or holding.get("provider") or "kis").lower()
    idx_eval, _ = choose_eval_index(candles, meta=meta, provider=provider)
    if idx_eval < 1:
        return SellEvaluation(action="REVIEW", reasons=["Not enough completed candles"])

    candles_eval = candles[: idx_eval + 1]
    closes = [c["close"] for c in candles_eval]
    highs = [c["high"] for c in candles_eval]
    lows = [c["low"] for c in candles_eval]

    atr_values = atr(highs, lows, closes, 14)
    stop_override = holding.get("stop_override")
    target_override = holding.get("target_override")

    ema_len_short, ema_len_long = settings.ema_lengths
    ema_short = ema(closes, ema_len_short)
    ema_long = ema(closes, ema_len_long)
    rsi_values = rsi(closes, settings.rsi_period)

    latest = candles[idx_eval]
    close_today = float(latest.get("close") or 0.0)
    eval_date = str(latest.get("date") or "") or None
    atr_today = atr_values[-1]

    reasons: list[str] = []
    action = "HOLD"

    # SMA200 context (optional)
    if settings.require_sma200:
        sma200 = sma(closes, 200)
        sma_val = sma200[-1]
        if not (
            close_today > sma_val and ema_short[-1] > sma_val and ema_long[-1] > sma_val
        ):
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
    entry_date_str = holding.get("entry_date")
    if stop_override is not None:
        stop_price = float(stop_override)
        reasons.append("Custom stop override in effect")
    elif atr_today > 0:
        start_idx = max(0, len(closes) - settings.min_bars)
        if entry_date_str:
            try:
                entry_date = dt.date.fromisoformat(str(entry_date_str))
                entry_yyyymmdd = entry_date.strftime("%Y%m%d")
                for idx, candle in enumerate(candles_eval):
                    candle_date = _normalize_candle_date(candle.get("date"))
                    if candle_date and candle_date >= entry_yyyymmdd:
                        start_idx = idx
                        break
                else:
                    start_idx = len(closes) - 1
                    reasons.append(
                        "Entry date is after latest candle; ATR trail uses latest close"
                    )
            except ValueError:
                reasons.append(
                    "Entry date missing/invalid; ATR trail uses recent window"
                )
        else:
            reasons.append("Entry date missing/invalid; ATR trail uses recent window")

        trail_closes = closes[start_idx:]
        peak_close = max(trail_closes) if trail_closes else close_today
        stop_price = peak_close - settings.atr_trail_multiplier * atr_today
        reasons.append(
            f"ATR trail (peak close {peak_close:.2f}) "
            f"{settings.atr_trail_multiplier:g}×ATR → {stop_price:.2f}"
        )
        if close_today <= stop_price:
            reasons.append("Price hit ATR trailing stop")
            action = "SELL"

    target_price = float(target_override) if target_override is not None else None

    # Time stop: days since entry
    time_stop_days = settings.time_stop_days
    if entry_date_str and time_stop_days > 0:
        try:
            entry_date = dt.date.fromisoformat(str(entry_date_str))
            days_in_trade = (dt.date.today() - entry_date).days
            if days_in_trade >= time_stop_days:
                reasons.append(
                    f"Time stop: {days_in_trade} days >= {time_stop_days} days"
                )
                action = "REVIEW" if action != "SELL" else action
        except ValueError:
            pass

    if not reasons:
        reasons.append("No sell criteria triggered")

    return SellEvaluation(
        action=action,
        reasons=reasons,
        stop_price=stop_price,
        target_price=target_price,
        eval_price=close_today,
        eval_index=idx_eval,
        eval_date=eval_date,
    )
