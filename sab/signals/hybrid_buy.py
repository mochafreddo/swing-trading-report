from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..utils.numeric import to_finite_float as _to_finite_float
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
    reason_kind: str | None = None


def _slugify_reason_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = normalized.strip("_")
    return normalized or "unknown"


def _pattern_label(pattern: HybridPattern) -> str:
    labels = {
        HybridPattern.TREND_PULLBACK_BOUNCE: "눌림 반등",
        HybridPattern.SWING_HIGH_BREAKOUT: "스윙 고점 돌파",
        HybridPattern.RSI_OVERSOLD_REVERSAL: "RSI 과매도 반전",
    }
    return labels.get(pattern, pattern.value)


def _pattern_reason_id_label(reason: str) -> tuple[str, str]:
    if reason == "Close reclaimed EMA short":
        return "trigger_close_reclaimed_ema_short", "EMA 단기선 회복"
    if reason == "Bullish candle with rising volume":
        return "trigger_bullish_candle_rising_volume", "양봉+거래량 증가"
    if reason == "RSI crossed above 50":
        return "trigger_rsi_crossed_above_50", "RSI 50 상향"
    if reason == "Reversal candle near EMA short":
        return "trigger_reversal_near_ema_short", "EMA 단기선 부근 반전"
    if reason.startswith("Close broke above recent swing high with volume >"):
        return (
            "trigger_breakout_above_swing_high_with_volume",
            "전고점 돌파(거래량 확인)",
        )
    if reason.startswith("Confirmed second close above prior breakout swing high"):
        return (
            "trigger_confirmed_second_close_above_swing_high",
            "전고점 돌파 2차 종가 확인",
        )
    if reason == "Reversal off EMA short/mid with volume":
        return (
            "trigger_reversal_off_ema_support_with_volume",
            "EMA 지지 반전(거래량 확인)",
        )
    return f"trigger_{_slugify_reason_token(reason)}", reason


def _to_finite_or_default(value: Any, *, default: float = 0.0) -> float:
    parsed = _to_finite_float(value)
    if parsed is None:
        return default
    return parsed


def _to_volume_and_invalid(value: Any) -> tuple[float, bool]:
    if value is None or value == "":
        return 0.0, False
    parsed = _to_finite_float(value)
    if parsed is None:
        return 0.0, True
    return parsed, False


def _has_non_finite_ohlc(candles: list[dict[str, Any]]) -> bool:
    for candle in candles:
        if (
            _to_finite_float(candle.get("open")) is None
            or _to_finite_float(candle.get("high")) is None
            or _to_finite_float(candle.get("low")) is None
            or _to_finite_float(candle.get("close")) is None
        ):
            return True
    return False


def _avg_dollar_volume(
    candles: list[dict[str, Any]], window: int
) -> tuple[float, bool]:
    if not candles:
        return 0.0, False
    sub = candles[-window:] if len(candles) >= window else candles
    total = 0.0
    count = 0
    has_invalid_volume = False
    for c in sub:
        price = _to_finite_or_default(c.get("close"))
        volume, invalid_volume = _to_volume_and_invalid(c.get("volume"))
        has_invalid_volume = has_invalid_volume or invalid_volume
        total += price * volume
        count += 1
    return (total / count if count else 0.0), has_invalid_volume


