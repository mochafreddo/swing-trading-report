from __future__ import annotations

from collections.abc import Iterable
from math import isnan


def ema(values: Iterable[float], period: int) -> list[float]:
    vals = list(values)
    if period <= 0 or not vals:
        return [float("nan")] * len(vals)
    k = 2 / (period + 1)
    out: list[float] = []
    ema_prev = None
    for v in vals:
        if v is None:
            v = float("nan")
        if ema_prev is None:
            ema_prev = v
        else:
            ema_prev = (v * k) + (ema_prev * (1 - k))
        out.append(ema_prev)
    return out


def rsi(closes: Iterable[float], period: int = 14) -> list[float]:
    c = list(closes)
    if period <= 0 or len(c) < 2:
        return [float("nan")] * len(c)
    gains: list[float] = [0.0]
    losses: list[float] = [0.0]
    for i in range(1, len(c)):
        ch = c[i] - c[i - 1]
        gains.append(max(0.0, ch))
        losses.append(max(0.0, -ch))
    avg_gain = sum(gains[1 : period + 1]) / period if len(gains) > period else 0.0
    avg_loss = sum(losses[1 : period + 1]) / period if len(losses) > period else 0.0
    rsis: list[float] = [float("nan")] * len(c)
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
) -> list[float]:
    H, L, C = list(highs), list(lows), list(closes)
    n = min(len(H), len(L), len(C))
    if period <= 0 or n == 0:
        return [float("nan")] * n
    tr: list[float] = []
    prev_close = C[0]
    for i in range(n):
        high = H[i]
        low = L[i]
        c_prev = prev_close
        tr.append(max(high - low, abs(high - c_prev), abs(low - c_prev)))
        prev_close = C[i]
    # Wilder's smoothing
    out: list[float] = [float("nan")] * n
    if n > period:
        first = sum(tr[1 : period + 1]) / period
        out[period] = first
        for i in range(period + 1, n):
            out[i] = ((out[i - 1] * (period - 1)) + tr[i]) / period
    return out


def sma(values: Iterable[float], period: int) -> list[float]:
    vals = list(values)
    n = len(vals)
    if period <= 0 or n == 0:
        return [float("nan")] * n
    out: list[float] = [float("nan")] * n
    window_sum = 0.0
    for i, v in enumerate(vals):
        if v is None or (isinstance(v, float) and isnan(v)):
            window_sum += 0.0
        else:
            window_sum += v
        if i >= period:
            prev = vals[i - period]
            if prev is None or (isinstance(prev, float) and isnan(prev)):
                prev = 0.0
            window_sum -= prev
        if i >= period - 1:
            out[i] = window_sum / period
    return out
