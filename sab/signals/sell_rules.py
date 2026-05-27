from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, TypedDict

from ..data.trading_sessions import count_trading_sessions
from ..utils.numeric import to_finite_float as _to_finite_float
from ._candle_dates import normalize_candle_date as _normalize_candle_date
from ._candle_dates import parse_eval_date as _parse_eval_date
from ._holding_market import resolve_holding_market as _resolve_holding_market
from .corporate_action import detect_corporate_action_move
from .eval_index import choose_eval_index
from .indicators import atr, ema, rsi, sma


class Candle(TypedDict):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _to_finite_series(values: list[Any]) -> list[float] | None:
    out: list[float] = []
    for value in values:
        parsed = _to_finite_float(value)
        if parsed is None:
            return None
        out.append(parsed)
    return out


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
    flags: list[str] | None = None
    days_in_trade_sessions: int | None = None
    time_stop_triggered: bool = False


def evaluate_sell_signals(
    ticker: str,
    candles: list[Candle],
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
    meta["data_dir"] = holding.get("data_dir")
    idx_eval, _ = choose_eval_index(candles, meta=meta)
    if idx_eval < 1:
        return SellEvaluation(action="REVIEW", reasons=["Not enough completed candles"])

    candles_eval = candles[: idx_eval + 1]
    if len(candles_eval) < settings.min_bars:
        return SellEvaluation(
            action="REVIEW",
            reasons=["Insufficient completed candles for sell evaluation"],
        )

    closes = _to_finite_series([c.get("close") for c in candles_eval])
    highs = _to_finite_series([c.get("high") for c in candles_eval])
    lows = _to_finite_series([c.get("low") for c in candles_eval])
    if closes is None or highs is None or lows is None:
        return SellEvaluation(
            action="REVIEW",
            reasons=["Invalid candle data: non-finite OHLC values"],
        )

    atr_values = atr(highs, lows, closes, 14)
    stop_override = holding.get("stop_override")
    target_override = holding.get("target_override")

    ema_len_short, ema_len_long = settings.ema_lengths
    ema_short = ema(closes, ema_len_short)
    ema_long = ema(closes, ema_len_long)
    rsi_values = rsi(closes, settings.rsi_period)

    latest = candles_eval[-1]
    close_today = closes[-1]
    eval_date = str(latest.get("date") or "") or None
    atr_today = atr_values[-1]

    reasons: list[str] = []
    flags: list[str] = []
    action = "HOLD"
    corporate_action_move = detect_corporate_action_move(closes)

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
        parsed_stop_override = _to_finite_float(stop_override)
        if parsed_stop_override is None:
            reasons.append("Invalid custom stop override ignored")
            action = "REVIEW" if action != "SELL" else action
        else:
            stop_price = parsed_stop_override
            reasons.append("Custom stop override in effect")
            if close_today <= stop_price:
                reasons.append("Price hit custom stop override")
                action = "SELL"
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
        trail_atr_values = atr_values[start_idx:]
        peak_close = float("-inf")
        trailing_stop: float | None = None
        stop_anchor_peak = 0.0
        stop_anchor_atr = 0.0
        for idx, trail_close in enumerate(trail_closes):
            peak_close = max(peak_close, trail_close)
            trail_atr = trail_atr_values[idx]
            if math.isnan(trail_atr) or trail_atr <= 0:
                continue
            next_stop = peak_close - settings.atr_trail_multiplier * trail_atr
            if trailing_stop is None or next_stop > trailing_stop:
                trailing_stop = next_stop
                stop_anchor_peak = peak_close
                stop_anchor_atr = trail_atr

        if trailing_stop is not None:
            stop_price = trailing_stop
            reasons.append(
                f"ATR trail (peak close {stop_anchor_peak:.2f}, ATR {stop_anchor_atr:.2f}) "
                f"{settings.atr_trail_multiplier:g}×ATR → {stop_price:.2f}"
            )
            if close_today <= stop_price:
                reasons.append("Price hit ATR trailing stop")
                action = "SELL"

    target_price = float(target_override) if target_override is not None else None

    # Time stop: days since entry
    time_stop_days = settings.time_stop_days
    days_in_trade_sessions: int | None = None
    time_stop_triggered = False
    if entry_date_str and time_stop_days > 0:
        try:
            entry_date = dt.date.fromisoformat(str(entry_date_str))
        except ValueError:
            reasons.append("Entry date missing/invalid; time stop skipped")
        else:
            eval_anchor = _parse_eval_date(eval_date)
            if eval_anchor is None:
                reasons.append(f"Time stop skipped: invalid eval_date {eval_date!r}")
            elif entry_date > eval_anchor:
                reasons.append("Time stop skipped: entry_date after eval_date")
                if action == "HOLD":
                    action = "REVIEW"
            else:
                resolved_market = _resolve_holding_market(
                    ticker=ticker, holding=holding
                )
                if resolved_market is None:
                    reasons.append(
                        "Time stop skipped: unable to resolve holding market"
                    )
                    if action == "HOLD":
                        action = "REVIEW"
                else:
                    days_in_trade_sessions = max(
                        count_trading_sessions(
                            entry_date,
                            eval_anchor,
                            market=resolved_market,
                            inclusive=True,
                            data_dir=(
                                str(holding.get("data_dir"))
                                if holding.get("data_dir")
                                else None
                            ),
                        )
                        - 1,
                        0,
                    )
                    if days_in_trade_sessions >= time_stop_days:
                        time_stop_triggered = True
                        reasons.append(
                            "Time stop: "
                            f"{days_in_trade_sessions} sessions >= {time_stop_days} sessions"
                        )
                        action = "REVIEW" if action != "SELL" else action

    if corporate_action_move is not None:
        reasons.append(
            "Potential corporate action: abnormal one-day move "
            f"{corporate_action_move * 100:.1f}%"
        )
        flags.append("CORPORATE_ACTION_SUSPECT")
        if action != "SELL":
            if action != "REVIEW":
                reasons.append(
                    "Corporate action suspect: manual review required before sell decision"
                )
            action = "REVIEW"

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
        flags=flags or None,
        days_in_trade_sessions=days_in_trade_sessions,
        time_stop_triggered=time_stop_triggered,
    )
