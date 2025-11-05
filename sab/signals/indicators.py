from __future__ import annotations

from math import isnan
from typing import Iterable, List, Tuple


def ema(values: Iterable[float], period: int) -> List[float]:
    vals = list(values)
    if period <= 0 or not vals:
        return [float("nan")] * len(vals)
    k = 2 / (period + 1)
    out: List[float] = []
    ema_prev = None
    for i, v in enumerate(vals):
        if v is None:
            v = float("nan")
        if ema_prev is None:
            ema_prev = v
        else:
            ema_prev = (v * k) + (ema_prev * (1 - k))
        out.append(ema_prev)
    return out


def rsi(closes: Iterable[float], period: int = 14) -> List[float]:
    c = list(closes)
    if period <= 0 or len(c) < 2:
        return [float("nan")] * len(c)
    gains: List[float] = [0.0]
    losses: List[float] = [0.0]
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]
        gains.append(max(0.0, ch))
        losses.append(max(0.0, -ch))
    avg_gain = sum(gains[1 : period + 1]) / period if len(gains) > period else 0.0
    avg_loss = sum(losses[1 : period + 1]) / period if len(losses) > period else 0.0
    rsis: List[float] = [float("nan")] * len(c)
    if period < len(c):
        rsis[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
    for i in range(period + 1, len(c)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        rsi_val = 100.0 if avg_loss == 0 else 100 - (100 / (1 + (avg_gain / avg_loss)))
        rsis[i] = rsi_val
    return rsis


def atr(
    highs: Iterable[float], lows: Iterable[float], closes: Iterable[float], period: int = 14
) -> List[float]:
    H, L, C = list(highs), list(lows), list(closes)
    n = min(len(H), len(L), len(C))
    if period <= 0 or n == 0:
        return [float("nan")] * n
    tr: List[float] = []
    prev_close = C[0]
    for i in range(n):
        h = H[i]
        l = L[i]
        c_prev = prev_close
        tr.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
        prev_close = C[i]
    # Wilder's smoothing
    out: List[float] = [float("nan")] * n
    if n > period:
        first = sum(tr[1 : period + 1]) / period
        out[period] = first
        for i in range(period + 1, n):
            out[i] = ((out[i - 1] * (period - 1)) + tr[i]) / period
    return out

