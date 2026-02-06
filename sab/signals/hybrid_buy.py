from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .etf_filters import is_etf_or_leveraged
from .eval_index import choose_eval_index
from .indicators import atr, ema, rsi, sma


class HybridPattern(StrEnum):
    TREND_PULLBACK_BOUNCE = "trend_pullback_bounce"
    SWING_HIGH_BREAKOUT = "swing_high_breakout"
    RSI_OVERSOLD_REVERSAL = "rsi_oversold_reversal"


@dataclass
class HybridEvaluationSettings:
    sma_trend_period: int
    ema_short_period: int
    ema_mid_period: int
    rsi_period: int
    rsi_zone_low: float
    rsi_zone_high: float
    rsi_oversold_low: float
    rsi_oversold_high: float
    pullback_max_bars: int
    breakout_consolidation_min_bars: int
    breakout_consolidation_max_bars: int
    volume_lookback_days: int
    max_gap_pct: float
    use_sma60_filter: bool
    sma60_period: int
    kr_breakout_requires_confirmation: bool
    gap_atr_multiplier: float
    # shared filters
    min_history_bars: int
    min_price: float
    us_min_price: float | None
    min_dollar_volume: float
    us_min_dollar_volume: float | None
    exclude_etf_etn: bool


@dataclass
class HybridEvaluationResult:
    ticker: str
    candidate: dict[str, Any] | None
    reason: str | None = None


def _avg_dollar_volume(candles: list[dict[str, Any]], window: int) -> float:
    if not candles:
        return 0.0
    sub = candles[-window:] if len(candles) >= window else candles
    total = 0.0
    count = 0
    for c in sub:
        price = float(c.get("close") or 0.0)
        volume = float(c.get("volume") or 0.0)
        total += price * volume
        count += 1
    return total / count if count else 0.0


def _basic_filters(
    ticker: str,
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
    meta: dict[str, Any],
    eval_index: int,
) -> tuple[bool, str | None, float, float]:
    if len(candles) < settings.min_history_bars:
        return (
            False,
            f"Not enough history (<{settings.min_history_bars} bars)",
            0.0,
            0.0,
        )

    idx = max(0, min(eval_index, len(candles) - 1))
    latest = candles[idx]
    currency = str(meta.get("currency", "KRW")).upper()

    close = float(latest.get("close") or 0.0)
    eff_min_price = settings.min_price
    if currency == "USD" and settings.us_min_price is not None:
        eff_min_price = settings.us_min_price
    if eff_min_price and close < eff_min_price:
        return False, f"Price {close:.2f} < MIN_PRICE {eff_min_price:.2f}", 0.0, 0.0

    avg_dv = _avg_dollar_volume(candles[: idx + 1], 20)
    eff_min_dv = settings.min_dollar_volume
    if currency == "USD" and settings.us_min_dollar_volume is not None:
        eff_min_dv = settings.us_min_dollar_volume
    if eff_min_dv > 0 and avg_dv < eff_min_dv:
        return (
            False,
            f"Avg dollar volume {avg_dv:,.0f} < {eff_min_dv:,.0f}",
            0.0,
            avg_dv,
        )

    if settings.exclude_etf_etn and is_etf_or_leveraged(ticker, meta):
        return False, "ETF/ETN excluded", close, avg_dv

    return True, None, close, avg_dv


def _volume_stats(
    candles: list[dict[str, Any]], lookback_days: int
) -> tuple[float, float]:
    if not candles:
        return 0.0, 0.0
    vols = [float(c.get("volume") or 0.0) for c in candles]
    prev_vol = vols[-2] if len(vols) >= 2 else vols[-1]
    window = vols[-lookback_days:] if len(vols) >= lookback_days else vols
    avg_vol = sum(window) / len(window) if window else 0.0
    return prev_vol, avg_vol


