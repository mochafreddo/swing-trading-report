from __future__ import annotations

import datetime as dt
from typing import Any

from .data.holiday_cache import HolidayEntry
from .data.kis_client import KISClientError
from .data.pykrx_client import PykrxClientError
from .report.run_meta import build_run_meta
from .report.session_state import (
    resolve_run_session_state,
    resolve_run_session_state_map,
)
from .scan_types import _excd_from_suffix, _ScanRuntime, _split_overseas, _to_float
from .signals.eval_index import choose_eval_index
from .tickers import infer_market_from_ticker, parse_ticker

_SYSTEM_REASON_PREFIXES = (
    "Not enough completed candles",
    "Not enough completed history",
    "Insufficient price data",
    "No candle data",
)
_ENTRY_REFERENCE_RAW_LOOKBACK_BARS = 10
_RS_BENCHMARK_LOOKBACK_BUFFER_BARS = 2


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


def _normalize_eval_date_key(value: Any) -> str | None:
    date_text = str(value or "").strip().replace("-", "")
    if len(date_text) != 8 or not date_text.isdigit():
        return None
    return date_text


def _record_entry_reference_issue(runtime: _ScanRuntime, message: str) -> None:
    if message not in runtime.system_issues:
        runtime.system_issues.append(message)


def _record_rs_benchmark_issue(runtime: _ScanRuntime, message: str) -> None:
    if message not in runtime.system_issues:
        runtime.system_issues.append(message)
        runtime.logger.warning("%s", message)


def _resolve_raw_entry_reference_close(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
    eval_date_key: str,
) -> tuple[float | None, str | None]:
    rows: list[dict[str, Any]]
    provider = runtime.cfg.data_provider

    if provider == "kis":
        if runtime.kis_client is None:
            return (
                None,
                f"{ticker}: raw entry reference close unavailable (KIS client not initialized)",
            )
        try:
            if market == "US":
                symbol, suffix = _split_overseas(ticker)
                exchange = _excd_from_suffix(suffix)
                if exchange is None:
                    if str(suffix or "").strip().upper() == "US":
                        exchange = "NAS"
                    else:
                        return (
                            None,
                            f"{ticker}: raw entry reference close unavailable (exchange unresolved)",
                        )
                rows = runtime.kis_client.overseas_daily_candles(
                    symbol=symbol,
                    exchange=exchange,
                    count=_ENTRY_REFERENCE_RAW_LOOKBACK_BARS,
                    adjusted=False,
                )
            else:
                symbol, _ = _split_overseas(ticker)
                rows = runtime.kis_client.daily_candles(
                    symbol,
                    count=_ENTRY_REFERENCE_RAW_LOOKBACK_BARS,
                    adjusted=False,
                )
        except KISClientError as exc:
            return None, f"{ticker}: raw entry reference close unavailable ({exc})"
    elif provider == "pykrx":
        if market == "US":
            return (
                None,
                f"{ticker}: raw entry reference close unavailable (pykrx does not support US)",
            )
        if runtime.pykrx_client is None:
            return (
                None,
                f"{ticker}: raw entry reference close unavailable (PyKRX client not initialized)",
            )
        try:
            rows = runtime.pykrx_client.daily_candles(
                ticker,
                count=_ENTRY_REFERENCE_RAW_LOOKBACK_BARS,
                adjusted=False,
            )
        except PykrxClientError as exc:
            return None, f"{ticker}: raw entry reference close unavailable ({exc})"
    else:
        return (
            None,
            f"{ticker}: raw entry reference close unavailable (provider {provider!r} unsupported)",
        )

    for row in reversed(rows):
        row_date = _normalize_eval_date_key(row.get("date"))
        if row_date != eval_date_key:
            continue
        raw_close = _to_float(row.get("close"))
        if raw_close is not None and raw_close > 0:
            return raw_close, None

    return (
        None,
        f"{ticker}: raw entry reference close unavailable for eval_date {eval_date_key}",
    )


