from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..utils.numeric import to_finite_float as _to_finite_float
from .etf_filters import is_etf_or_leveraged
from .eval_index import choose_eval_index
from .indicators import atr, ema, rsi, sma


@dataclass
class EvaluationResult:
    ticker: str
    candidate: dict[str, Any] | None
    reason: str | None = None
    reason_kind: str | None = None


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
    rs_benchmark_return: float | None = None
    min_price: float = 0.0
    us_min_price: float | None = None


@dataclass(frozen=True)
class _OhlcSeries:
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]


@dataclass(frozen=True)
class _GapFilterResult:
    gap_pct: float
    threshold: float | None
    guard_pct: float | None
    guard_up_price: float | None
    guard_down_price: float | None


@dataclass(frozen=True)
class _VolumeFilterResult:
    avg_dollar_volume: float
    effective_min_dollar_volume: float


@dataclass(frozen=True)
class _RelativeStrengthResult:
    rs_return: float | None
    rs_diff: float | None
    benchmark_return: float | None
    benchmark_ticker: str | None


@dataclass(frozen=True)
class _FilterIssue:
    reason: str
    reason_kind: str


def _currency_code(meta: dict[str, Any]) -> str:
    return str(meta.get("currency", "KRW")).upper()


def _market_specific_setting(
    meta: dict[str, Any],
    *,
    default: float,
    us_override: float | None,
) -> float:
    if _currency_code(meta) == "USD" and us_override is not None:
        return us_override
    return default


def _format_metric(value: float | None, digits: int = 2) -> str:
    if value is None or math.isnan(value):
        return "-"
    if digits == 0:
        return f"{value:,.0f}"
    return f"{value:,.{digits}f}"


def _extract_ohlc_series(candles: list[dict[str, float]]) -> _OhlcSeries | None:
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for candle in candles:
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
        highs.append(high_price)
        lows.append(low_price)
        closes.append(close_price)
    return _OhlcSeries(opens=opens, highs=highs, lows=lows, closes=closes)


def _evaluate_gap_filter(
    *,
    settings: EvaluationSettings,
    previous_close: float,
    latest_open: float,
    latest_close: float,
    atr_value: float,
    atr_pre_signal_value: float,
) -> tuple[_GapFilterResult, _FilterIssue | None]:
    gap_pct = 0.0
    if previous_close:
        gap_pct = (latest_open - previous_close) / previous_close

    gap_threshold: float | None = None
    if settings.gap_atr_multiplier > 0:
        if (
            math.isnan(atr_pre_signal_value)
            or atr_pre_signal_value <= 0
            or previous_close <= 0
        ):
            return (
                _GapFilterResult(gap_pct, None, None, None, None),
                _FilterIssue(
                    "Gap filter unavailable: ATR/price inputs invalid",
                    "system",
                ),
            )
        gap_threshold = (
            settings.gap_atr_multiplier * atr_pre_signal_value / previous_close
        )
        if abs(gap_pct) > gap_threshold:
            return (
                _GapFilterResult(gap_pct, gap_threshold, None, None, None),
                _FilterIssue(
                    f"Gap {gap_pct * 100:.1f}% exceeds threshold",
                    "signal",
                ),
            )

    guard_pct = None
    guard_up_price = None
    guard_down_price = None
    if (
        settings.gap_atr_multiplier > 0
        and not math.isnan(atr_value)
        and atr_value > 0
        and latest_close > 0
    ):
        guard_pct = settings.gap_atr_multiplier * atr_value / latest_close
        guard_up_price = latest_close * (1.0 + guard_pct)
        guard_down_price = latest_close * (1.0 - guard_pct)
    return (
        _GapFilterResult(
            gap_pct=gap_pct,
            threshold=gap_threshold,
            guard_pct=guard_pct,
            guard_up_price=guard_up_price,
            guard_down_price=guard_down_price,
        ),
        None,
    )


