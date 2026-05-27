from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from .data.holiday_cache import HolidayEntry
from .data.kis_client import KISClientError
from .data.pykrx_client import PykrxClientError
from .report.run_meta import build_run_meta
from .report.session_state import (
    resolve_run_session_state,
    resolve_run_session_state_map,
)
from .report.summary_metrics import (
    build_market_data_summary,
    compute_ratio,
    count_provider_fallbacks,
)
from .scan_types import _ScanRuntime, _to_float
from .signals.eval_index import choose_eval_index
from .signals.indicators import sma
from .tickers import infer_market_from_ticker, parse_ticker

_SYSTEM_REASON_PREFIXES = (
    "Not enough completed candles",
    "Not enough completed history",
    "Insufficient price data",
    "No candle data",
)
_MARKET_REGIME_SMA_PERIOD = 200
_RS_BENCHMARK_LOOKBACK_BUFFER_BARS = 2
_INCOMPLETE_TAIL_BUFFER_BARS = 1


@dataclass(frozen=True)
class MarketRegimeContext:
    benchmark_ticker: str
    benchmark_close: float
    benchmark_sma200: float
    is_bullish: bool


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


def _record_system_issue(
    runtime: _ScanRuntime, message: str, *, warn: bool = False
) -> None:
    if message in runtime.system_issues:
        return
    runtime.system_issues.append(message)
    if warn:
        runtime.logger.warning("%s", message)


def _latest_market_data_date_key(runtime: _ScanRuntime, market: str) -> str | None:
    date_keys: list[str] = []
    for ticker in runtime.tickers:
        if infer_market_from_ticker(ticker) != market:
            continue

        date_key = _normalize_eval_date_key(runtime.latest_dates.get(ticker))
        if date_key is not None:
            date_keys.append(date_key)
            continue

        for row in reversed(runtime.market_data.get(ticker, [])):
            row_date_key = _normalize_eval_date_key(row.get("date"))
            if row_date_key is not None:
                date_keys.append(row_date_key)
                break

    return max(date_keys) if date_keys else None


