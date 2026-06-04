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


@dataclass(frozen=True)
class _SellOhlcSeries:
    opens: list[float]
    closes: list[float]


@dataclass(frozen=True)
class _HybridSellIndicators:
    ema_short: float | None
    ema_mid: float | None
    sma_trend: float | None
    rsi_today: float | None
    ema_short_prev: float | None
    ema_mid_prev: float | None


@dataclass(frozen=True)
class _EntryDateState:
    entry_date: dt.date | None
    invalid: bool
    after_eval: bool


@dataclass(frozen=True)
class _TimeStopResult:
    action: str
    reasons: list[str]
    days_in_trade_sessions: int | None
    triggered: bool


@dataclass(frozen=True)
class _ExitOverrideState:
    action: str
    reasons: list[str]
    stop_override: float | None
    target_override: float | None
    stop_price: float | None
    target_price: float | None


@dataclass(frozen=True)
class _ProfitProtectionState:
    action: str
    reasons: list[str]
    stop_price: float | None


@dataclass(frozen=True)
class _TrendBreakdownState:
    action: str
    reasons: list[str]


@dataclass(frozen=True)
class _FailedBreakoutState:
    action: str
    reasons: list[str]


@dataclass(frozen=True)
class _HardStopBandState:
    action: str
    reasons: list[str]
    stop_price: float | None


@dataclass(frozen=True)
class _CorporateActionGuardState:
    action: str
    reasons: list[str]
    flags: list[str]


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


def _extract_sell_ohlc_series(
    candles_eval: list[dict[str, float]],
) -> _SellOhlcSeries | None:
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
            return None
        opens.append(open_price)
        closes.append(close_price)
    return _SellOhlcSeries(opens=opens, closes=closes)


def _compute_hybrid_sell_indicators(
    closes: list[float],
    settings: HybridSellSettings,
) -> _HybridSellIndicators:
    ema_short = ema(closes, settings.ema_short_period)
    ema_mid = ema(closes, settings.ema_mid_period)
    sma_trend = sma(closes, settings.sma_trend_period)
    rsi_values = rsi(closes, settings.rsi_period)
    return _HybridSellIndicators(
        ema_short=_to_finite_float(ema_short[-1]) if ema_short else None,
        ema_mid=_to_finite_float(ema_mid[-1]) if ema_mid else None,
        sma_trend=_to_finite_float(sma_trend[-1]) if sma_trend else None,
        rsi_today=_to_finite_float(rsi_values[-1]) if rsi_values else None,
        ema_short_prev=_to_finite_float(ema_short[-2]) if len(ema_short) >= 2 else None,
        ema_mid_prev=_to_finite_float(ema_mid[-2]) if len(ema_mid) >= 2 else None,
    )


def _resolve_entry_date_state(
    holding: dict[str, Any],
    eval_anchor: dt.date | None,
) -> _EntryDateState:
    entry_date_str = holding.get("entry_date")
    if not entry_date_str:
        return _EntryDateState(entry_date=None, invalid=False, after_eval=False)
    try:
        entry_date = dt.date.fromisoformat(str(entry_date_str))
    except ValueError:
        return _EntryDateState(entry_date=None, invalid=True, after_eval=False)
    return _EntryDateState(
        entry_date=entry_date,
        invalid=False,
        after_eval=eval_anchor is not None and entry_date > eval_anchor,
    )


def _detect_hybrid_sell_corporate_action(
    *,
    closes: list[float],
    closes_since_entry: list[float] | None,
) -> float | None:
    corporate_action_move = detect_corporate_action_move(closes)
    if corporate_action_move is None and closes_since_entry:
        corporate_action_move = detect_corporate_action_move(
            closes_since_entry,
            lookback_bars=len(closes_since_entry),
        )
    return corporate_action_move


