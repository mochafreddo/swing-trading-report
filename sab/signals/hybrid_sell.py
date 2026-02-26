from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from ..data.trading_sessions import count_trading_sessions
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


def _to_finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _normalize_candle_date(value: Any) -> str:
    date_text = str(value or "").strip().replace("-", "")
    return date_text[:8]


def _parse_eval_date(value: Any) -> dt.date | None:
    date_text = _normalize_candle_date(value)
    if not date_text:
        return None
    try:
        return dt.datetime.strptime(date_text, "%Y%m%d").date()
    except ValueError:
        return None


_US_EXCHANGE_CODES = {"US", "NASDAQ", "NASD", "NAS", "NYSE", "NYS", "AMEX", "AMS"}


def _resolve_holding_market(*, ticker: str, holding: dict[str, Any]) -> str | None:
    exchange_raw = str(holding.get("exchange") or "").strip().upper()
    if exchange_raw in _US_EXCHANGE_CODES:
        return "US"

    currency_raw = (
        str(holding.get("entry_currency") or holding.get("currency") or "")
        .strip()
        .upper()
    )
    if currency_raw == "USD":
        return "US"
    if currency_raw == "KRW":
        return "KR"

    normalized_ticker = str(ticker or "").strip().upper()
    if "." in normalized_ticker:
        suffix = normalized_ticker.rsplit(".", 1)[1].strip().upper()
        if suffix in _US_EXCHANGE_CODES:
            return "US"

    return None


_SPLIT_LIKE_RATIOS: tuple[float, ...] = (
    0.5,  # 2:1 split
    1 / 3,  # 3:1 split
    0.25,  # 4:1 split
    0.2,  # 5:1 split
    2.0,  # 1:2 reverse split
    3.0,  # 1:3 reverse split
    4.0,  # 1:4 reverse split
    5.0,  # 1:5 reverse split
    10.0,  # 1:10 reverse split
)


def _is_split_like_ratio(ratio: float, *, tolerance_pct: float = 0.08) -> bool:
    if ratio <= 0:
        return False
    for target in _SPLIT_LIKE_RATIOS:
        if abs(ratio - target) / target <= tolerance_pct:
            return True
    return False


def _detect_corporate_action_move(
    closes: list[float], *, lookback_bars: int = 5, threshold_pct: float = 0.45
) -> float | None:
    if len(closes) < 2:
        return None
    start_idx = max(1, len(closes) - lookback_bars)
    for idx in range(start_idx, len(closes)):
        prev_close = closes[idx - 1]
        if prev_close <= 0:
            continue
        split_ratio = closes[idx] / prev_close
        change_pct = (closes[idx] - prev_close) / prev_close
        if abs(change_pct) >= threshold_pct and _is_split_like_ratio(split_ratio):
            return change_pct
    return None


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

    ema_short = ema(closes, settings.ema_short_period)
    ema_mid = ema(closes, settings.ema_mid_period)
    sma_trend = sma(closes, settings.sma_trend_period)
    rsi_values = rsi(closes, settings.rsi_period)

    reasons: list[str] = []
    flags: list[str] = []
    action = "HOLD"
    corporate_action_move = _detect_corporate_action_move(closes)

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
    if len(candles_eval) >= 3 and all(
        closes[idx] < opens[idx] for idx in range(len(closes) - 3, len(closes))
    ):
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
    entry_date_str = holding.get("entry_date")
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
    "HybridSellSettings",
    "HybridSellEvaluation",
    "evaluate_sell_signals_hybrid",
]
