from __future__ import annotations

import datetime as dt
from typing import Any

from .data.holiday_cache import HolidayEntry
from .scan_types import _ScanRuntime, _to_float

_SYSTEM_REASON_PREFIXES = (
    "Not enough completed candles",
    "Not enough completed history",
    "Insufficient price data",
    "No candle data",
)


def _is_system_issue_reason(reason: str) -> bool:
    return reason.startswith(_SYSTEM_REASON_PREFIXES)


def _is_system_result(result: Any) -> bool:
    reason_kind = getattr(result, "reason_kind", None)
    if reason_kind == "system":
        return True
    if reason_kind == "signal":
        return False
    reason = getattr(result, "reason", None)
    if not isinstance(reason, str):
        return False
    return _is_system_issue_reason(reason)


def _apply_currency_display(
    candidate: dict[str, Any],
    fx_rate: float | None,
    fx_meta_note: str | None,
) -> None:
    currency = candidate.get("currency", "KRW")
    price_value = _to_float(candidate.get("price_value"))
    if price_value is None:
        candidate["price"] = candidate.get("price", "-")
        return

    if currency == "USD":
        display = f"${price_value:,.2f}"
        if fx_rate:
            converted = price_value * fx_rate
            candidate["price_converted"] = converted
            note = f"1 USD ≈ ₩{fx_rate:,.0f}"
            if fx_meta_note:
                note += f" ({fx_meta_note})"
            candidate["fx_note"] = note
            display += f" (₩{converted:,.0f})"
        candidate["price"] = display
    else:
        candidate["price"] = f"₩{price_value:,.0f}"


def _evaluate_candidates(
    runtime: _ScanRuntime,
    *,
    EvaluationSettingsCls: Any,
    HybridEvaluationSettingsCls: Any,
    evaluate_ticker_fn: Any,
    evaluate_ticker_hybrid_fn: Any,
    split_overseas_fn: Any,
    excd_from_suffix_fn: Any,
) -> None:
    cfg = runtime.cfg
    eval_settings = EvaluationSettingsCls(
        use_sma200_filter=cfg.use_sma200_filter,
        gap_atr_multiplier=cfg.gap_atr_multiplier,
        min_dollar_volume=cfg.min_dollar_volume,
        us_min_dollar_volume=cfg.us_min_dollar_volume,
        min_history_bars=cfg.min_history_bars,
        exclude_etf_etn=cfg.exclude_etf_etn,
        require_slope_up=cfg.require_slope_up,
        rs_lookback_days=cfg.rs_lookback_days,
        rs_benchmark_return=cfg.rs_benchmark_return,
        min_price=cfg.min_price,
        us_min_price=cfg.us_min_price,
    )
    hybrid_settings = HybridEvaluationSettingsCls(
        sma_trend_period=cfg.hybrid.sma_trend_period,
        ema_short_period=cfg.hybrid.ema_short_period,
        ema_mid_period=cfg.hybrid.ema_mid_period,
        rsi_period=cfg.hybrid.rsi_period,
        rsi_zone_low=cfg.hybrid.rsi_zone_low,
        rsi_zone_high=cfg.hybrid.rsi_zone_high,
        rsi_oversold_low=cfg.hybrid.rsi_oversold_low,
        rsi_oversold_high=cfg.hybrid.rsi_oversold_high,
        pullback_max_bars=cfg.hybrid.pullback_max_bars,
        breakout_consolidation_min_bars=cfg.hybrid.breakout_consolidation_min_bars,
        breakout_consolidation_max_bars=cfg.hybrid.breakout_consolidation_max_bars,
        volume_lookback_days=cfg.hybrid.volume_lookback_days,
        max_gap_pct=cfg.hybrid.max_gap_pct,
        use_sma60_filter=cfg.hybrid.use_sma60_filter,
        sma60_period=cfg.hybrid.sma60_period,
        kr_breakout_requires_confirmation=cfg.hybrid.kr_breakout_requires_confirmation,
        gap_atr_multiplier=cfg.gap_atr_multiplier,
        min_history_bars=cfg.min_history_bars,
        min_price=cfg.min_price,
        us_min_price=cfg.us_min_price,
        min_dollar_volume=cfg.min_dollar_volume,
        us_min_dollar_volume=cfg.us_min_dollar_volume,
        exclude_etf_etn=cfg.exclude_etf_etn,
    )

    for ticker in runtime.tickers:
        ticker_candles = runtime.market_data.get(ticker)
        if not ticker_candles:
            continue

        meta = dict(runtime.screener_meta_map.get(ticker, {}))
        meta["currency"] = runtime.ticker_currency.get(ticker, "KRW")
        _, suffix = split_overseas_fn(ticker)
        if "exchange" not in meta:
            meta["exchange"] = excd_from_suffix_fn(suffix)
        data_source = runtime.ticker_data_source.get(ticker, cfg.data_provider)
        meta["data_source"] = data_source
        meta["provider"] = data_source
        meta["data_dir"] = cfg.data_dir
        if runtime.fx_rate is not None:
            meta["usd_krw_rate"] = runtime.fx_rate

        try:
            if cfg.strategy_mode == "sma_ema_hybrid":
                result_hybrid = evaluate_ticker_hybrid_fn(
                    ticker, ticker_candles, hybrid_settings, meta
                )
                if result_hybrid.candidate:
                    runtime.candidates.append(result_hybrid.candidate)
                elif result_hybrid.reason:
                    detail = f"{ticker}: {result_hybrid.reason}"
                    if _is_system_result(result_hybrid):
                        runtime.failures.append(detail)
                        runtime.system_issues.append(detail)
                        runtime.logger.warning("%s", detail)
                    else:
                        runtime.screen_outs.append(detail)
                        runtime.logger.info("%s", detail)
                continue

            result = evaluate_ticker_fn(ticker, ticker_candles, eval_settings, meta)
            if result.candidate:
                runtime.candidates.append(result.candidate)
            elif result.reason:
                detail = f"{ticker}: {result.reason}"
                if _is_system_result(result):
                    runtime.failures.append(detail)
                    runtime.system_issues.append(detail)
                    runtime.logger.warning("%s", detail)
                else:
                    runtime.screen_outs.append(detail)
                    runtime.logger.info("%s", detail)
        except Exception as exc:
            detail = (
                f"{ticker}: Unexpected evaluation error ({type(exc).__name__}: {exc})"
            )
            runtime.failures.append(detail)
            runtime.system_issues.append(detail)
            runtime.fatal_failure = True
            runtime.logger.exception("%s", detail)