def _detect_trend_pullback_bounce(
    closes: list[float],
    sma_trend: list[float],
    ema_short: list[float],
    ema_mid: list[float],
    rsi_vals: list[float],
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
) -> tuple[bool, list[str], HybridPattern | None, dict[str, Any]]:
    reasons: list[str] = []
    idx = len(closes) - 1
    close = closes[idx]
    sma_val = sma_trend[idx]
    rsi_val = rsi_vals[idx]

    if not (close > sma_val):
        return False, ["Close not above SMA trend"], None, {}
    if not (ema_short[idx] >= ema_mid[idx]):
        return False, ["EMA short < EMA mid (momentum missing)"], None, {}
    if not (settings.rsi_zone_low <= rsi_val <= settings.rsi_zone_high):
        return False, ["RSI not in swing zone"], None, {}

    prev_vol, avg_vol = _volume_stats(candles, settings.volume_lookback_days)

    # Pullback region: last N bars where close <= ema_short
    pullback_bars = 0
    for i in range(idx, -1, -1):
        if closes[i] <= ema_short[i]:
            pullback_bars += 1
            if pullback_bars > settings.pullback_max_bars:
                break
        else:
            break

    # Very rough check for heavy selling: big red bar with volume >> avg
    heavy_selling = False
    for bar in candles[-pullback_bars:]:
        bar_open = float(bar.get("open") or 0.0)
        bar_close = float(bar.get("close") or 0.0)
        bar_volume = float(bar.get("volume") or 0.0)
        if bar_close < bar_open and avg_vol > 0 and bar_volume > avg_vol * 1.5:
            heavy_selling = True
            break
    if heavy_selling:
        return False, ["Heavy selling volume during pullback"], None, {}

    # Triggers
    triggered = False
    flags: dict[str, Any] = {
        "rsi_val": rsi_val,
        "avg_vol": avg_vol,
        "today_vol": float(candles[-1].get("volume") or 0.0),
        "close_above_ema_short": close > ema_short[idx],
    }
    if idx >= 1 and closes[idx - 1] <= ema_short[idx - 1] and close > ema_short[idx]:
        reasons.append("Close reclaimed EMA short")
        triggered = True
        flags["trigger_reclaim"] = True

    today = candles[-1]
    yest = candles[-2] if len(candles) >= 2 else None
    if yest is not None:
        o = float(today.get("open") or 0.0)
        close_today = float(today.get("close") or 0.0)
        v = float(today.get("volume") or 0.0)
        prev_v = float(yest.get("volume") or 0.0)
        if close_today > o and v > max(prev_v, avg_vol):
            reasons.append("Bullish candle with rising volume")
            triggered = True
            flags["trigger_bullish_vol"] = True

    if idx >= 1 and rsi_vals[idx - 1] <= 50 < rsi_val:
        reasons.append("RSI crossed above 50")
        triggered = True
        flags["trigger_rsi50"] = True

    low = float(today.get("low") or 0.0)
    body = abs(close - float(today.get("open") or close))
    lower_shadow = min(close, float(today.get("open") or close)) - low
    if lower_shadow > body and abs(low - ema_short[idx]) / close < 0.02:
        reasons.append("Reversal candle near EMA short")
        triggered = True
        flags["trigger_hammer_near_ema"] = True

    if not triggered:
        return False, ["No pullback-bounce trigger"], None, flags

    return True, reasons, HybridPattern.TREND_PULLBACK_BOUNCE, flags


def _detect_swing_high_breakout(
    closes: list[float],
    sma_trend: list[float],
    ema_short: list[float],
    ema_mid: list[float],
    rsi_vals: list[float],
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
    currency: str,
) -> tuple[bool, list[str], HybridPattern | None, dict[str, Any]]:
    idx = len(closes) - 1
    close = closes[idx]
    reasons: list[str] = []

    if not (ema_short[idx] > ema_mid[idx] > sma_trend[idx]):
        return False, ["EMAs not aligned for uptrend"], None, {}
    if rsi_vals[idx] >= 60:
        return False, ["RSI too extended for breakout"], None, {}

    # Consolidation: price staying within a relatively tight range
    min_bars = settings.breakout_consolidation_min_bars
    max_bars = settings.breakout_consolidation_max_bars
    window = candles[-max_bars:] if len(candles) >= max_bars else candles
    if len(window) < min_bars:
        return False, ["Not enough bars for consolidation"], None, {}

    highs = [float(c.get("high") or 0.0) for c in window]
    lows = [float(c.get("low") or 0.0) for c in window]
    swing_high = max(highs[:-1]) if len(highs) > 1 else highs[0]
    range_pct = (max(highs) - min(lows)) / swing_high if swing_high else 0.0
    if range_pct > 0.1:
        return False, ["Consolidation range too wide"], None, {"swing_high": swing_high}

    today = candles[-1]
    prev_vol, avg_vol = _volume_stats(candles, settings.volume_lookback_days)
    if not (close > swing_high and float(today.get("volume") or 0.0) > avg_vol):
        return (
            False,
            ["No confirmed breakout over swing high"],
            None,
            {"swing_high": swing_high},
        )

    # KR-specific confirmation can be applied later in entry logic; for now we only mark pattern.
    reasons.append("Close broke above recent swing high with volume > 5d avg")
    return (
        True,
        reasons,
        HybridPattern.SWING_HIGH_BREAKOUT,
        {
            "swing_high": swing_high,
            "avg_vol": avg_vol,
        },
    )


