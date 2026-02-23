from __future__ import annotations

import datetime as dt
import logging

from . import scan_evaluation, scan_screener
from .config import Config, load_config, load_watchlist
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.holiday_cache import HolidayEntry, lookup_holiday, merge_holidays
from .data.kis_client import KISClient, KISClientError, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .market_data_service import (
    MarketDataPolicy,
    MarketDataService,
    scan_legacy_cache_keys,
)
from .report.markdown import write_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .scan_types import (
    _coerce_nday,
    _excd_from_suffix,
    _filter_tickers_by_markets,
    _format_ny_now_for_log,
    _infer_currency,
    _ScanRuntime,
    _split_overseas,
)
from .screener import KISScreener, ScreenRequest
from .screener.kis_overseas_screener import KISOverseasScreener as KUS
from .screener.kis_overseas_screener import ScreenRequest as KUSReq
from .screener.overseas_screener import ScreenRequest as USScreenRequest
from .screener.overseas_screener import USSimpleScreener as USScreener
from .signals.evaluator import EvaluationSettings, evaluate_ticker
from .signals.hybrid_buy import HybridEvaluationSettings, evaluate_ticker_hybrid
from .utils.market_time import us_market_status, us_session_info


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def _build_market_data_service() -> MarketDataService:
    return MarketDataService(
        KISCredentialsCls=KISCredentials,
        KISClientCls=KISClient,
        PykrxClientCls=PykrxClient,
        PykrxClientErrorCls=PykrxClientError,
        infer_env_from_base_fn=_infer_env_from_base,
        load_json_fn=load_json,
        save_json_fn=save_json,
    )


def _build_scan_market_data_policy(
    runtime: _ScanRuntime, *, screener_enabled: bool
) -> MarketDataPolicy:
    unsupported_msg = (
        "Screener currently supports KIS provider only." if screener_enabled else None
    )
    return MarketDataPolicy(
        tickers=runtime.tickers,
        target_bars=max(runtime.cfg.min_history_bars, 200),
        split_symbol_and_suffix_fn=_split_overseas,
        exchange_from_suffix_fn=_excd_from_suffix,
        pykrx_error_attr="pykrx_import_error",
        pykrx_initialized_log_message="PyKRX client initialized for fallback/provider usage",
        init_unsupported_provider_message=unsupported_msg,
        init_mark_fatal_on_unsupported=screener_enabled,
        legacy_cache_keys_fn=scan_legacy_cache_keys,
        on_candles_applied_fn=_update_latest_date,
        before_kis_collection_fn=_refresh_us_holidays_if_needed,
    )


def _resolve_scan_fx(runtime: _ScanRuntime) -> None:
    runtime.ticker_currency = {
        ticker: _infer_currency(ticker) for ticker in runtime.tickers
    }
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate(
        cfg=runtime.cfg,
        ticker_currency=runtime.ticker_currency,
        tickers=runtime.tickers,
        kis_client=runtime.kis_client,
        logger=runtime.logger,
    )
    runtime.fx_rate = resolved_rate
    runtime.fx_meta_note = resolved_note
    if fx_messages:
        runtime.failures.extend(fx_messages)


def _refresh_us_holidays(runtime: _ScanRuntime) -> dict[str, HolidayEntry]:
    if runtime.kis_client is None:
        return {}
    try:
        now = dt.datetime.now()
        start = now.strftime("%Y%m%d")
        end = (now + dt.timedelta(days=30)).strftime("%Y%m%d")
    except Exception:
        start = end = dt.date.today().strftime("%Y%m%d")

    runtime.logger.info("Refreshing US holidays via KIS: %s -> %s", start, end)
    try:
        items = runtime.kis_client.overseas_holidays(
            country_code="US",
            start_date=start,
            end_date=end,
        )
    except KISClientError as exc:
        message = str(exc)
        if "HTTP 404" in message:
            runtime.logger.info(
                "US holiday API returned 404 (no entries from %s to %s)", start, end
            )
            return {}
        runtime.logger.warning("Failed to refresh US holidays: %s", message)
        return {}

    runtime.logger.info(
        "US holiday API succeeded: %s rows for %s -> %s", len(items), start, end
    )
    if items:
        runtime.logger.debug("US holiday sample row: %s", items[0])
    return merge_holidays(runtime.cfg.data_dir, "US", items)


def _refresh_us_holidays_if_needed(runtime: _ScanRuntime) -> None:
    if runtime.kis_client is None:
        return
    if "US" in runtime.cfg.universe_markets or any(
        currency.upper() == "USD" for currency in runtime.ticker_currency.values()
    ):
        runtime.us_holidays_cache = _refresh_us_holidays(runtime)


def _update_latest_date(
    runtime: _ScanRuntime, ticker: str, candles: list[dict[str, float | str]]
) -> None:
    last_date = str(candles[-1].get("date") or "") if candles else ""
    if last_date:
        runtime.latest_dates[ticker] = last_date


