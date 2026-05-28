from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from ..data.trading_sessions import count_trading_sessions
from ..utils.numeric import to_finite_float as _to_finite_float
from ._candle_dates import parse_eval_date as _parse_eval_date
from ._holding_market import resolve_holding_market as _resolve_holding_market
from .corporate_action import detect_corporate_action_move
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
    flags: list[str] | None = None
    days_in_trade_sessions: int | None = None
    time_stop_triggered: bool = False


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


def _closes_since_entry(
    *,
    candles_eval: list[dict[str, float]],
    holding: dict[str, Any],
) -> list[float] | None:
    entry_date = _parse_eval_date(holding.get("entry_date"))
    if entry_date is None:
        return None

    closes_since_entry: list[float] = []
    for candle in candles_eval:
        candle_date = _parse_eval_date(candle.get("date"))
        if candle_date is None or candle_date < entry_date:
            continue
        close_price = _to_finite_float(candle.get("close"))
        if close_price is not None:
            closes_since_entry.append(close_price)
    return closes_since_entry


def _compute_peak_pnl_pct_since_entry(
    *,
    entry_price: float | None,
    closes_since_entry: list[float] | None,
    fallback_close: float,
) -> tuple[float | None, bool]:
    current_pnl = _compute_pnl_pct(entry_price, fallback_close)
    if entry_price is None or closes_since_entry is None:
        return current_pnl, False

    if not closes_since_entry:
        return None, False
    return _compute_pnl_pct(entry_price, max(closes_since_entry)), True


def _is_breakout_holding(holding: dict[str, Any]) -> bool:
    markers: list[str] = []
    for key in ("strategy", "pattern", "entry_pattern", "signal_pattern"):
        value = holding.get(key)
        if value is not None:
            markers.append(str(value))

    tags = holding.get("tags")
    if isinstance(tags, list | tuple | set):
        markers.extend(str(tag) for tag in tags)
    elif tags is not None:
        markers.append(str(tags))

    return any("breakout" in marker.strip().lower() for marker in markers)