def _detect_rsi_oversold_reversal(
    closes: list[float],
    sma_trend: list[float],
    ema_short: list[float],
    ema_mid: list[float],
    rsi_vals: list[float],
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
) -> tuple[bool, list[str], HybridPattern | None, dict[str, Any]]:
    idx = len(closes) - 1
    close = closes[idx]
    sma_val = sma_trend[idx]
    rsi_val = rsi_vals[idx]
    reasons: list[str] = []

    if not (close > sma_val):
        return False, ["Price not above SMA trend"], None, {}

    # EMA short dipping below EMA mid temporarily is allowed; we do not enforce it strictly here.
    if not (
        settings.rsi_oversold_low <= rsi_vals[idx - 1] <= settings.rsi_oversold_high
        and rsi_val > 40
    ):
        return False, ["RSI did not rebound from oversold band"], None, {}

    today = candles[-1]
    prev_vol, avg_vol = _volume_stats(candles, settings.volume_lookback_days)
    o = float(today.get("open") or 0.0)
    c = float(today.get("close") or 0.0)
    v = float(today.get("volume") or 0.0)
    if c <= o or not (avg_vol == 0.0 or v >= avg_vol):
        return False, ["No strong bullish candle with rising volume"], None, {}

    low = float(today.get("low") or 0.0)
    body = abs(c - o)
    lower_shadow = min(c, o) - low
    if lower_shadow <= body:
        return False, ["No clear reversal candle off lows"], None, {}

    if (
        abs(low - ema_short[idx]) / close < 0.03
        or abs(low - ema_mid[idx]) / close < 0.03
    ):
        reasons.append("Reversal off EMA short/mid with volume")
        return (
            True,
            reasons,
            HybridPattern.RSI_OVERSOLD_REVERSAL,
            {
                "avg_vol": avg_vol,
                "rsi_val": rsi_val,
                "close_above_ema_short": close > ema_short[idx],
                "close_above_ema_mid": close > ema_mid[idx],
            },
        )

    return False, ["Reversal not near EMA support"], None, {}