def _basic_filters(
    ticker: str,
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
    meta: dict[str, Any],
    eval_index: int,
) -> tuple[bool, str | None, str | None, float, float]:
    idx = max(0, min(eval_index, len(candles) - 1))
    completed_bars = idx + 1
    if completed_bars < settings.min_history_bars:
        return (
            False,
            f"Not enough completed history (<{settings.min_history_bars} bars)",
            "system",
            0.0,
            0.0,
        )

    latest = candles[idx]
    currency = str(meta.get("currency", "KRW")).upper()

    close = _to_finite_float(latest.get("close"))
    if close is None:
        return (
            False,
            "Invalid candle data: non-finite OHLC values",
            "system",
            0.0,
            0.0,
        )
    eff_min_price = settings.min_price
    if currency == "USD" and settings.us_min_price is not None:
        eff_min_price = settings.us_min_price
    if eff_min_price and close < eff_min_price:
        return (
            False,
            f"Price {close:.2f} < MIN_PRICE {eff_min_price:.2f}",
            "signal",
            0.0,
            0.0,
        )

    avg_dv, has_invalid_volume = _avg_dollar_volume(candles[: idx + 1], 20)
    if has_invalid_volume:
        return (
            False,
            "Invalid candle data: non-finite volume values",
            "system",
            close,
            avg_dv,
        )
    eff_min_dv = settings.min_dollar_volume
    if currency == "USD" and settings.us_min_dollar_volume is not None:
        eff_min_dv = settings.us_min_dollar_volume
    if eff_min_dv > 0 and avg_dv < eff_min_dv:
        return (
            False,
            f"Avg dollar volume {avg_dv:,.0f} < {eff_min_dv:,.0f}",
            "signal",
            0.0,
            avg_dv,
        )

    if settings.exclude_etf_etn and is_etf_or_leveraged(ticker, meta):
        return False, "ETF/ETN excluded", "signal", close, avg_dv

    return True, None, None, close, avg_dv


def _volume_stats(
    candles: list[dict[str, Any]], lookback_days: int
) -> tuple[float, float]:
    if not candles:
        return 0.0, 0.0
    vols: list[float] = []
    for candle in candles:
        volume, _ = _to_volume_and_invalid(candle.get("volume"))
        vols.append(volume)
    prev_vol = vols[-2] if len(vols) >= 2 else vols[-1]
    window = vols[-lookback_days:] if len(vols) >= lookback_days else vols
    avg_vol = sum(window) / len(window) if window else 0.0
    return prev_vol, avg_vol


def _avg_volume_excluding_latest(
    candles: list[dict[str, Any]], lookback_days: int
) -> float:
    if len(candles) <= 1 or lookback_days <= 0:
        return 0.0
    historical = candles[:-1]
    vols: list[float] = []
    for candle in historical:
        volume, _ = _to_volume_and_invalid(candle.get("volume"))
        vols.append(volume)
    window = vols[-lookback_days:] if len(vols) >= lookback_days else vols
    return sum(window) / len(window) if window else 0.0


def _resolve_consolidation_swing_high(
    pre_breakout: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
) -> tuple[float | None, list[str], dict[str, Any]]:
    min_bars = settings.breakout_consolidation_min_bars
    max_bars = settings.breakout_consolidation_max_bars
    window = pre_breakout[-max_bars:] if len(pre_breakout) >= max_bars else pre_breakout
    if len(window) < min_bars:
        return None, ["Not enough bars for consolidation"], {}

    highs = [_to_finite_or_default(c.get("high")) for c in window]
    lows = [_to_finite_or_default(c.get("low")) for c in window]
    swing_high = max(highs)
    range_pct = (max(highs) - min(lows)) / swing_high if swing_high else 0.0
    context = {"swing_high": swing_high}
    if range_pct > 0.1:
        return None, ["Consolidation range too wide"], context
    return swing_high, [], context