def _collect_scan_runtime(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
    screener_only: bool,
    screener_limit: int,
    evaluation_limit: int | None,
) -> None:
    market_data_service = _build_market_data_service()
    provider_policy = _build_scan_market_data_policy(
        runtime,
        screener_enabled=screener_enabled,
    )
    market_data_service.initialize_provider(runtime, policy=provider_policy)

    scan_screener._run_screeners(
        runtime,
        screener_enabled=screener_enabled,
        screener_only=screener_only,
        screener_limit=screener_limit,
        ScreenRequestCls=ScreenRequest,
        KISScreenerCls=KISScreener,
        KUSCls=KUS,
        KUSReqCls=KUSReq,
        USScreenerCls=USScreener,
        USScreenRequestCls=USScreenRequest,
        us_session_info_fn=us_session_info,
        coerce_nday_fn=_coerce_nday,
        format_ny_now_for_log_fn=_format_ny_now_for_log,
    )
    scan_screener._enforce_ticker_limit(runtime, ticker_limit=evaluation_limit)

    _resolve_scan_fx(runtime)
    collect_policy = _build_scan_market_data_policy(
        runtime,
        screener_enabled=screener_enabled,
    )
    market_data_service.collect_market_data(runtime, policy=collect_policy)


def _evaluate_scan_runtime(runtime: _ScanRuntime) -> None:
    scan_evaluation._evaluate_candidates(
        runtime,
        EvaluationSettingsCls=EvaluationSettings,
        HybridEvaluationSettingsCls=HybridEvaluationSettings,
        evaluate_ticker_fn=evaluate_ticker,
        evaluate_ticker_hybrid_fn=evaluate_ticker_hybrid,
        split_overseas_fn=_split_overseas,
        excd_from_suffix_fn=_excd_from_suffix,
    )
    scan_evaluation._decorate_candidates(
        runtime,
        apply_currency_display_fn=scan_evaluation._apply_currency_display,
        lookup_holiday_fn=lookup_holiday,
        us_market_status_fn=us_market_status,
    )


def _render_scan_report(runtime: _ScanRuntime) -> str:
    return scan_evaluation._write_scan_report(runtime, write_report_fn=write_report)


def run_scan(
    *,
    limit: int | None,
    watchlist_path: str | None,
    provider: str | None,
    screener_limit: int | None = None,
    universe: str | None = None,
) -> int:
    logger = logging.getLogger(__name__)
    try:
        cfg: Config = load_config(provider_override=provider, limit_override=limit)
    except (ConfigLoadError, HoldingsLoadError) as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    loaded_tickers = scan_screener._load_scan_tickers(
        cfg,
        watchlist_path,
        load_watchlist_fn=load_watchlist,
    )
    filtered_tickers = _filter_tickers_by_markets(loaded_tickers, cfg.universe_markets)
    if len(filtered_tickers) != len(loaded_tickers):
        logger.info(
            "Watchlist filtered by universe markets=%s (%s -> %s tickers)",
            ",".join(cfg.universe_markets),
            len(loaded_tickers),
            len(filtered_tickers),
        )

    runtime = _ScanRuntime(
        cfg=cfg,
        logger=logger,
        tickers=filtered_tickers,
    )
    effective_screener_limit: int = (
        cfg.screener_limit if screener_limit is None else screener_limit
    )
    screener_enabled, screener_only = scan_screener._resolve_screener_flags(
        cfg, universe
    )

    _collect_scan_runtime(
        runtime,
        screener_enabled=screener_enabled,
        screener_only=screener_only,
        screener_limit=effective_screener_limit,
        evaluation_limit=cfg.screen_limit,
    )

    if not runtime.tickers:
        msg = "No tickers provided (watchlist empty or missing)"
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True

    _evaluate_scan_runtime(runtime)

    if runtime.tickers and not runtime.market_data:
        runtime.fatal_failure = True
        runtime.logger.error("Failed to retrieve market data for requested tickers")

    out_path = _render_scan_report(runtime)
    runtime.logger.info("Buy report written to: %s", out_path)
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="buy",
            logger=runtime.logger,
        )
    except SupabaseStorageError as exc:
        runtime.failures.append(f"Supabase upload failed: {exc}")
        runtime.fatal_failure = True
        runtime.logger.error("Supabase report upload failed: %s", exc)
    else:
        if uploaded_key:
            runtime.logger.info("Buy report uploaded to Supabase: %s", uploaded_key)

    if runtime.fatal_failure:
        runtime.logger.error(
            "Scan completed with fatal errors. See failures section in report."
        )
        return 1
    if runtime.failures:
        runtime.logger.warning("Scan completed with warnings. See report for details.")
    return 0


__all__ = ["run_scan"]
