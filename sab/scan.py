from __future__ import annotations

import logging
from functools import partial

from . import scan_evaluation, scan_market_data, scan_screener
from .config import Config, load_config, load_watchlist
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.holiday_cache import lookup_holiday, merge_holidays
from .data.kis_client import KISClient, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
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


def _collect_scan_runtime(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
    screener_only: bool,
    screener_limit: int,
) -> None:
    ensure_pykrx_client = partial(
        scan_market_data._ensure_pykrx_client,
        PykrxClientCls=PykrxClient,
    )
    refresh_us_holidays = partial(
        scan_market_data._refresh_us_holidays,
        merge_holidays_fn=merge_holidays,
    )
    collect_market_data_from_kis = partial(
        scan_market_data._collect_market_data_from_kis,
        load_json_fn=load_json,
        save_json_fn=save_json,
        refresh_us_holidays_fn=refresh_us_holidays,
        ensure_pykrx_client_fn=ensure_pykrx_client,
        split_overseas_fn=_split_overseas,
        excd_from_suffix_fn=_excd_from_suffix,
    )
    collect_market_data_from_pykrx = partial(
        scan_market_data._collect_market_data_from_pykrx,
        PykrxClientErrorCls=PykrxClientError,
    )

    scan_market_data._initialize_provider(
        runtime,
        screener_enabled=screener_enabled,
        KISCredentialsCls=KISCredentials,
        KISClientCls=KISClient,
        ensure_pykrx_client_fn=ensure_pykrx_client,
        infer_env_from_base_fn=_infer_env_from_base,
    )

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

    scan_market_data._resolve_scan_fx(
        runtime,
        resolve_fx_rate_fn=resolve_fx_rate,
        infer_currency_fn=_infer_currency,
    )

    scan_market_data._collect_market_data(
        runtime,
        collect_market_data_from_kis_fn=collect_market_data_from_kis,
        collect_market_data_from_pykrx_fn=collect_market_data_from_pykrx,
    )


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
