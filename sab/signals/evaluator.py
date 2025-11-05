from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from .indicators import atr, ema, rsi


@dataclass
class EvaluationResult:
    ticker: str
    candidate: Optional[Dict[str, str]]
    reason: Optional[str] = None


def _clean(values: List[float]) -> List[float]:
    return [v for v in values if not math.isnan(v)]


def evaluate_ticker(ticker: str, candles: List[Dict[str, float]]) -> EvaluationResult:
    if len(candles) < 60:
        return EvaluationResult(ticker, None, "Not enough history (<60 bars)")

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    if not (_clean(closes) and _clean(highs) and _clean(lows)):
        return EvaluationResult(ticker, None, "Insufficient price data")

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)
    atr14 = atr(highs, lows, closes, 14)

    latest = candles[-1]
    previous = candles[-2]

    ema_cross_up = ema20[-1] > ema50[-1] and ema20[-2] <= ema50[-2]
    rsi_rebound = rsi14[-1] > 30 and rsi14[-2] <= 30
    rsi_not_overbought = rsi14[-1] < 70
    gap_pct = 0.0
    if previous["close"]:
        gap_pct = (latest["open"] - previous["close"]) / previous["close"]
    gap_ok = abs(gap_pct) <= 0.03

    atr_value = atr14[-1]
    if math.isnan(atr_value) or atr_value <= 0:
        atr_value = float("nan")

    if not (ema_cross_up and rsi_rebound and rsi_not_overbought and gap_ok):
        return EvaluationResult(ticker, None, "Did not meet signal criteria")

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

    score = rsi14[-1]

    candidate = {
        "ticker": ticker,
        "name": ticker,
        "price": fmt(latest["close"], 0),
        "ema20": fmt(ema20[-1]),
        "ema50": fmt(ema50[-1]),
        "rsi14": fmt(rsi14[-1]),
        "rsi14_value": rsi14[-1],
        "atr14": fmt(atr_value),
        "gap": f"{gap_pct*100:.1f}%",
        "pct_change": f"{pct_change*100:.1f}%",
        "high": fmt(latest["high"], 0),
        "low": fmt(latest["low"], 0),
        "risk_guide": risk_guide,
        "score": score,
    }

    return EvaluationResult(ticker, candidate)