def _normalize_benchmark_rows(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
    rows: list[dict[str, Any]],
    unavailable_label: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        date_key = _normalize_eval_date_key(row.get("date"))
        if date_key is None:
            continue
        normalized_row = dict(row)
        normalized_row["date"] = date_key
        normalized_rows.append(normalized_row)

    if not normalized_rows:
        return [], None

    normalized_rows.sort(key=lambda row: str(row.get("date") or ""))
    market_date_key = _latest_market_data_date_key(runtime, market)
    if market_date_key is None:
        return normalized_rows, None

    aligned_rows = [
        row for row in normalized_rows if str(row.get("date") or "") <= market_date_key
    ]
    latest_aligned_date = (
        str(aligned_rows[-1].get("date") or "") if aligned_rows else None
    )
    if latest_aligned_date != market_date_key:
        if latest_aligned_date is None:
            return (
                None,
                f"{ticker}: {unavailable_label} unavailable "
                f"(benchmark candles do not cover market {market_date_key})",
            )
        return (
            None,
            f"{ticker}: {unavailable_label} unavailable "
            f"(stale benchmark candles; latest {latest_aligned_date} < market {market_date_key})",
        )

    dropped_future_count = len(normalized_rows) - len(aligned_rows)
    if dropped_future_count > 0:
        runtime.logger.info(
            "%s: Trimmed %s benchmark candle(s) after market date %s",
            ticker,
            dropped_future_count,
            market_date_key,
        )
    return aligned_rows, None


def _resolve_raw_entry_reference_close(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    eval_date_key: str,
) -> tuple[float | None, str | None]:
    rows = runtime.raw_market_data.get(ticker)
    if rows is None:
        return (
            None,
            f"{ticker}: raw entry reference close unavailable from batched market data",
        )

    return _resolve_raw_entry_reference_close_from_rows(
        ticker=ticker,
        eval_date_key=eval_date_key,
        rows=rows,
    )


def _resolve_raw_entry_reference_close_from_rows(
    *,
    ticker: str,
    eval_date_key: str,
    rows: list[dict[str, Any]],
) -> tuple[float | None, str | None]:
    if not rows:
        return (
            None,
            f"{ticker}: raw entry reference close unavailable from cached market data",
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
        f"{ticker}: raw entry reference close unavailable for eval_date {eval_date_key} from cached market data",
    )


def _resolve_adjusted_benchmark_candles(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
    count: int,
    unavailable_label: str = "RS benchmark",
) -> tuple[list[dict[str, Any]] | None, str | None]:
    provider = runtime.cfg.data_provider
    parsed = parse_ticker(ticker)

    if provider == "kis":
        if runtime.kis_client is None:
            return (
                None,
                f"{ticker}: {unavailable_label} unavailable (KIS client not initialized)",
            )
        try:
            if market == "US":
                if parsed.exchange is None:
                    return (
                        None,
                        f"{ticker}: {unavailable_label} unavailable (exchange unresolved)",
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
            return None, f"{ticker}: {unavailable_label} unavailable ({exc})"
        return _normalize_benchmark_rows(
            runtime,
            ticker=ticker,
            market=market,
            rows=rows,
            unavailable_label=unavailable_label,
        )

    if provider == "pykrx":
        if market == "US":
            return (
                None,
                f"{ticker}: {unavailable_label} unavailable (pykrx does not support US)",
            )
        if runtime.pykrx_client is None:
            return (
                None,
                f"{ticker}: {unavailable_label} unavailable (PyKRX client not initialized)",
            )
        try:
            rows = runtime.pykrx_client.daily_candles(
                parsed.symbol,
                count=count,
                adjusted=True,
            )
        except PykrxClientError as exc:
            return None, f"{ticker}: {unavailable_label} unavailable ({exc})"
        return _normalize_benchmark_rows(
            runtime,
            ticker=ticker,
            market=market,
            rows=rows,
            unavailable_label=unavailable_label,
        )

    return (
        None,
        f"{ticker}: {unavailable_label} unavailable (provider {provider!r} unsupported)",
    )


def _compute_rs_benchmark_return(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
) -> tuple[float | None, str | None]:
    lookback_days = runtime.cfg.rs_lookback_days
    target_bars = (
        max(
            runtime.cfg.min_history_bars,
            lookback_days + _RS_BENCHMARK_LOOKBACK_BUFFER_BARS,
        )
        + _INCOMPLETE_TAIL_BUFFER_BARS
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
    runtime.rs_benchmark_requested_count = 0
    runtime.rs_benchmark_unavailable_count = 0
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
    requested_markets = {
        market for market in active_markets if configured_benchmarks.get(market)
    }
    runtime.rs_benchmark_requested_count = sum(
        1
        for ticker in runtime.tickers
        if infer_market_from_ticker(ticker) in requested_markets
    )
    dynamic_requested = any(
        configured_benchmarks.get(market) for market in active_markets
    )
    if not dynamic_requested:
        return {}, {}, False

    benchmark_returns: dict[str, float] = {}
    benchmark_tickers: dict[str, str] = {}
    unavailable_markets: set[str] = set()
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
            unavailable_markets.add(market)
            issues.append(issue or f"{market}: benchmark return unavailable")
            continue
        benchmark_returns[market] = benchmark_return
        benchmark_tickers[market] = benchmark_ticker

    runtime.rs_benchmark_unavailable_count = sum(
        1
        for ticker in runtime.tickers
        if infer_market_from_ticker(ticker) in unavailable_markets
    )

    if issues:
        issue_label = (
            "RS benchmark partially disabled"
            if benchmark_returns
            else "RS benchmark disabled"
        )
        _record_system_issue(
            runtime,
            issue_label + ": " + "; ".join(issues),
            warn=True,
        )
        return benchmark_returns, benchmark_tickers, True

    return benchmark_returns, benchmark_tickers, True


def _compute_market_regime_context(
    runtime: _ScanRuntime,
    *,
    ticker: str,
    market: str,
) -> tuple[MarketRegimeContext | None, str | None]:
    target_bars = (
        max(runtime.cfg.min_history_bars, _MARKET_REGIME_SMA_PERIOD)
        + _INCOMPLETE_TAIL_BUFFER_BARS
    )
    rows, issue = _resolve_adjusted_benchmark_candles(
        runtime,
        ticker=ticker,
        market=market,
        count=target_bars,
        unavailable_label="Market regime benchmark",
    )
    if rows is None:
        return None, issue

    currency = "USD" if market == "US" else "KRW"
    idx_eval, _ = choose_eval_index(
        rows,
        meta={"currency": currency, "data_dir": runtime.cfg.data_dir},
    )
    completed_rows = rows[: idx_eval + 1]
    if len(completed_rows) < _MARKET_REGIME_SMA_PERIOD:
        return (
            None,
            f"{ticker}: Market regime unavailable (insufficient completed history for SMA200)",
        )

    closes = [_to_float(candle.get("close")) for candle in completed_rows]
    if any(close is None for close in closes):
        return None, f"{ticker}: Market regime unavailable (invalid close series)"

    close_values = [float(close) for close in closes if close is not None]
    sma200_series = sma(close_values, _MARKET_REGIME_SMA_PERIOD)
    sma200_value = sma200_series[-1] if sma200_series else float("nan")
    if math.isnan(sma200_value):
        return None, f"{ticker}: Market regime unavailable (SMA200 unavailable)"

    latest_close = close_values[-1]
    return (
        MarketRegimeContext(
            benchmark_ticker=ticker,
            benchmark_close=latest_close,
            benchmark_sma200=sma200_value,
            is_bullish=latest_close > sma200_value,
        ),
        None,
    )


def _resolve_market_regime_context(
    runtime: _ScanRuntime,
) -> dict[str, MarketRegimeContext]:
    if not runtime.cfg.use_market_regime_filter:
        return {}

    active_markets = sorted(
        {infer_market_from_ticker(ticker) for ticker in runtime.tickers if ticker}
    )
    if not active_markets:
        return {}

    configured_benchmarks = {
        "KR": runtime.cfg.rs_benchmark_ticker_kr,
        "US": runtime.cfg.rs_benchmark_ticker_us,
    }
    regime_by_market: dict[str, MarketRegimeContext] = {}
    issues: list[str] = []
    for market in active_markets:
        benchmark_ticker = configured_benchmarks.get(market)
        if not benchmark_ticker:
            issues.append(f"{market}: market regime benchmark ticker not configured")
            continue
        context, issue = _compute_market_regime_context(
            runtime,
            ticker=benchmark_ticker,
            market=market,
        )
        if context is None:
            issues.append(issue or f"{market}: market regime unavailable")
            continue
        regime_by_market[market] = context

    if issues:
        issue_label = (
            "Market regime filter partially disabled"
            if regime_by_market
            else "Market regime filter disabled"
        )
        _record_system_issue(
            runtime,
            issue_label + ": " + "; ".join(issues),
            warn=True,
        )

    return regime_by_market


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

        raw_close, issue = _resolve_raw_entry_reference_close(
            runtime,
            ticker=ticker,
            eval_date_key=eval_date_key,
        )
        candidate["entry_reference_close_raw_value"] = raw_close
        candidate["entry_reference_eval_date"] = eval_date_key
        if raw_close is None and issue is not None:
            _record_system_issue(runtime, issue)


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
    enrich_entry_reference_prices: bool = True,
) -> None:
    cfg = runtime.cfg
    market_regimes_by_market = _resolve_market_regime_context(runtime)
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
        rs_lookback_days=cfg.rs_lookback_days,
        rs_benchmark_return=cfg.rs_benchmark_return,
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
        regime_context = market_regimes_by_market.get(ticker_market)
        if regime_context is not None and not regime_context.is_bullish:
            detail = (
                f"{ticker}: Market regime filter blocked "
                f"(benchmark {regime_context.benchmark_ticker} close "
                f"{regime_context.benchmark_close:.2f} <= SMA200 "
                f"{regime_context.benchmark_sma200:.2f})"
            )
            runtime.screen_outs.append(detail)
            runtime.logger.info("%s", detail)
            continue
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

    if enrich_entry_reference_prices:
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

    currencies = {
        str(candidate.get("currency", "KRW")).strip().upper()
        for candidate in runtime.candidates
        if candidate
    }
    has_mixed_currencies = len(currencies) > 1
    can_compare_cross_currency_liquidity = not has_mixed_currencies or (
        runtime.fx_rate is not None and runtime.fx_rate > 0
    )

    def _liquidity_metric(candidate: dict[str, Any]) -> float:
        if not can_compare_cross_currency_liquidity:
            return 0.0
        liquidity = _metric(candidate, "avg_dollar_volume_value")
        currency = str(candidate.get("currency", "KRW")).strip().upper()
        if (
            has_mixed_currencies
            and currency == "USD"
            and runtime.fx_rate is not None
            and runtime.fx_rate > 0
            and liquidity != float("-inf")
        ):
            return liquidity * runtime.fx_rate
        return liquidity

    runtime.candidates.sort(
        key=lambda candidate: (
            -_metric(candidate, "score_value", fallback_key="score", default=0.0),
            -_metric(candidate, "rs_diff_value", default=0.0),
            -_liquidity_metric(candidate),
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
            "use_market_regime_filter": runtime.cfg.use_market_regime_filter,
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
    artifact_dates = sorted(
        {
            normalized
            for normalized in (
                [
                    _normalize_eval_date_key(candidate.get("eval_date"))
                    for candidate in runtime.candidates
                ]
                + [
                    _normalize_eval_date_key(date_key)
                    for date_key in runtime.latest_dates.values()
                ]
            )
            if normalized is not None
        }
    )
    artifact_date = artifact_dates[-1] if artifact_dates else None
    summary_fields = {
        **build_market_data_summary(
            requested_count=len(runtime.tickers),
            covered_count=len(runtime.market_data),
            fallback_count=count_provider_fallbacks(
                tickers=runtime.tickers,
                ticker_data_source=runtime.ticker_data_source,
                primary_provider=runtime.cfg.data_provider,
            ),
        ),
        "rs_benchmark_requested_count": runtime.rs_benchmark_requested_count,
        "rs_benchmark_unavailable_count": runtime.rs_benchmark_unavailable_count,
        "rs_benchmark_unavailable_ratio": compute_ratio(
            numerator=runtime.rs_benchmark_unavailable_count,
            denominator=runtime.rs_benchmark_requested_count,
        ),
    }
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
        summary_fields=summary_fields,
        run_meta=run_meta,
        artifact_date=artifact_date,
    )