def _average_dollar_volume_or_issue(
    *,
    candles_eval: list[dict[str, float]],
    closes: list[float],
    settings: EvaluationSettings,
    meta: dict[str, Any],
) -> tuple[_VolumeFilterResult | None, _FilterIssue | None]:
    avg_dollar_volume = 0.0
    window_start = max(0, len(candles_eval) - 20)
    if len(candles_eval) > 0:
        total = 0.0
        count = 0
        for idx in range(window_start, len(candles_eval)):
            volume = _to_finite_float(candles_eval[idx].get("volume"))
            if volume is None:
                return (
                    None,
                    _FilterIssue(
                        "Invalid candle data: non-finite volume values",
                        "system",
                    ),
                )
            total += closes[idx] * volume
            count += 1
        if count:
            avg_dollar_volume = total / count

    effective_min_dv = _market_specific_setting(
        meta,
        default=settings.min_dollar_volume,
        us_override=settings.us_min_dollar_volume,
    )
    if effective_min_dv > 0 and avg_dollar_volume < effective_min_dv:
        return (
            None,
            _FilterIssue(
                f"Avg dollar volume {avg_dollar_volume:,.0f} < {effective_min_dv:,.0f}",
                "signal",
            ),
        )
    return (
        _VolumeFilterResult(
            avg_dollar_volume=avg_dollar_volume,
            effective_min_dollar_volume=effective_min_dv,
        ),
        None,
    )


def _relative_strength(
    *,
    settings: EvaluationSettings,
    meta: dict[str, Any],
    closes: list[float],
    latest_close: float,
) -> _RelativeStrengthResult:
    rs_return = None
    rs_diff = None
    benchmark_return = _to_finite_float(meta.get("rs_benchmark_return"))
    if benchmark_return is None:
        benchmark_return = settings.rs_benchmark_return
    benchmark_ticker = str(meta.get("rs_benchmark_ticker") or "").strip() or None
    if settings.rs_lookback_days > 0 and len(closes) > settings.rs_lookback_days:
        base_close = closes[-settings.rs_lookback_days - 1]
        if base_close:
            rs_return = (latest_close - base_close) / base_close
            if benchmark_return is not None:
                rs_diff = rs_return - benchmark_return
    return _RelativeStrengthResult(
        rs_return=rs_return,
        rs_diff=rs_diff,
        benchmark_return=benchmark_return,
        benchmark_ticker=benchmark_ticker,
    )