def _resolve_adjusted_benchmark_candles(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
    count: int,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    provider = runtime.cfg.data_provider
    parsed = parse_ticker(ticker)

    if provider == "kis":
        if runtime.kis_client is None:
            return (
                None,
                f"{ticker}: RS benchmark unavailable (KIS client not initialized)",
            )
        try:
            if market == "US":
                if parsed.exchange is None:
                    return (
                        None,
                        f"{ticker}: RS benchmark unavailable (exchange unresolved)",
                    )
                rows = runtime.kis_client.overseas_daily_candles(
                    symbol=parsed.symbol,
                    exchange=parsed.exchange,
                    count=count,
                    adjusted=True,
                )
            else:
                rows = runtime.kis_client.daily_candles(
                    parsed.symbol,
                    count=count,
                    adjusted=True,
                )
        except KISClientError as exc:
            return None, f"{ticker}: RS benchmark unavailable ({exc})"
        return rows, None

    if provider == "pykrx":
        if market == "US":
            return (
                None,
                f"{ticker}: RS benchmark unavailable (pykrx does not support US)",
            )
        if runtime.pykrx_client is None:
            return (
                None,
                f"{ticker}: RS benchmark unavailable (PyKRX client not initialized)",
            )
        try:
            rows = runtime.pykrx_client.daily_candles(
                parsed.symbol,
                count=count,
                adjusted=True,
            )
        except PykrxClientError as exc:
            return None, f"{ticker}: RS benchmark unavailable ({exc})"
        return rows, None

    return (
        None,
        f"{ticker}: RS benchmark unavailable (provider {provider!r} unsupported)",
    )


def _compute_rs_benchmark_return(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
) -> tuple[float | None, str | None]:
    lookback_days = runtime.cfg.rs_lookback_days
    target_bars = max(
        runtime.cfg.min_history_bars,
        lookback_days + _RS_BENCHMARK_LOOKBACK_BUFFER_BARS,
    )
    rows, issue = _resolve_adjusted_benchmark_candles(
        runtime,
        ticker=ticker,
        market=market,
        count=target_bars,
    )
    if rows is None:
        return None, issue

    currency = "USD" if market == "US" else "KRW"
    idx_eval, _ = choose_eval_index(
        rows,
        meta={"currency": currency, "data_dir": runtime.cfg.data_dir},
    )
    if idx_eval < lookback_days:
        return (
            None,
            f"{ticker}: RS benchmark unavailable (insufficient completed history)",
        )

    closes = [_to_float(candle.get("close")) for candle in rows[: idx_eval + 1]]
    if any(close is None for close in closes):
        return None, f"{ticker}: RS benchmark unavailable (invalid close series)"

    latest_close = closes[-1]
    base_close = closes[-lookback_days - 1]
    if latest_close is None or base_close is None or base_close <= 0:
        return None, f"{ticker}: RS benchmark unavailable (invalid lookback base)"
    return (latest_close - base_close) / base_close, None


def _resolve_rs_benchmark_context(
    runtime: _ScanRuntime,
) -> tuple[dict[str, float], dict[str, str], bool]:
    if runtime.cfg.rs_lookback_days <= 0:
        return {}, {}, False

    active_markets = sorted(
        {infer_market_from_ticker(ticker) for ticker in runtime.tickers if ticker}
    )
    if not active_markets:
        return {}, {}, False

    configured_benchmarks = {
        "KR": runtime.cfg.rs_benchmark_ticker_kr,
        "US": runtime.cfg.rs_benchmark_ticker_us,
    }
    dynamic_requested = any(
        configured_benchmarks.get(market) for market in active_markets
    )
    if not dynamic_requested:
        return {}, {}, False

    benchmark_returns: dict[str, float] = {}
    benchmark_tickers: dict[str, str] = {}
    issues: list[str] = []
    for market in active_markets:
        benchmark_ticker = configured_benchmarks.get(market)
        if not benchmark_ticker:
            issues.append(f"{market}: benchmark ticker not configured")
            continue
        benchmark_return, issue = _compute_rs_benchmark_return(
            runtime,
            ticker=benchmark_ticker,
            market=market,
        )
        if benchmark_return is None:
            issues.append(issue or f"{market}: benchmark return unavailable")
            continue
        benchmark_returns[market] = benchmark_return
        benchmark_tickers[market] = benchmark_ticker

    if issues:
        _record_rs_benchmark_issue(
            runtime,
            "RS benchmark disabled: " + "; ".join(issues),
        )
        return {}, {}, True

    return benchmark_returns, benchmark_tickers, True


def _enrich_entry_reference_prices(runtime: _ScanRuntime) -> None:
    for candidate in runtime.candidates:
        ticker = str(candidate.get("ticker") or "").strip().upper()
        if not ticker:
            continue

        close_value = _to_float(candidate.get("close_value"))
        if close_value is not None and close_value > 0:
            candidate.setdefault("signal_close_adjusted_value", close_value)
        candidate.setdefault("signal_price_basis", "adjusted")

        eval_date_key = _normalize_eval_date_key(candidate.get("eval_date"))
        if eval_date_key is None:
            candidate.setdefault("entry_reference_close_raw_value", None)
            candidate.setdefault("entry_reference_eval_date", None)
            continue

        market = (
            "US"
            if str(runtime.ticker_currency.get(ticker, "KRW")).strip().upper() == "USD"
            else "KR"
        )
        raw_close, issue = _resolve_raw_entry_reference_close(
            runtime,
            ticker=ticker,
            market=market,
            eval_date_key=eval_date_key,
        )
        candidate["entry_reference_close_raw_value"] = raw_close
        candidate["entry_reference_eval_date"] = eval_date_key
        if raw_close is None and issue is not None:
            _record_entry_reference_issue(runtime, issue)


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
    (
        benchmark_returns_by_market,
        benchmark_tickers_by_market,
        _dynamic_rs_requested,
    ) = _resolve_rs_benchmark_context(runtime)

    def _with_strategy_mode(candidate: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(candidate)
        enriched.setdefault("strategy_mode", cfg.strategy_mode)
        return enriched

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
        ticker_market = "US" if meta["currency"].upper() == "USD" else "KR"
        benchmark_return = benchmark_returns_by_market.get(ticker_market)
        if benchmark_return is not None:
            meta["rs_benchmark_return"] = benchmark_return
            meta["rs_benchmark_ticker"] = benchmark_tickers_by_market.get(ticker_market)

        try:
            if cfg.strategy_mode == "sma_ema_hybrid":
                result_hybrid = evaluate_ticker_hybrid_fn(
                    ticker, ticker_candles, hybrid_settings, meta
                )
                if result_hybrid.candidate:
                    runtime.candidates.append(
                        _with_strategy_mode(result_hybrid.candidate)
                    )
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
                runtime.candidates.append(_with_strategy_mode(result.candidate))
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

    _enrich_entry_reference_prices(runtime)


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
            -_metric(candidate, "rs_diff_value", default=0.0),
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
    markets = sorted(
        {
            str(market).strip().upper()
            for market in runtime.cfg.universe_markets
            if str(market).strip()
        }
    )
    if len(markets) == 1 and markets[0] in {"KR", "US"}:
        eval_market = markets[0]
        eval_markets = None
    else:
        eval_market = "MIXED"
        eval_markets = [m for m in markets if m in {"KR", "US"}] or None
    state_markets = [eval_market] if eval_market in {"KR", "US"} else eval_markets
    session_state_by_market = resolve_run_session_state_map(
        markets=state_markets,
        data_dir=runtime.cfg.data_dir,
    )
    session_state = resolve_run_session_state(
        markets=state_markets,
        data_dir=runtime.cfg.data_dir,
        session_state_by_market=session_state_by_market,
    )
    run_meta = build_run_meta(
        market=eval_market,
        markets=eval_markets,
        session_state=session_state,
        session_state_by_market=(
            session_state_by_market if eval_market == "MIXED" else None
        ),
        eval_index_policy="choose_eval_index:v1",
        config_snapshot={
            "strategy_mode": runtime.cfg.strategy_mode,
            "use_sma200_filter": runtime.cfg.use_sma200_filter,
            "require_slope_up": runtime.cfg.require_slope_up,
            "gap_atr_multiplier": runtime.cfg.gap_atr_multiplier,
            "min_history_bars": runtime.cfg.min_history_bars,
            "rs_lookback_days": runtime.cfg.rs_lookback_days,
            "rs_benchmark_ticker_kr": runtime.cfg.rs_benchmark_ticker_kr,
            "rs_benchmark_ticker_us": runtime.cfg.rs_benchmark_ticker_us,
            "min_price": runtime.cfg.min_price,
            "us_min_price": runtime.cfg.us_min_price,
            "min_dollar_volume": runtime.cfg.min_dollar_volume,
            "us_min_dollar_volume": runtime.cfg.us_min_dollar_volume,
            "exclude_etf_etn": runtime.cfg.exclude_etf_etn,
            "universe_markets": runtime.cfg.universe_markets,
        },
    )
    return write_report_fn(  # type: ignore[no-any-return]
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
        run_meta=run_meta,
    )