def evaluate_sell_signals_hybrid(
    ticker: str,
    candles: list[dict[str, float]],
    holding: dict[str, Any],
    settings: HybridSellSettings,
) -> HybridSellEvaluation:
    required_bars = max(settings.min_bars, 2)
    if len(candles) < required_bars:
        return HybridSellEvaluation(
            action="REVIEW", reasons=["Insufficient data for hybrid sell evaluation"]
        )

    meta_currency = holding.get("entry_currency") or holding.get("currency")
    meta = {"currency": meta_currency} if meta_currency else {}
    meta["exchange"] = holding.get("exchange")
    meta["data_source"] = holding.get("data_source")
    meta["data_dir"] = holding.get("data_dir")
    idx_eval, _ = choose_eval_index(candles, meta=meta)
    if idx_eval < 1:
        return HybridSellEvaluation(
            action="REVIEW", reasons=["Not enough completed candles for hybrid sell"]
        )

    candles_eval = candles[: idx_eval + 1]
    if len(candles_eval) < required_bars:
        return HybridSellEvaluation(
            action="REVIEW",
            reasons=["Insufficient completed candles for hybrid sell"],
        )

    opens: list[float] = []
    closes: list[float] = []
    for candle in candles_eval:
        open_price = _to_finite_float(candle.get("open"))
        high_price = _to_finite_float(candle.get("high"))
        low_price = _to_finite_float(candle.get("low"))
        close_price = _to_finite_float(candle.get("close"))
        if (
            open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
        ):
            return HybridSellEvaluation(
                action="REVIEW",
                reasons=["Invalid candle data: non-finite OHLC values"],
            )
        opens.append(open_price)
        closes.append(close_price)

    latest = candles_eval[-1]
    last_close = closes[-1]
    eval_date = str(latest.get("date") or "") or None
    eval_anchor = _parse_eval_date(eval_date)

    ema_short = ema(closes, settings.ema_short_period)
    ema_mid = ema(closes, settings.ema_mid_period)
    sma_trend = sma(closes, settings.sma_trend_period)
    rsi_values = rsi(closes, settings.rsi_period)
    ema_s = _to_finite_float(ema_short[-1]) if ema_short else None
    ema_m = _to_finite_float(ema_mid[-1]) if ema_mid else None
    sma_t = _to_finite_float(sma_trend[-1]) if sma_trend else None
    rsi_today = _to_finite_float(rsi_values[-1]) if rsi_values else None
    ema_s_prev = _to_finite_float(ema_short[-2]) if len(ema_short) >= 2 else None
    ema_m_prev = _to_finite_float(ema_mid[-2]) if len(ema_mid) >= 2 else None

    reasons: list[str] = []
    flags: list[str] = []
    action = "HOLD"
    entry_date_str = holding.get("entry_date")
    entry_date: dt.date | None = None
    entry_date_invalid = False
    entry_date_after_eval = False
    if entry_date_str:
        try:
            entry_date = dt.date.fromisoformat(str(entry_date_str))
        except ValueError:
            entry_date_invalid = True
        else:
            if eval_anchor is not None and entry_date > eval_anchor:
                entry_date_after_eval = True
                reasons.append("Time stop skipped: entry_date after eval_date")
                action = "REVIEW"
    missing_indicators = [
        label
        for label, value in (
            ("EMA short", ema_s),
            ("EMA mid", ema_m),
            ("SMA trend", sma_t),
            ("RSI", rsi_today),
        )
        if value is None
    ]
    if missing_indicators:
        reasons.append(
            "Indicator data unavailable for hybrid sell: "
            + ", ".join(missing_indicators)
        )
        action = "REVIEW"

    closes_since_entry = _closes_since_entry(
        candles_eval=candles_eval,
        holding=holding,
    )
    corporate_action_move = detect_corporate_action_move(closes)
    if corporate_action_move is None and closes_since_entry:
        corporate_action_move = detect_corporate_action_move(
            closes_since_entry,
            lookback_bars=len(closes_since_entry),
        )

    entry_price = _to_finite_float(holding.get("entry_price"))
    stop_override = _to_finite_float(holding.get("stop_override"))
    target_override = _to_finite_float(holding.get("target_override"))

    pnl_pct = _compute_pnl_pct(entry_price, last_close)

    # --- 1) Profit taking logic ---
    stop_price: float | None = None
    target_price: float | None = None
    if stop_override is not None:
        stop_price = stop_override
        reasons.append("Custom stop override in effect")
        if last_close <= stop_price:
            reasons.append("Price hit custom stop override")
            action = "SELL"

    if target_override is not None:
        target_price = target_override
        reasons.append("Custom target override in effect")
    elif entry_price is not None:
        # Suggest a notional target price (can be surfaced in report)
        target_price = entry_price * (1.0 + settings.profit_target_high)

    profit_protection_stop: float | None = None
    profit_protection_high_armed = False
    if corporate_action_move:
        if entry_date_after_eval:
            profit_basis_pnl, profit_basis_uses_peak = None, False
        else:
            profit_basis_pnl, profit_basis_uses_peak = pnl_pct, False
    else:
        profit_basis_pnl, profit_basis_uses_peak = _compute_peak_pnl_pct_since_entry(
            entry_price=entry_price,
            closes_since_entry=closes_since_entry,
            fallback_close=last_close,
        )
    if entry_price is not None and profit_basis_pnl is not None:
        profit_label = (
            f"peak {profit_basis_pnl * 100:.1f}%"
            if profit_basis_uses_peak
            else f"{profit_basis_pnl * 100:.1f}%"
        )
        if profit_basis_pnl >= settings.partial_profit_floor:
            profit_protection_stop = entry_price
            reasons.append(
                "Profit protection armed at break-even "
                f"({profit_label} ≥ {settings.partial_profit_floor * 100:.1f}%)"
            )
        if profit_basis_pnl >= settings.profit_target_low:
            tightened_stop = entry_price * (1.0 + settings.partial_profit_floor)
            profit_protection_stop = max(
                profit_protection_stop or tightened_stop,
                tightened_stop,
            )
            reasons.append(
                "Profit protection tightened above entry "
                f"({profit_label} ≥ {settings.profit_target_low * 100:.1f}%)"
            )
        if profit_basis_pnl >= settings.profit_target_high:
            profit_protection_high_armed = True
            extended_stop = entry_price * (1.0 + settings.profit_target_low)
            profit_protection_stop = max(
                profit_protection_stop or extended_stop,
                extended_stop,
            )
            reasons.append(
                "High-target profit protection activated "
                f"({profit_label} ≥ {settings.profit_target_high * 100:.1f}%)"
            )
    if profit_protection_stop is not None and stop_override is None:
        stop_price = max(stop_price or profit_protection_stop, profit_protection_stop)
        if last_close <= stop_price:
            reasons.append("Price closed below profit protection stop")
            if profit_protection_high_armed:
                action = "SELL"
            elif action != "SELL":
                action = "REVIEW"

    # --- 2) Trend breakdown (EMA/SMA + RSI) ---
    # Price relative to EMA/SMA
    if ema_s is not None and last_close < ema_s:
        reasons.append("Close below EMA short")
        if action != "SELL":
            action = "REVIEW"
    if sma_t is not None and last_close < sma_t:
        reasons.append("Close below SMA trend (SMA20)")
        if action != "SELL":
            action = "REVIEW"

    # Momentum shift: EMA short falling below EMA mid
    if (
        ema_s is not None
        and ema_m is not None
        and ema_s_prev is not None
        and ema_m_prev is not None
        and ema_s < ema_m
        and ema_s_prev >= ema_m_prev
    ):
        reasons.append("EMA short crossed below EMA mid (momentum down)")
        action = "SELL"

    # Consecutive bearish candles
    if len(candles_eval) >= 3 and all(
        closes[idx] < opens[idx] for idx in range(len(closes) - 3, len(closes))
    ):
        reasons.append("Three consecutive bearish candles")
        if action != "SELL":
            action = "REVIEW"

    # RSI breakdowns
    if rsi_today is not None and rsi_today < 50.0:
        reasons.append("RSI dropped below 50")
        if action != "SELL":
            action = "REVIEW"
    if rsi_today is not None and rsi_today < 40.0:
        reasons.append("RSI dropped into oversold zone (<40)")
        action = "SELL"

    # --- 3) Failed breakout ---
    # If holding strategy is breakout-like, consider a sharp drop > failed_breakout_drop_pct
    if (
        entry_price is not None
        and pnl_pct is not None
        and _is_breakout_holding(holding)
        and pnl_pct <= -settings.failed_breakout_drop_pct
    ):
        reasons.append(
            f"Failed breakout: price moved {pnl_pct * 100:.1f}% below entry "
            f"(threshold {settings.failed_breakout_drop_pct * 100:.1f}%)"
        )
        action = "SELL"

    # --- 4) Hard stop loss band (3–5%) ---
    if entry_price is not None and stop_override is None:
        loss_pct = _compute_pnl_pct(entry_price, last_close)
        if loss_pct is not None and loss_pct < 0:
            loss_abs = abs(loss_pct)
            hard_stop_price = entry_price * (1.0 - settings.stop_loss_pct_max)
            if loss_abs >= settings.stop_loss_pct_max:
                reasons.append(
                    f"Hit hard stop max (loss {loss_abs * 100:.1f}% ≥ "
                    f"{settings.stop_loss_pct_max * 100:.1f}% max)"
                )
                action = "SELL"
                stop_price = hard_stop_price
            elif loss_abs >= settings.stop_loss_pct_min:
                reasons.append(
                    f"Loss within hard stop band ({loss_abs * 100:.1f}% in "
                    f"{settings.stop_loss_pct_min * 100:.1f}%–"
                    f"{settings.stop_loss_pct_max * 100:.1f}%)"
                )
                if action != "SELL":
                    action = "REVIEW"
                stop_price = hard_stop_price

    # --- 5) Optional time stop ---
    time_stop_days = settings.time_stop_days
    time_stop_grace_days = settings.time_stop_grace_days
    time_stop_profit_floor = settings.time_stop_profit_floor
    days_in_trade_sessions: int | None = None
    time_stop_triggered = False
    if entry_date_str and time_stop_days > 0:
        if entry_date_invalid:
            reasons.append("Entry date missing/invalid; time stop skipped")
        elif eval_anchor is None:
            reasons.append(f"Time stop skipped: invalid eval_date {eval_date!r}")
        elif entry_date_after_eval:
            pass
        elif entry_date is not None:
            resolved_market = _resolve_holding_market(ticker=ticker, holding=holding)
            if resolved_market is None:
                reasons.append("Time stop skipped: unable to resolve holding market")
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
                        f"{days_in_trade_sessions} sessions ≥ {time_stop_days} sessions"
                    )
                    if action != "SELL":
                        action = "REVIEW"

    # Extended time stop: only if a grace window is configured
    if (
        days_in_trade_sessions is not None
        and time_stop_days > 0
        and time_stop_grace_days > 0
        and days_in_trade_sessions >= (time_stop_days + time_stop_grace_days)
        and action != "SELL"
    ):
        pnl_ok = pnl_pct is not None and pnl_pct >= time_stop_profit_floor
        if sma_t is None or ema_s is None or ema_m is None:
            trend_available = False
            trend_ok = False
        else:
            trend_available = True
            trend_ok = last_close >= sma_t and ema_s >= ema_m
        weak_bits = []
        if not pnl_ok:
            if pnl_pct is None:
                weak_bits.append("P&L unavailable")
            else:
                weak_bits.append(
                    f"P&L {pnl_pct * 100:.1f}% < floor {time_stop_profit_floor * 100:.1f}%"
                )
        if trend_available and not trend_ok:
            weak_bits.append("trend below SMA/EMA")
        elif not trend_available and not pnl_ok:
            weak_bits.append("trend indicators unavailable")

        should_sell_for_extended_time_stop = not pnl_ok or (
            trend_available and not trend_ok
        )
        if should_sell_for_extended_time_stop:
            reason_detail = "; ".join(weak_bits) if weak_bits else "weak trend/return"
            reasons.append(
                f"Extended time stop: {days_in_trade_sessions} sessions ≥ "
                f"{time_stop_days + time_stop_grace_days} sessions ({reason_detail})"
            )
            action = "SELL"

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
        reasons.append("No hybrid sell criteria triggered")

    return HybridSellEvaluation(
        action=action,
        reasons=reasons,
        stop_price=stop_price,
        target_price=target_price,
        eval_price=last_close,
        eval_index=idx_eval,
        eval_date=eval_date,
        flags=flags or None,
        days_in_trade_sessions=days_in_trade_sessions,
        time_stop_triggered=time_stop_triggered,
    )


__all__ = [
    "HybridSellEvaluation",
    "HybridSellSettings",
    "evaluate_sell_signals_hybrid",
]