def _add_candidate_reason(
    reasons: list[dict[str, Any]],
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


def _build_ema_cross_candidate(
    *,
    ticker: str,
    meta: dict[str, Any],
    currency: Any,
    settings: EvaluationSettings,
    eval_date: str | None,
    latest_close: float,
    previous_close: float,
    latest_high: float,
    latest_low: float,
    ema20: list[float],
    ema50: list[float],
    rsi14: list[float],
    atr_value: float,
    sma200_value: float,
    trend_pass: bool,
    slope_pass: bool,
    gap: _GapFilterResult,
    volume: _VolumeFilterResult,
    relative_strength: _RelativeStrengthResult,
) -> dict[str, Any]:
    pct_change = 0.0
    if previous_close:
        pct_change = (latest_close - previous_close) / previous_close

    risk_guide = "-"
    if not math.isnan(atr_value):
        stop = max(latest_close - atr_value, 0)
        target = latest_close + atr_value * 2
        risk_guide = (
            f"Stop {_format_metric(stop, 0)} / "
            f"Target {_format_metric(target, 0)} (~1:2)"
        )

    score = 0.0
    breakdown: list[str] = []
    reasons: list[dict[str, Any]] = []

    score += 1
    breakdown.append("ema_cross")
    _add_candidate_reason(
        reasons,
        reason_id="ema_cross",
        label="EMA20/50 골든크로스",
        kind="signal",
        points=1,
    )

    score += 1
    breakdown.append("rsi")
    _add_candidate_reason(
        reasons,
        reason_id="rsi_rebound",
        label="RSI 반등",
        kind="signal",
        points=1,
        value=rsi14[-1],
        threshold=30.0,
    )

    if settings.use_sma200_filter and trend_pass:
        score += 1
        breakdown.append("sma200")
        _add_candidate_reason(
            reasons,
            reason_id="sma200_trend_filter",
            label="SMA200 상단 추세 필터",
            kind="filter",
            points=1,
            value=latest_close,
            threshold=sma200_value,
        )

    if settings.require_slope_up and slope_pass:
        score += 1
        breakdown.append("slope")
        _add_candidate_reason(
            reasons,
            reason_id="ema_slope_up",
            label="EMA 기울기 상승",
            kind="filter",
            points=1,
        )

    if settings.gap_atr_multiplier > 0:
        score += 1
        breakdown.append("gap")
        _add_candidate_reason(
            reasons,
            reason_id="gap_within_limit",
            label="갭 허용 범위",
            kind="filter",
            points=1,
            value=gap.gap_pct,
            threshold=gap.threshold,
        )

    if volume.avg_dollar_volume > 0:
        score += 1
        breakdown.append("liquidity")
        _add_candidate_reason(
            reasons,
            reason_id="liquidity",
            label="유동성 확보",
            kind="filter",
            points=1,
            value=volume.avg_dollar_volume,
            threshold=(
                volume.effective_min_dollar_volume
                if volume.effective_min_dollar_volume > 0
                else 0.0
            ),
        )

    if relative_strength.rs_diff is not None:
        if relative_strength.rs_diff >= 0:
            score += 1
            breakdown.append("rs")
            _add_candidate_reason(
                reasons,
                reason_id="rs_above_benchmark",
                label="상대강도 양호",
                kind="filter",
                points=1,
                value=relative_strength.rs_diff,
                threshold=0.0,
            )
        else:
            breakdown.append("rs_below")
            _add_candidate_reason(
                reasons,
                reason_id="rs_below_benchmark",
                label="상대강도 약함",
                kind="filter",
                status="warn",
                points=0,
                value=relative_strength.rs_diff,
                threshold=0.0,
            )

    return {
        "ticker": ticker,
        "name": meta.get("name", ticker),
        "price": _format_metric(latest_close, 0),
        "ema20": _format_metric(ema20[-1]),
        "ema50": _format_metric(ema50[-1]),
        "rsi14": _format_metric(rsi14[-1]),
        "atr14": _format_metric(atr_value),
        "atr14_value": None if math.isnan(atr_value) else atr_value,
        "gap": f"{gap.gap_pct * 100:.1f}%",
        "gap_threshold": (
            f"{gap.threshold * 100:.1f}%" if gap.threshold is not None else "-"
        ),
        "gap_guard_pct_value": gap.guard_pct,
        "gap_guard_up_price_value": gap.guard_up_price,
        "gap_guard_down_price_value": gap.guard_down_price,
        "pct_change": f"{pct_change * 100:.1f}%",
        "high": _format_metric(latest_high, 0),
        "low": _format_metric(latest_low, 0),
        "risk_guide": risk_guide,
        "sma200": _format_metric(sma200_value, 0),
        "avg_dollar_volume": _format_metric(volume.avg_dollar_volume, 0),
        "avg_dollar_volume_value": volume.avg_dollar_volume,
        "rs_return": (
            f"{relative_strength.rs_return * 100:.1f}%"
            if relative_strength.rs_return is not None
            else "-"
        ),
        "rs_return_value": relative_strength.rs_return,
        "rs_diff": (
            f"{relative_strength.rs_diff * 100:.1f}%"
            if relative_strength.rs_diff is not None
            else "-"
        ),
        "rs_diff_value": relative_strength.rs_diff,
        "rs_benchmark": (
            f"{relative_strength.benchmark_return * 100:.1f}%"
            if relative_strength.benchmark_return is not None
            else "-"
        ),
        "rs_benchmark_value": relative_strength.benchmark_return,
        "rs_benchmark_ticker": relative_strength.benchmark_ticker,
        "score": f"{score:.1f}",
        "score_value": score,
        "score_notes": ", ".join(breakdown),
        "reasons": reasons,
        "trend_pass": "Yes" if trend_pass else "No",
        "slope_pass": "Yes" if slope_pass else "No",
        "currency": currency,
        "eval_date": eval_date,
        "price_value": latest_close,
        "close_value": latest_close,
        "signal_price_basis": "adjusted",
        "signal_close_adjusted_value": latest_close,
        "pct_change_value": pct_change,
    }


def evaluate_ticker(
    ticker: str,
    candles: list[dict[str, float]],
    settings: EvaluationSettings,
    meta: dict[str, Any] | None = None,
) -> EvaluationResult:
    meta = meta or {}
    currency = meta.get("currency", "KRW")

    idx_eval, _ = choose_eval_index(candles, meta=meta)
    if idx_eval < 1:
        return EvaluationResult(
            ticker, None, "Not enough completed candles", reason_kind="system"
        )

    candles_eval = candles[: idx_eval + 1]
    if len(candles_eval) < settings.min_history_bars:
        return EvaluationResult(
            ticker,
            None,
            f"Not enough completed history (<{settings.min_history_bars} bars)",
            reason_kind="system",
        )

    ohlc = _extract_ohlc_series(candles_eval)
    if ohlc is None:
        return EvaluationResult(
            ticker,
            None,
            "Invalid candle data: non-finite OHLC values",
            reason_kind="system",
        )

    ema20 = ema(ohlc.closes, 20)
    ema50 = ema(ohlc.closes, 50)
    rsi14 = rsi(ohlc.closes, 14)
    atr14 = atr(ohlc.highs, ohlc.lows, ohlc.closes, 14)
    sma200 = sma(ohlc.closes, 200)
    latest_close = ohlc.closes[-1]
    previous_close = ohlc.closes[-2]
    latest_open = ohlc.opens[-1]
    latest_high = ohlc.highs[-1]
    latest_low = ohlc.lows[-1]

    effective_min_price = _market_specific_setting(
        meta,
        default=settings.min_price,
        us_override=settings.us_min_price,
    )
    if effective_min_price and latest_close < effective_min_price:
        return EvaluationResult(
            ticker,
            None,
            f"Price {latest_close:.0f} < MIN_PRICE {effective_min_price:.0f}",
            reason_kind="signal",
        )

    ema_cross_up = ema20[-1] > ema50[-1] and ema20[-2] <= ema50[-2]
    rsi_rebound = rsi14[-1] > 30 and rsi14[-2] <= 30
    rsi_not_overbought = rsi14[-1] < 70
    atr_value = atr14[-1]
    atr_pre_signal_value = atr14[-2]
    sma200_value = sma200[-1]
    eval_date_raw = str(candles_eval[-1].get("date") or "").strip()
    eval_date = eval_date_raw or None

    if not ema_cross_up:
        return EvaluationResult(
            ticker, None, "EMA(20/50) cross not satisfied", reason_kind="signal"
        )
    if not (rsi_rebound and rsi_not_overbought):
        return EvaluationResult(
            ticker, None, "RSI signal not satisfied", reason_kind="signal"
        )

    trend_pass = True
    if settings.use_sma200_filter:
        trend_pass = (
            not math.isnan(sma200_value)
            and latest_close > sma200_value
            and ema20[-1] > sma200_value
            and ema50[-1] > sma200_value
        )
        if not trend_pass:
            return EvaluationResult(
                ticker, None, "Below SMA200 filter", reason_kind="signal"
            )

    slope_pass = True
    if settings.require_slope_up:
        slope_pass = ema20[-1] > ema20[-2] and ema50[-1] > ema50[-2]
        if not slope_pass:
            return EvaluationResult(
                ticker, None, "EMA slope not rising", reason_kind="signal"
            )

    gap, issue = _evaluate_gap_filter(
        settings=settings,
        previous_close=previous_close,
        latest_open=latest_open,
        latest_close=latest_close,
        atr_value=atr_value,
        atr_pre_signal_value=atr_pre_signal_value,
    )
    if issue is not None:
        return EvaluationResult(
            ticker, None, issue.reason, reason_kind=issue.reason_kind
        )

    volume, issue = _average_dollar_volume_or_issue(
        candles_eval=candles_eval,
        closes=ohlc.closes,
        settings=settings,
        meta=meta,
    )
    if issue is not None:
        return EvaluationResult(
            ticker, None, issue.reason, reason_kind=issue.reason_kind
        )
    assert volume is not None

    if settings.exclude_etf_etn and is_etf_or_leveraged(ticker, meta):
        return EvaluationResult(ticker, None, "ETF/ETN excluded", reason_kind="signal")

    relative_strength = _relative_strength(
        settings=settings,
        meta=meta,
        closes=ohlc.closes,
        latest_close=latest_close,
    )

    candidate = _build_ema_cross_candidate(
        ticker=ticker,
        meta=meta,
        currency=currency,
        settings=settings,
        eval_date=eval_date,
        latest_close=latest_close,
        previous_close=previous_close,
        latest_high=latest_high,
        latest_low=latest_low,
        ema20=ema20,
        ema50=ema50,
        rsi14=rsi14,
        atr_value=atr_value,
        sma200_value=sma200_value,
        trend_pass=trend_pass,
        slope_pass=slope_pass,
        gap=gap,
        volume=volume,
        relative_strength=relative_strength,
    )
    return EvaluationResult(ticker, candidate)
