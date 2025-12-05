from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .etf_filters import is_etf_or_leveraged
from .eval_index import choose_eval_index
from .indicators import atr, ema, rsi, sma


@dataclass
class EvaluationResult:
    ticker: str
    candidate: dict[str, Any] | None
    reason: str | None = None


@dataclass
class EvaluationSettings:
    use_sma200_filter: bool = False
    gap_atr_multiplier: float = 1.0
    min_dollar_volume: float = 0.0
    us_min_dollar_volume: float | None = None
    min_history_bars: int = 120
    exclude_etf_etn: bool = False
    require_slope_up: bool = False
    rs_lookback_days: int = 20
    rs_benchmark_return: float = 0.0
    min_price: float = 0.0
    us_min_price: float | None = None


def _clean(values: list[float]) -> list[float]:
    return [v for v in values if not math.isnan(v)]


def evaluate_ticker(
    ticker: str,
    candles: list[dict[str, float]],
    settings: EvaluationSettings,
    meta: dict[str, Any] | None = None,
) -> EvaluationResult:
    meta = meta or {}
    currency = meta.get("currency", "KRW")

    if len(candles) < settings.min_history_bars:
        return EvaluationResult(
            ticker,
            None,
            f"Not enough history (<{settings.min_history_bars} bars)",
        )

    provider = str(meta.get("data_source") or meta.get("provider") or "kis").lower()
    idx_eval, _ = choose_eval_index(candles, meta=meta, provider=provider)
    if idx_eval < 1:
        return EvaluationResult(ticker, None, "Not enough completed candles")

    candles_eval = candles[: idx_eval + 1]

    closes = [c["close"] for c in candles_eval]
    highs = [c["high"] for c in candles_eval]
    lows = [c["low"] for c in candles_eval]

    if not (_clean(closes) and _clean(highs) and _clean(lows)):
        return EvaluationResult(ticker, None, "Insufficient price data")

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)
    atr14 = atr(highs, lows, closes, 14)
    sma200 = sma(closes, 200)

    latest = candles[idx_eval]
    previous = candles[idx_eval - 1]

    # Market-aware price floor
    eff_min_price = settings.min_price
    if meta.get("currency", "KRW").upper() == "USD" and settings.us_min_price:
        eff_min_price = settings.us_min_price

    if eff_min_price and latest["close"] < eff_min_price:
        return EvaluationResult(
            ticker,
            None,
            f"Price {latest['close']:.0f} < MIN_PRICE {eff_min_price:.0f}",
        )

    ema_cross_up = ema20[-1] > ema50[-1] and ema20[-2] <= ema50[-2]
    rsi_rebound = rsi14[-1] > 30 and rsi14[-2] <= 30
    rsi_not_overbought = rsi14[-1] < 70
    gap_pct = 0.0
    if previous["close"]:
        gap_pct = (latest["open"] - previous["close"]) / previous["close"]

    atr_value = atr14[-1]

    if not ema_cross_up:
        return EvaluationResult(ticker, None, "EMA(20/50) cross not satisfied")
    if not (rsi_rebound and rsi_not_overbought):
        return EvaluationResult(ticker, None, "RSI signal not satisfied")

    # SMA200 filter
    trend_pass = True
    sma200_value = sma200[-1]
    if settings.use_sma200_filter:
        trend_pass = (
            not math.isnan(sma200_value)
            and latest["close"] > sma200_value
            and ema20[-1] > sma200_value
            and ema50[-1] > sma200_value
        )
        if not trend_pass:
            return EvaluationResult(ticker, None, "Below SMA200 filter")

    # EMA slope requirement
    slope_pass = True
    if settings.require_slope_up:
        slope_pass = ema20[-1] > ema20[-2] and ema50[-1] > ema50[-2]
        if not slope_pass:
            return EvaluationResult(ticker, None, "EMA slope not rising")

    # Gap threshold via ATR multiplier
    gap_threshold = 0.03
    if (
        settings.gap_atr_multiplier > 0
        and not math.isnan(atr_value)
        and atr_value > 0
        and previous["close"] > 0
    ):
        gap_threshold = settings.gap_atr_multiplier * atr_value / previous["close"]
    gap_ok = abs(gap_pct) <= gap_threshold
    if not gap_ok:
        return EvaluationResult(
            ticker,
            None,
            f"Gap {gap_pct * 100:.1f}% exceeds threshold",
        )

    # Liquidity: average dollar volume last 20 bars
    avg_dollar_volume = 0.0
    window = candles_eval[-20:] if len(candles_eval) >= 20 else candles_eval
    if window:
        total = 0.0
        count = 0
        for c in window:
            price = c.get("close") or 0.0
            volume = c.get("volume") or 0.0
            total += price * volume
            count += 1
        if count:
            avg_dollar_volume = total / count
    # Market-aware liquidity floor (USD for US, KRW for KR)
    eff_min_dv = settings.min_dollar_volume
    if meta.get("currency", "KRW").upper() == "USD" and settings.us_min_dollar_volume:
        eff_min_dv = settings.us_min_dollar_volume
    if eff_min_dv > 0 and avg_dollar_volume < eff_min_dv:
        return EvaluationResult(
            ticker,
            None,
            f"Avg dollar volume {avg_dollar_volume:,.0f} < {eff_min_dv:,.0f}",
        )

    # ETF/ETN exclusion heuristic (including leveraged/inverse products)
    if settings.exclude_etf_etn and is_etf_or_leveraged(ticker, meta):
        return EvaluationResult(ticker, None, "ETF/ETN excluded")

    rs_return = None
    rs_diff = None
    if settings.rs_lookback_days > 0 and len(closes) > settings.rs_lookback_days:
        base_close = closes[-settings.rs_lookback_days - 1]
        if base_close:
            rs_return = (latest["close"] - base_close) / base_close
            rs_diff = rs_return - settings.rs_benchmark_return

    pct_change = 0.0
    if previous["close"]:
        pct_change = (latest["close"] - previous["close"]) / previous["close"]

    def fmt(value: float, digits: int = 2) -> str:
        if value is None or math.isnan(value):
            return "-"
        if digits == 0:
            return f"{value:,.0f}"
        return f"{value:,.{digits}f}"

    risk_guide = "-"
    if not math.isnan(atr_value):
        stop = max(latest["close"] - atr_value, 0)
        target = latest["close"] + atr_value * 2
        risk_guide = f"Stop {fmt(stop, 0)} / Target {fmt(target, 0)} (~1:2)"

    score = 0.0
    breakdown: list[str] = []

    score += 1
    breakdown.append("ema_cross")

    score += 1
    breakdown.append("rsi")

    if trend_pass:
        score += 1
        breakdown.append("sma200")

    if slope_pass:
        score += 1
        breakdown.append("slope")

    if gap_ok:
        score += 1
        breakdown.append("gap")

    if avg_dollar_volume > 0:
        score += 1
        breakdown.append("liquidity")

    if rs_return is not None:
        if rs_diff is None or rs_diff >= 0:
            score += 1
            breakdown.append("rs")
        else:
            breakdown.append("rs_below")

    score_display = f"{score:.1f}"
    score_notes = ", ".join(breakdown)

    candidate = {
        "ticker": ticker,
        "name": meta.get("name", ticker),
        "price": fmt(latest["close"], 0),
        "ema20": fmt(ema20[-1]),
        "ema50": fmt(ema50[-1]),
        "rsi14": fmt(rsi14[-1]),
        "atr14": fmt(atr_value),
        "gap": f"{gap_pct * 100:.1f}%",
        "gap_threshold": f"{gap_threshold * 100:.1f}%",
        "pct_change": f"{pct_change * 100:.1f}%",
        "high": fmt(latest["high"], 0),
        "low": fmt(latest["low"], 0),
        "risk_guide": risk_guide,
        "sma200": fmt(sma200_value if not math.isnan(sma200_value) else float("nan"), 0),
        "avg_dollar_volume": fmt(avg_dollar_volume, 0),
        "rs_return": f"{rs_return * 100:.1f}%" if rs_return is not None else "-",
        "rs_diff": f"{rs_diff * 100:.1f}%" if rs_diff is not None else "-",
        "rs_benchmark": f"{settings.rs_benchmark_return * 100:.1f}%",
        "score": score_display,
        "score_value": score,
        "score_notes": score_notes,
        "trend_pass": "Yes" if trend_pass else "No",
        "slope_pass": "Yes" if slope_pass else "No",
        "currency": currency,
        "price_value": latest["close"],
    }

    return EvaluationResult(ticker, candidate)