def _apply_time_stop_rules(
    *,
    ticker: str,
    holding: dict[str, Any],
    settings: HybridSellSettings,
    entry_date_state: _EntryDateState,
    eval_anchor: dt.date | None,
    eval_date: str | None,
    action: str,
    pnl_pct: float | None,
    last_close: float,
    indicators: _HybridSellIndicators,
) -> _TimeStopResult:
    reasons: list[str] = []
    action_out = action
    days_in_trade_sessions: int | None = None
    time_stop_triggered = False
    entry_date_str = holding.get("entry_date")
    time_stop_days = settings.time_stop_days
    time_stop_grace_days = settings.time_stop_grace_days
    time_stop_profit_floor = settings.time_stop_profit_floor
    if entry_date_str and time_stop_days > 0:
        if entry_date_state.invalid:
            reasons.append("Entry date missing/invalid; time stop skipped")
        elif eval_anchor is None:
            reasons.append(f"Time stop skipped: invalid eval_date {eval_date!r}")
        elif entry_date_state.after_eval:
            pass
        elif entry_date_state.entry_date is not None:
            resolved_market = _resolve_holding_market(ticker=ticker, holding=holding)
            if resolved_market is None:
                reasons.append("Time stop skipped: unable to resolve holding market")
                if action_out == "HOLD":
                    action_out = "REVIEW"
            else:
                days_in_trade_sessions = max(
                    count_trading_sessions(
                        entry_date_state.entry_date,
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
                    if action_out != "SELL":
                        action_out = "REVIEW"

    if (
        days_in_trade_sessions is not None
        and time_stop_days > 0
        and time_stop_grace_days > 0
        and days_in_trade_sessions >= (time_stop_days + time_stop_grace_days)
        and action_out != "SELL"
    ):
        pnl_ok = pnl_pct is not None and pnl_pct >= time_stop_profit_floor
        if (
            indicators.sma_trend is None
            or indicators.ema_short is None
            or indicators.ema_mid is None
        ):
            trend_available = False
            trend_ok = False
        else:
            trend_available = True
            trend_ok = (
                last_close >= indicators.sma_trend
                and indicators.ema_short >= indicators.ema_mid
            )
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
            action_out = "SELL"

    return _TimeStopResult(
        action=action_out,
        reasons=reasons,
        days_in_trade_sessions=days_in_trade_sessions,
        triggered=time_stop_triggered,
    )


def _apply_exit_overrides(
    *,
    holding: dict[str, Any],
    entry_price: float | None,
    last_close: float,
    settings: HybridSellSettings,
    action: str,
) -> _ExitOverrideState:
    stop_override = _to_finite_float(holding.get("stop_override"))
    target_override = _to_finite_float(holding.get("target_override"))
    stop_price: float | None = None
    target_price: float | None = None
    reasons: list[str] = []
    action_out = action

    if stop_override is not None:
        stop_price = stop_override
        reasons.append("Custom stop override in effect")
        if last_close <= stop_price:
            reasons.append("Price hit custom stop override")
            action_out = "SELL"

    if target_override is not None:
        target_price = target_override
        reasons.append("Custom target override in effect")
    elif entry_price is not None:
        # Suggest a notional target price (can be surfaced in report)
        target_price = entry_price * (1.0 + settings.profit_target_high)

    return _ExitOverrideState(
        action=action_out,
        reasons=reasons,
        stop_override=stop_override,
        target_override=target_override,
        stop_price=stop_price,
        target_price=target_price,
    )


def _apply_profit_protection(
    *,
    entry_price: float | None,
    pnl_pct: float | None,
    closes_since_entry: list[float] | None,
    last_close: float,
    corporate_action_move: float | None,
    entry_date_after_eval: bool,
    stop_override: float | None,
    stop_price: float | None,
    settings: HybridSellSettings,
    action: str,
) -> _ProfitProtectionState:
    profit_protection_stop: float | None = None
    profit_protection_high_armed = False
    reasons: list[str] = []
    action_out = action

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

    stop_price_out = stop_price
    if profit_protection_stop is not None and stop_override is None:
        stop_price_out = max(
            stop_price_out or profit_protection_stop,
            profit_protection_stop,
        )
        if last_close <= stop_price_out:
            reasons.append("Price closed below profit protection stop")
            if profit_protection_high_armed:
                action_out = "SELL"
            elif action_out != "SELL":
                action_out = "REVIEW"

    return _ProfitProtectionState(
        action=action_out,
        reasons=reasons,
        stop_price=stop_price_out,
    )


def _apply_trend_breakdown_rules(
    *,
    opens: list[float],
    closes: list[float],
    last_close: float,
    indicators: _HybridSellIndicators,
    action: str,
) -> _TrendBreakdownState:
    reasons: list[str] = []
    action_out = action
    ema_s = indicators.ema_short
    ema_m = indicators.ema_mid
    sma_t = indicators.sma_trend
    rsi_today = indicators.rsi_today
    ema_s_prev = indicators.ema_short_prev
    ema_m_prev = indicators.ema_mid_prev

    if ema_s is not None and last_close < ema_s:
        reasons.append("Close below EMA short")
        if action_out != "SELL":
            action_out = "REVIEW"
    if sma_t is not None and last_close < sma_t:
        reasons.append("Close below SMA trend (SMA20)")
        if action_out != "SELL":
            action_out = "REVIEW"

    if (
        ema_s is not None
        and ema_m is not None
        and ema_s_prev is not None
        and ema_m_prev is not None
        and ema_s < ema_m
        and ema_s_prev >= ema_m_prev
    ):
        reasons.append("EMA short crossed below EMA mid (momentum down)")
        action_out = "SELL"

    if len(closes) >= 3 and all(
        closes[idx] < opens[idx] for idx in range(len(closes) - 3, len(closes))
    ):
        reasons.append("Three consecutive bearish candles")
        if action_out != "SELL":
            action_out = "REVIEW"

    if rsi_today is not None and rsi_today < 50.0:
        reasons.append("RSI dropped below 50")
        if action_out != "SELL":
            action_out = "REVIEW"
    if rsi_today is not None and rsi_today < 40.0:
        reasons.append("RSI dropped into oversold zone (<40)")
        action_out = "SELL"

    return _TrendBreakdownState(action=action_out, reasons=reasons)


def _apply_failed_breakout_rules(
    *,
    holding: dict[str, Any],
    entry_price: float | None,
    pnl_pct: float | None,
    settings: HybridSellSettings,
    action: str,
) -> _FailedBreakoutState:
    if (
        entry_price is None
        or pnl_pct is None
        or not _is_breakout_holding(holding)
        or pnl_pct > -settings.failed_breakout_drop_pct
    ):
        return _FailedBreakoutState(action=action, reasons=[])

    return _FailedBreakoutState(
        action="SELL",
        reasons=[
            f"Failed breakout: price moved {pnl_pct * 100:.1f}% below entry "
            f"(threshold {settings.failed_breakout_drop_pct * 100:.1f}%)"
        ],
    )


def _apply_hard_stop_band(
    *,
    entry_price: float | None,
    last_close: float,
    stop_override: float | None,
    settings: HybridSellSettings,
    action: str,
    stop_price: float | None = None,
) -> _HardStopBandState:
    reasons: list[str] = []
    action_out = action
    stop_price_out = stop_price

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
                action_out = "SELL"
                stop_price_out = hard_stop_price
            elif loss_abs >= settings.stop_loss_pct_min:
                reasons.append(
                    f"Loss within hard stop band ({loss_abs * 100:.1f}% in "
                    f"{settings.stop_loss_pct_min * 100:.1f}%–"
                    f"{settings.stop_loss_pct_max * 100:.1f}%)"
                )
                if action_out != "SELL":
                    action_out = "REVIEW"
                stop_price_out = hard_stop_price

    return _HardStopBandState(
        action=action_out,
        reasons=reasons,
        stop_price=stop_price_out,
    )


def _apply_corporate_action_guard(
    *,
    corporate_action_move: float | None,
    action: str,
) -> _CorporateActionGuardState:
    if corporate_action_move is None:
        return _CorporateActionGuardState(action=action, reasons=[], flags=[])

    reasons = [
        "Potential corporate action: abnormal one-day move "
        f"{corporate_action_move * 100:.1f}%"
    ]
    flags = ["CORPORATE_ACTION_SUSPECT"]
    action_out = action
    if action_out != "SELL":
        if action_out != "REVIEW":
            reasons.append(
                "Corporate action suspect: manual review required before sell decision"
            )
        action_out = "REVIEW"

    return _CorporateActionGuardState(
        action=action_out,
        reasons=reasons,
        flags=flags,
    )


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

    ohlc = _extract_sell_ohlc_series(candles_eval)
    if ohlc is None:
        return HybridSellEvaluation(
            action="REVIEW",
            reasons=["Invalid candle data: non-finite OHLC values"],
        )
    opens = ohlc.opens
    closes = ohlc.closes

    latest = candles_eval[-1]
    last_close = closes[-1]
    eval_date = str(latest.get("date") or "") or None
    eval_anchor = _parse_eval_date(eval_date)

    indicators = _compute_hybrid_sell_indicators(closes, settings)
    ema_s = indicators.ema_short
    ema_m = indicators.ema_mid
    sma_t = indicators.sma_trend
    rsi_today = indicators.rsi_today

    reasons: list[str] = []
    flags: list[str] = []
    action = "HOLD"
    entry_date_state = _resolve_entry_date_state(holding, eval_anchor)
    if entry_date_state.after_eval:
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
    corporate_action_move = _detect_hybrid_sell_corporate_action(
        closes=closes,
        closes_since_entry=closes_since_entry,
    )

    entry_price = _to_finite_float(holding.get("entry_price"))
    pnl_pct = _compute_pnl_pct(entry_price, last_close)

    # --- 1) Profit taking logic ---
    exit_overrides = _apply_exit_overrides(
        holding=holding,
        entry_price=entry_price,
        last_close=last_close,
        settings=settings,
        action=action,
    )
    stop_override = exit_overrides.stop_override
    stop_price = exit_overrides.stop_price
    target_price = exit_overrides.target_price
    reasons.extend(exit_overrides.reasons)
    action = exit_overrides.action

    profit_protection = _apply_profit_protection(
        entry_price=entry_price,
        pnl_pct=pnl_pct,
        closes_since_entry=closes_since_entry,
        last_close=last_close,
        corporate_action_move=corporate_action_move,
        entry_date_after_eval=entry_date_state.after_eval,
        stop_override=stop_override,
        stop_price=stop_price,
        settings=settings,
        action=action,
    )
    reasons.extend(profit_protection.reasons)
    action = profit_protection.action
    stop_price = profit_protection.stop_price

    # --- 2) Trend breakdown (EMA/SMA + RSI) ---
    trend_breakdown = _apply_trend_breakdown_rules(
        opens=opens,
        closes=closes,
        last_close=last_close,
        indicators=indicators,
        action=action,
    )
    reasons.extend(trend_breakdown.reasons)
    action = trend_breakdown.action

    # --- 3) Failed breakout ---
    failed_breakout = _apply_failed_breakout_rules(
        holding=holding,
        entry_price=entry_price,
        pnl_pct=pnl_pct,
        settings=settings,
        action=action,
    )
    reasons.extend(failed_breakout.reasons)
    action = failed_breakout.action

    # --- 4) Hard stop loss band (3–5%) ---
    hard_stop_band = _apply_hard_stop_band(
        entry_price=entry_price,
        last_close=last_close,
        stop_override=stop_override,
        settings=settings,
        action=action,
        stop_price=stop_price,
    )
    reasons.extend(hard_stop_band.reasons)
    action = hard_stop_band.action
    stop_price = hard_stop_band.stop_price

    # --- 5) Optional time stop ---
    time_stop = _apply_time_stop_rules(
        ticker=ticker,
        holding=holding,
        settings=settings,
        entry_date_state=entry_date_state,
        eval_anchor=eval_anchor,
        eval_date=eval_date,
        action=action,
        pnl_pct=pnl_pct,
        last_close=last_close,
        indicators=indicators,
    )
    action = time_stop.action
    reasons.extend(time_stop.reasons)
    days_in_trade_sessions = time_stop.days_in_trade_sessions
    time_stop_triggered = time_stop.triggered

    corporate_action_guard = _apply_corporate_action_guard(
        corporate_action_move=corporate_action_move,
        action=action,
    )
    action = corporate_action_guard.action
    reasons.extend(corporate_action_guard.reasons)
    flags.extend(corporate_action_guard.flags)

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