def _decorate_candidates(
    runtime: _ScanRuntime,
    *,
    apply_currency_display_fn: Any,
    lookup_holiday_fn: Any,
    us_market_status_fn: Any,
) -> None:
    def _metric(
        candidate: dict[str, Any],
        primary_key: str,
        *,
        fallback_key: str | None = None,
        default: float = float("-inf"),
    ) -> float:
        primary = _to_float(candidate.get(primary_key))
        if primary is not None:
            return primary
        if fallback_key is not None:
            fallback = _to_float(candidate.get(fallback_key))
            if fallback is not None:
                return fallback
        return default

    runtime.candidates.sort(
        key=lambda candidate: (
            -_metric(candidate, "score_value", fallback_key="score", default=0.0),
            -_metric(candidate, "rs_diff_value"),
            -_metric(candidate, "avg_dollar_volume_value"),
            -_metric(candidate, "pct_change_value"),
            str(candidate.get("ticker", "")),
        )
    )
    for candidate in runtime.candidates:
        apply_currency_display_fn(candidate, runtime.fx_rate, runtime.fx_meta_note)
        if candidate.get("currency", "KRW").upper() != "USD":
            continue

        holiday_entry: HolidayEntry | None = None
        date_key = runtime.latest_dates.get(candidate.get("ticker", ""))
        if date_key:
            holiday_entry = runtime.us_holidays_cache.get(date_key)
            if not holiday_entry:
                try:
                    date_obj = dt.datetime.strptime(date_key, "%Y%m%d").date()
                    holiday_entry = lookup_holiday_fn(
                        runtime.cfg.data_dir, "US", date_obj
                    )
                except ValueError:
                    holiday_entry = None

        if holiday_entry:
            status = "Open" if holiday_entry.is_open else "Holiday"
            note = holiday_entry.note or ""
            candidate["market_status"] = f"US {status}{(' - ' + note) if note else ''}"
        else:
            candidate["market_status"] = (
                f"US market {us_market_status_fn(data_dir=runtime.cfg.data_dir)}"
            )


def _write_scan_report(runtime: _ScanRuntime, *, write_report_fn: Any) -> str:
    system_issues = list(dict.fromkeys(runtime.system_issues + runtime.failures))
    screen_outs = list(dict.fromkeys(runtime.screen_outs))
    combined_issues = list(dict.fromkeys(system_issues + screen_outs))
    return write_report_fn(
        report_dir=runtime.cfg.report_dir,
        provider=runtime.cfg.data_provider,
        universe_count=len(runtime.tickers),
        candidates=runtime.candidates,
        failures=combined_issues,
        system_issues=system_issues,
        screen_outs=screen_outs,
        cache_hint=runtime.cache_hint,
        report_type="buy",
        strategy_mode=runtime.cfg.strategy_mode,
    )