def _resolve_swing_high_breakout_bar(
    closes: list[float],
    sma_trend: list[float],
    ema_short: list[float],
    ema_mid: list[float],
    rsi_vals: list[float],
    candles: list[dict[str, Any]],
    settings: HybridEvaluationSettings,
) -> tuple[bool, list[str], dict[str, Any]]:
    idx = len(closes) - 1
    close = closes[idx]
    if not (ema_short[idx] > ema_mid[idx] > sma_trend[idx]):
        return False, ["EMAs not aligned for uptrend"], {}
    if rsi_vals[idx] >= 60:
        return False, ["RSI too extended for breakout"], {}

    swing_high, blockers, context = _resolve_consolidation_swing_high(
        candles[:-1], settings
    )
    if swing_high is None:
        return False, blockers, context

    avg_vol = _avg_volume_excluding_latest(candles, settings.volume_lookback_days)
    today_volume, _ = _to_volume_and_invalid(candles[-1].get("volume"))
    if not (close > swing_high and today_volume > avg_vol):
        return False, ["No confirmed breakout over swing high"], context

    return True, [], {"swing_high": swing_high, "avg_vol": avg_vol}


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

    _, avg_vol = _volume_stats(candles, settings.volume_lookback_days)

    # Pullback region: bars immediately before today's signal bar where
    # close stayed at/below EMA short.
    pullback_bars = 0
    for i in range(idx - 1, -1, -1):
        if closes[i] <= ema_short[i]:
            pullback_bars += 1
            if pullback_bars > settings.pullback_max_bars:
                break
        else:
            break

    if pullback_bars == 0:
        return False, ["No pullback bars near EMA short"], None, {}
    if pullback_bars > settings.pullback_max_bars:
        return False, ["Pullback exceeds max bars"], None, {}

    # Very rough check for heavy selling: big red bar with volume >> avg
    heavy_selling = False
    pullback_start = max(0, idx - pullback_bars)
    pullback_slice = candles[pullback_start:idx] if pullback_bars > 0 else []
    for bar in pullback_slice:
        bar_open = _to_finite_or_default(bar.get("open"))
        bar_close = _to_finite_or_default(bar.get("close"))
        bar_volume, _ = _to_volume_and_invalid(bar.get("volume"))
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
        "today_vol": _to_volume_and_invalid(candles[-1].get("volume"))[0],
        "close_above_ema_short": close > ema_short[idx],
    }
    if idx >= 1 and closes[idx - 1] <= ema_short[idx - 1] and close > ema_short[idx]:
        reasons.append("Close reclaimed EMA short")
        triggered = True
        flags["trigger_reclaim"] = True

    today = candles[-1]
    yest = candles[-2] if len(candles) >= 2 else None
    if yest is not None:
        o = _to_finite_or_default(today.get("open"))
        close_today = _to_finite_or_default(today.get("close"))
        v, _ = _to_volume_and_invalid(today.get("volume"))
        prev_v, _ = _to_volume_and_invalid(yest.get("volume"))
        if close_today > o and v > max(prev_v, avg_vol):
            reasons.append("Bullish candle with rising volume")
            triggered = True
            flags["trigger_bullish_vol"] = True

    if idx >= 1 and rsi_vals[idx - 1] <= 50 < rsi_val:
        reasons.append("RSI crossed above 50")
        triggered = True
        flags["trigger_rsi50"] = True

    low = _to_finite_or_default(today.get("low"))
    open_price = _to_finite_or_default(today.get("open"), default=close)
    body = abs(close - open_price)
    lower_shadow = min(close, open_price) - low
    if close > 0 and lower_shadow > body and abs(low - ema_short[idx]) / close < 0.02:
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

    if (
        currency != "USD"
        and settings.kr_breakout_requires_confirmation
        and len(candles) >= 3
    ):
        prior_ok, _, prior_context = _resolve_swing_high_breakout_bar(
            closes[:-1],
            sma_trend[:-1],
            ema_short[:-1],
            ema_mid[:-1],
            rsi_vals[:-1],
            candles[:-1],
            settings,
        )
        prior_swing_high = _to_finite_float(prior_context.get("swing_high"))
        if prior_ok and prior_swing_high is not None and close > prior_swing_high:
            reasons.append("Confirmed second close above prior breakout swing high")
            return (
                True,
                reasons,
                HybridPattern.SWING_HIGH_BREAKOUT,
                {
                    "swing_high": prior_swing_high,
                    "avg_vol": prior_context.get("avg_vol"),
                    "confirmed_breakout": True,
                },
            )

    ok, blockers, context = _resolve_swing_high_breakout_bar(
        closes,
        sma_trend,
        ema_short,
        ema_mid,
        rsi_vals,
        candles,
        settings,
    )
    if not ok:
        return (
            False,
            blockers,
            None,
            context,
        )

    # KR-specific first-close confirmation is handled above; this is a fresh breakout bar.
    reasons.append(
        "Close broke above recent swing high with volume > "
        f"{settings.volume_lookback_days}d avg (excluding breakout bar)"
    )
    return (
        True,
        reasons,
        HybridPattern.SWING_HIGH_BREAKOUT,
        {
            "swing_high": context.get("swing_high"),
            "avg_vol": context.get("avg_vol"),
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
    _, avg_vol = _volume_stats(candles, settings.volume_lookback_days)
    o = _to_finite_or_default(today.get("open"))
    c = _to_finite_or_default(today.get("close"))
    v, _ = _to_volume_and_invalid(today.get("volume"))
    if c <= o or not (avg_vol == 0.0 or v >= avg_vol):
        return False, ["No strong bullish candle with rising volume"], None, {}

    low = _to_finite_or_default(today.get("low"))
    body = abs(c - o)
    lower_shadow = min(c, o) - low
    if lower_shadow <= body:
        return False, ["No clear reversal candle off lows"], None, {}

    if close > 0 and (
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

    idx_eval, _ = choose_eval_index(candles, meta=meta)
    if idx_eval < 0:
        return HybridEvaluationResult(ticker, None, "No candle data", "system")

    candles_eval = candles[: idx_eval + 1]
    if _has_non_finite_ohlc(candles_eval):
        return HybridEvaluationResult(
            ticker,
            None,
            "Invalid candle data: non-finite OHLC values",
            "system",
        )

    ok, reason, reason_kind, last_close, avg_dv = _basic_filters(
        ticker, candles, settings, meta, idx_eval
    )
    if not ok:
        return HybridEvaluationResult(ticker, None, reason, reason_kind or "signal")

    closes = [float(c.get("close") or 0.0) for c in candles_eval]
    highs = [float(c.get("high") or 0.0) for c in candles_eval]
    lows = [float(c.get("low") or 0.0) for c in candles_eval]
    sma_trend = sma(closes, settings.sma_trend_period)
    ema_short = ema(closes, settings.ema_short_period)
    ema_mid = ema(closes, settings.ema_mid_period)
    rsi_vals = rsi(closes, settings.rsi_period)
    atr_vals = atr(highs, lows, closes, 14)
    atr_value = atr_vals[-1] if atr_vals else float("nan")
    latest = candles[idx_eval]
    eval_date_raw = str(latest.get("date") or "").strip()
    eval_date = eval_date_raw or None
    prev = candles[idx_eval - 1] if idx_eval >= 1 else latest
    prev_close = float(prev.get("close") or 0.0)
    gap_pct = 0.0
    if prev_close > 0:
        gap_pct = (float(latest.get("open") or 0.0) - prev_close) / prev_close
    if settings.max_gap_pct > 0 and abs(gap_pct) > settings.max_gap_pct:
        return HybridEvaluationResult(
            ticker,
            None,
            f"Gap {gap_pct * 100:.1f}% exceeds HYBRID_MAX_GAP_PCT {settings.max_gap_pct * 100:.1f}%",
            "signal",
        )

    if settings.use_sma60_filter:
        sma60_vals = sma(closes, settings.sma60_period)
        sma60 = sma60_vals[-1] if sma60_vals else float("nan")
        if math.isnan(sma60) or last_close <= sma60:
            return HybridEvaluationResult(
                ticker,
                None,
                f"Close {last_close:.2f} <= SMA{settings.sma60_period} {sma60:.2f}",
                "signal",
            )

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
            ticker, None, "Did not meet hybrid signal criteria", "signal"
        )
    pct_change = (last_close - prev_close) / prev_close if prev_close else 0.0

    # Determine readiness (READY vs WATCH) using close-based confirmations only.
    entry_state = "WATCH"
    entry_state_reason = "Early setup; awaiting confirmation"
    extended_breakout = False

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
        extended_breakout = extended
        needs_kr_confirmation = (
            currency != "USD"
            and settings.kr_breakout_requires_confirmation
            and swing_high > 0
            and prev_close <= swing_high
        )
        if extended:
            entry_state = "WATCH"
            entry_state_reason = (
                "Breakout extended (>1 ATR above swing high); consider waiting"
            )
        elif needs_kr_confirmation:
            entry_state = "WATCH"
            entry_state_reason = (
                "KR breakout needs one more close confirmation above swing high"
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

    pattern_weights = {
        HybridPattern.TREND_PULLBACK_BOUNCE: 0.30,
        HybridPattern.SWING_HIGH_BREAKOUT: 0.25,
        HybridPattern.RSI_OVERSOLD_REVERSAL: 0.20,
    }
    entry_state_score = 2.0 if entry_state == "READY" else 1.0
    pattern_weight = pattern_weights.get(pattern, 0.0)
    today_volume = float(latest.get("volume") or 0.0)
    avg_volume = float(pattern_context.get("avg_vol") or 0.0)
    has_volume_confirmation = bool(pattern_context.get("trigger_bullish_vol")) or (
        avg_volume > 0 and today_volume >= avg_volume
    )
    volume_confirmation_bonus = 0.10 if has_volume_confirmation else 0.0
    extended_penalty = 0.20 if extended_breakout else 0.0
    score_value = (
        entry_state_score
        + pattern_weight
        + volume_confirmation_bonus
        - extended_penalty
    )
    score_notes = (
        f"entry_state={entry_state_score:.1f},"
        f" pattern={pattern_weight:.2f},"
        f" volume_bonus={volume_confirmation_bonus:.2f},"
        f" extended_penalty={extended_penalty:.2f}"
    )
    reasons: list[dict[str, Any]] = []

    def add_reason(
        *,
        reason_id: str,
        label: str,
        kind: str,
        status: str = "pass",
        points: float | None = None,
        value: float | str | None = None,
        threshold: float | str | None = None,
    ) -> None:
        reason: dict[str, Any] = {
            "id": reason_id,
            "label": label,
            "kind": kind,
            "status": status,
        }
        if points is not None:
            reason["points"] = points
        if value is not None:
            reason["value"] = value
        if threshold is not None:
            reason["threshold"] = threshold
        reasons.append(reason)

    def fmt(value: float, digits: int = 2) -> str:
        if digits == 0:
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"

    price_digits = 2 if currency == "USD" else 0
    # Gap guard prices should carry decimals for precise order reference, regardless of currency.
    gap_price_digits = 2
    sma_trend_key = f"sma{settings.sma_trend_period}"
    ema_short_key = f"ema{settings.ema_short_period}"
    ema_mid_key = f"ema{settings.ema_mid_period}"
    rsi_key = f"rsi{settings.rsi_period}"

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

    entry_trigger_price_value: float | None = None
    entry_trigger_operator: str | None = None
    entry_trigger_label: str | None = None
    if pattern == HybridPattern.SWING_HIGH_BREAKOUT:
        trigger_swing_high = _to_finite_float(pattern_context.get("swing_high"))
        if trigger_swing_high is not None and trigger_swing_high > 0:
            entry_trigger_price_value = trigger_swing_high
            entry_trigger_operator = "gte"
            entry_trigger_label = "swing_high"
    elif pattern == HybridPattern.TREND_PULLBACK_BOUNCE:
        ema_trigger = ema_short[-1]
        if (
            not math.isnan(ema_trigger)
            and ema_trigger > 0
            and pattern_context.get("close_above_ema_short")
        ):
            entry_trigger_price_value = ema_trigger
            entry_trigger_operator = "gte"
            entry_trigger_label = ema_short_key
    elif pattern == HybridPattern.RSI_OVERSOLD_REVERSAL:
        ema_trigger = ema_short[-1]
        if not math.isnan(ema_trigger) and ema_trigger > 0:
            entry_trigger_price_value = ema_trigger
            entry_trigger_operator = "gte"
            entry_trigger_label = ema_short_key

    add_reason(
        reason_id=f"pattern_{pattern.value}",
        label=f"패턴: {_pattern_label(pattern)}",
        kind="pattern",
        points=pattern_weight,
    )
    add_reason(
        reason_id=f"entry_state_{entry_state.lower()}",
        label="READY(확인)" if entry_state == "READY" else "WATCH(대기)",
        kind="state",
        status="pass" if entry_state == "READY" else "warn",
        points=entry_state_score,
        value=entry_state_reason,
    )
    for reason_text in pattern_reasons:
        reason_id, reason_label = _pattern_reason_id_label(reason_text)
        add_reason(
            reason_id=reason_id,
            label=reason_label,
            kind="trigger",
            points=0.0,
            value=reason_text,
        )
    if has_volume_confirmation:
        add_reason(
            reason_id="volume_confirmation",
            label="거래량 확인",
            kind="trigger",
            points=volume_confirmation_bonus,
        )
    if extended_breakout:
        add_reason(
            reason_id="breakout_extended",
            label="돌파 과열 구간",
            kind="risk",
            status="warn",
            points=-extended_penalty,
        )
    if gap_guard_pct is not None:
        add_reason(
            reason_id="gap_guard_atr",
            label="ATR 기반 갭 가드",
            kind="risk",
            points=0.0,
            value=gap_guard_pct,
        )
    if entry_trigger_price_value is not None:
        add_reason(
            reason_id="entry_trigger_guard",
            label="진입 트리거 재확인 기준",
            kind="risk",
            points=0.0,
            value=entry_trigger_price_value,
            threshold=entry_trigger_label,
        )

    sma_trend_value = fmt(sma_trend[-1], 2)
    ema_short_value = fmt(ema_short[-1], 2)
    ema_mid_value = fmt(ema_mid[-1], 2)
    rsi_value = fmt(rsi_vals[-1], 1)

    candidate: dict[str, Any] = {
        "ticker": ticker,
        "name": meta.get("name", ticker),
        "price": fmt(last_close, price_digits),
        "price_value": last_close,
        "close_value": last_close,
        "signal_price_basis": "adjusted",
        "signal_close_adjusted_value": last_close,
        "currency": currency,
        "eval_date": eval_date,
        "pct_change": f"{pct_change * 100:.1f}%",
        "pct_change_value": pct_change,
        "high": fmt(_to_finite_or_default(latest.get("high")), price_digits),
        "low": fmt(_to_finite_or_default(latest.get("low")), price_digits),
        "sma_trend_period": settings.sma_trend_period,
        "ema_short_period": settings.ema_short_period,
        "ema_mid_period": settings.ema_mid_period,
        "rsi_period": settings.rsi_period,
        "sma_trend": sma_trend_value,
        "ema_short": ema_short_value,
        "ema_mid": ema_mid_value,
        "rsi": rsi_value,
        "avg_dollar_volume": fmt(avg_dv, 0),
        "avg_dollar_volume_value": avg_dv,
        "pattern": pattern.value,
        "pattern_reasons": ", ".join(pattern_reasons),
        "entry_state": entry_state,
        "entry_state_reason": entry_state_reason,
        "entry_trigger_price_value": entry_trigger_price_value,
        "entry_trigger_operator": entry_trigger_operator,
        "entry_trigger_label": entry_trigger_label,
        "atr14": fmt(atr_value),
        "atr14_value": None if math.isnan(atr_value) else atr_value,
        "gap_guard_pct": f"±{gap_guard_pct * 100:.1f}%"
        if gap_guard_pct is not None
        else "-",
        "gap_guard_pct_value": gap_guard_pct,
        "gap_guard_up_price": fmt(gap_guard_up_price, gap_price_digits)
        if gap_guard_up_price
        else "-",
        "gap_guard_up_price_value": gap_guard_up_price,
        "gap_guard_down_price": fmt(gap_guard_down_price, gap_price_digits)
        if gap_guard_down_price
        else "-",
        "gap_guard_down_price_value": gap_guard_down_price,
        "risk_guide": risk_guide,
        "score_value": score_value,
        "score": f"{score_value:.2f}",
        "score_notes": score_notes,
        "reasons": reasons,
    }
    candidate[sma_trend_key] = sma_trend_value
    candidate[ema_short_key] = ema_short_value
    candidate[ema_mid_key] = ema_mid_value
    candidate[rsi_key] = rsi_value

    return HybridEvaluationResult(ticker, candidate)


__all__ = [
    "HybridEvaluationResult",
    "HybridEvaluationSettings",
    "HybridPattern",
    "evaluate_ticker_hybrid",
]