def evaluate_ticker_hybrid(
    ticker: str,
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
    meta: dict[str, Any] | None = None,
) -> HybridEvaluationResult:
    meta = meta or {}
    currency = str(meta.get("currency", "KRW")).upper()

    provider = str(meta.get("data_source") or meta.get("provider") or "kis").lower()
    idx_eval, _ = choose_eval_index(candles, meta=meta, provider=provider)
    if idx_eval < 0:
        return HybridEvaluationResult(ticker, None, "No candle data")

    candles_eval = candles[: idx_eval + 1]

    ok, reason, last_close, avg_dv = _basic_filters(
        ticker, candles, settings, meta, idx_eval
    )
    if not ok:
        return HybridEvaluationResult(ticker, None, reason)

    closes = [float(c.get("close") or 0.0) for c in candles_eval]
    highs = [float(c.get("high") or 0.0) for c in candles_eval]
    lows = [float(c.get("low") or 0.0) for c in candles_eval]
    sma_trend = sma(closes, settings.sma_trend_period)
    ema_short = ema(closes, settings.ema_short_period)
    ema_mid = ema(closes, settings.ema_mid_period)
    rsi_vals = rsi(closes, settings.rsi_period)
    atr_vals = atr(highs, lows, closes, 14)
    atr_value = atr_vals[-1] if atr_vals else float("nan")

    pattern: HybridPattern | None = None
    pattern_reasons: list[str] = []
    pattern_context: dict[str, Any] = {}

    # 1) Trend continuation + pullback bounce (highest priority)
    ok_pb, reasons_pb, pat_pb, ctx_pb = _detect_trend_pullback_bounce(
        closes, sma_trend, ema_short, ema_mid, rsi_vals, candles_eval, settings
    )
    if ok_pb and pat_pb:
        pattern = pat_pb
        pattern_reasons = reasons_pb
        pattern_context = ctx_pb
    else:
        # 2) Swing high breakout
        ok_bo, reasons_bo, pat_bo, ctx_bo = _detect_swing_high_breakout(
            closes,
            sma_trend,
            ema_short,
            ema_mid,
            rsi_vals,
            candles_eval,
            settings,
            currency,
        )
        if ok_bo and pat_bo:
            pattern = pat_bo
            pattern_reasons = reasons_bo
            pattern_context = ctx_bo
        else:
            # 3) RSI oversold reversal
            ok_rsi, reasons_rsi, pat_rsi, ctx_rsi = _detect_rsi_oversold_reversal(
                closes, sma_trend, ema_short, ema_mid, rsi_vals, candles_eval, settings
            )
            if ok_rsi and pat_rsi:
                pattern = pat_rsi
                pattern_reasons = reasons_rsi
                pattern_context = ctx_rsi

    if not pattern:
        return HybridEvaluationResult(
            ticker, None, "Did not meet hybrid signal criteria"
        )

    latest = candles[idx_eval]
    prev = candles[idx_eval - 1] if idx_eval >= 1 else latest

    prev_close = float(prev.get("close") or 0.0)
    pct_change = (last_close - prev_close) / prev_close if prev_close else 0.0

    # Determine readiness (READY vs WATCH) using close-based confirmations only.
    entry_state = "WATCH"
    entry_state_reason = "Early setup; awaiting confirmation"

    if pattern == HybridPattern.TREND_PULLBACK_BOUNCE:
        rsi_val = float(pattern_context.get("rsi_val", rsi_vals[-1]))
        close_above_ema = bool(
            pattern_context.get("close_above_ema_short", last_close > ema_short[-1])
        )
        strong_confirmation = False
        if close_above_ema and (rsi_val > 50 or pattern_context.get("trigger_rsi50")):
            strong_confirmation = True
        if close_above_ema and pattern_context.get("trigger_bullish_vol"):
            strong_confirmation = True
        if pattern_context.get("trigger_hammer_near_ema") and rsi_val > 50:
            strong_confirmation = True

        if strong_confirmation:
            entry_state = "READY"
            entry_state_reason = "Pullback bounce confirmed on close"
        else:
            entry_state_reason = (
                "Pullback bounce forming; wait for EMA reclaim/RSI>50 or volume thrust"
            )

    elif pattern == HybridPattern.SWING_HIGH_BREAKOUT:
        swing_high = float(pattern_context.get("swing_high") or 0.0)
        extended = False
        if swing_high > 0 and not math.isnan(atr_value):
            extended = last_close > swing_high + atr_value
        if extended:
            entry_state = "WATCH"
            entry_state_reason = (
                "Breakout extended (>1 ATR above swing high); consider waiting"
            )
        else:
            entry_state = "READY"
            entry_state_reason = "Breakout close above swing high with volume"

    elif pattern == HybridPattern.RSI_OVERSOLD_REVERSAL:
        rsi_val = float(pattern_context.get("rsi_val", rsi_vals[-1]))
        close_above_ema = bool(
            pattern_context.get("close_above_ema_short", last_close > ema_short[-1])
        )
        if rsi_val >= 45 and close_above_ema:
            entry_state = "READY"
            entry_state_reason = "RSI rebound and close above EMA short"
        else:
            entry_state_reason = (
                "Early reversal; need RSI>=45 and close above EMA short"
            )

    def fmt(value: float, digits: int = 2) -> str:
        if digits == 0:
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"

    price_digits = 2 if currency == "USD" else 0
    # Gap guard prices should carry decimals for precise order reference, regardless of currency.
    gap_price_digits = 2

    risk_guide = "-"
    if not math.isnan(atr_value):
        stop = max(last_close - atr_value, 0)
        target = last_close + atr_value * 2
        risk_guide = f"Stop {fmt(stop, price_digits)} / Target {fmt(target, price_digits)} (~1:2)"

    gap_guard_pct = None
    gap_guard_up_price = None
    gap_guard_down_price = None
    if (
        settings.gap_atr_multiplier > 0
        and not math.isnan(atr_value)
        and atr_value > 0
        and last_close > 0
    ):
        gap_guard_pct = settings.gap_atr_multiplier * atr_value / last_close
        gap_guard_up_price = last_close * (1 + gap_guard_pct)
        gap_guard_down_price = last_close * (1 - gap_guard_pct)

    candidate: dict[str, Any] = {
        "ticker": ticker,
        "name": meta.get("name", ticker),
        "price": fmt(last_close, 0),
        "price_value": last_close,
        "currency": currency,
        "pct_change": f"{pct_change * 100:.1f}%",
        "high": fmt(float(latest.get("high") or 0.0), 0),
        "low": fmt(float(latest.get("low") or 0.0), 0),
        "sma20": fmt(sma_trend[-1], 2),
        "ema10": fmt(ema_short[-1], 2),
        "ema21": fmt(ema_mid[-1], 2),
        "rsi14": fmt(rsi_vals[-1], 1),
        "avg_dollar_volume": fmt(avg_dv, 0),
        "pattern": pattern.value,
        "pattern_reasons": ", ".join(pattern_reasons),
        "entry_state": entry_state,
        "entry_state_reason": entry_state_reason,
        "atr14": fmt(atr_value),
        "gap_guard_pct": f"±{gap_guard_pct * 100:.1f}%"
        if gap_guard_pct is not None
        else "-",
        "gap_guard_up_price": fmt(gap_guard_up_price, gap_price_digits)
        if gap_guard_up_price
        else "-",
        "gap_guard_down_price": fmt(gap_guard_down_price, gap_price_digits)
        if gap_guard_down_price
        else "-",
        "risk_guide": risk_guide,
        # Score is kept for sorting compatibility but fixed for hybrid
        "score_value": 1.0,
        "score": "1.0",
    }

    return HybridEvaluationResult(ticker, candidate)


__all__ = [
    "HybridPattern",
    "HybridEvaluationSettings",
    "HybridEvaluationResult",
    "evaluate_ticker_hybrid",
]
