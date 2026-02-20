from __future__ import annotations

import logging

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
from .scan_evaluation import _apply_currency_display as _apply_currency_display_impl
from .scan_evaluation import _decorate_candidates as _decorate_candidates_impl
from .scan_evaluation import _evaluate_candidates as _evaluate_candidates_impl
from .scan_evaluation import _write_scan_report as _write_scan_report_impl
from .scan_market_data import _collect_market_data as _collect_market_data_impl
from .scan_market_data import (
    _collect_market_data_from_kis as _collect_market_data_from_kis_impl,
)
from .scan_market_data import (
    _collect_market_data_from_pykrx as _collect_market_data_from_pykrx_impl,
)
from .scan_market_data import _ensure_pykrx_client as _ensure_pykrx_client_impl
from .scan_market_data import _initialize_provider as _initialize_provider_impl
from .scan_market_data import _refresh_us_holidays as _refresh_us_holidays_impl
from .scan_market_data import _resolve_scan_fx as _resolve_scan_fx_impl
from .scan_screener import _load_scan_tickers as _load_scan_tickers_impl
from .scan_screener import _resolve_screener_flags as _resolve_screener_flags_impl
from .scan_screener import _run_screeners as _run_screeners_impl
from .scan_types import (
    _coerce_nday as _coerce_nday_impl,
)
from .scan_types import (
    _excd_from_suffix as _excd_from_suffix_impl,
)
from .scan_types import (
    _filter_tickers_by_markets as _filter_tickers_by_markets_impl,
)
from .scan_types import (
    _format_ny_now_for_log as _format_ny_now_for_log_impl,
)
from .scan_types import (
    _infer_currency as _infer_currency_impl,
)
from .scan_types import (
    _ScanRuntime,
)
from .scan_types import (
    _split_overseas as _split_overseas_impl,
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


def _format_ny_now_for_log(session_info: dict[str, object]) -> str:
    return _format_ny_now_for_log_impl(session_info)


def _infer_currency(ticker: str) -> str:
    return _infer_currency_impl(ticker)


def _filter_tickers_by_markets(
    tickers: list[str], universe_markets: list[str]
) -> list[str]:
    return _filter_tickers_by_markets_impl(tickers, universe_markets)


def _split_overseas(ticker: str) -> tuple[str, str | None]:
    return _split_overseas_impl(ticker)


def _excd_from_suffix(suffix: str | None) -> str | None:
    return _excd_from_suffix_impl(suffix)


def _coerce_nday(value: object) -> int:
    return _coerce_nday_impl(value)


def _load_scan_tickers(cfg: Config, watchlist_path: str | None) -> list[str]:
    return _load_scan_tickers_impl(
        cfg,
        watchlist_path,
        load_watchlist_fn=load_watchlist,
    )


def _resolve_screener_flags(cfg: Config, universe: str | None) -> tuple[bool, bool]:
    return _resolve_screener_flags_impl(cfg, universe)


def _ensure_pykrx_client(runtime: _ScanRuntime) -> PykrxClient | None:
    return _ensure_pykrx_client_impl(runtime, PykrxClientCls=PykrxClient)


def _initialize_provider(runtime: _ScanRuntime, *, screener_enabled: bool) -> None:
    _initialize_provider_impl(
        runtime,
        screener_enabled=screener_enabled,
        KISCredentialsCls=KISCredentials,
        KISClientCls=KISClient,
        ensure_pykrx_client_fn=_ensure_pykrx_client,
        infer_env_from_base_fn=_infer_env_from_base,
    )


def _run_screeners(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
    screener_only: bool,
    screener_limit: int,
) -> None:
    _run_screeners_impl(
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


def _resolve_scan_fx(runtime: _ScanRuntime) -> None:
    _resolve_scan_fx_impl(
        runtime,
        resolve_fx_rate_fn=resolve_fx_rate,
        infer_currency_fn=_infer_currency,
    )


def _refresh_us_holidays(runtime: _ScanRuntime):
    return _refresh_us_holidays_impl(runtime, merge_holidays_fn=merge_holidays)


def _collect_market_data_from_kis(runtime: _ScanRuntime) -> None:
    _collect_market_data_from_kis_impl(
        runtime,
        load_json_fn=load_json,
        save_json_fn=save_json,
        refresh_us_holidays_fn=_refresh_us_holidays,
        ensure_pykrx_client_fn=_ensure_pykrx_client,
        split_overseas_fn=_split_overseas,
        excd_from_suffix_fn=_excd_from_suffix,
    )


def _collect_market_data_from_pykrx(runtime: _ScanRuntime) -> None:
    _collect_market_data_from_pykrx_impl(runtime, PykrxClientErrorCls=PykrxClientError)


def _collect_market_data(runtime: _ScanRuntime) -> None:
    _collect_market_data_impl(
        runtime,
        collect_market_data_from_kis_fn=_collect_market_data_from_kis,
        collect_market_data_from_pykrx_fn=_collect_market_data_from_pykrx,
    )


def _evaluate_candidates(runtime: _ScanRuntime) -> None:
    _evaluate_candidates_impl(
        runtime,
        EvaluationSettingsCls=EvaluationSettings,
        HybridEvaluationSettingsCls=HybridEvaluationSettings,
        evaluate_ticker_fn=evaluate_ticker,
        evaluate_ticker_hybrid_fn=evaluate_ticker_hybrid,
        split_overseas_fn=_split_overseas,
        excd_from_suffix_fn=_excd_from_suffix,
    )


def _apply_currency_display(candidate, fx_rate, fx_meta_note) -> None:
    _apply_currency_display_impl(candidate, fx_rate, fx_meta_note)


def _decorate_candidates(runtime: _ScanRuntime) -> None:
    _decorate_candidates_impl(
        runtime,
        apply_currency_display_fn=_apply_currency_display,
        lookup_holiday_fn=lookup_holiday,
        us_market_status_fn=us_market_status,
    )


def _write_scan_report(runtime: _ScanRuntime) -> str:
    return _write_scan_report_impl(runtime, write_report_fn=write_report)


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

    loaded_tickers = _load_scan_tickers(cfg, watchlist_path)
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
    screener_enabled, screener_only = _resolve_screener_flags(cfg, universe)

    _initialize_provider(runtime, screener_enabled=screener_enabled)
    _run_screeners(
        runtime,
        screener_enabled=screener_enabled,
        screener_only=screener_only,
        screener_limit=effective_screener_limit,
    )
    _resolve_scan_fx(runtime)
    _collect_market_data(runtime)

    if not runtime.tickers:
        msg = "No tickers provided (watchlist empty or missing)"
        runtime.failures.append(msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True

    _evaluate_candidates(runtime)
    _decorate_candidates(runtime)

    if runtime.tickers and not runtime.market_data:
        runtime.fatal_failure = True
        runtime.logger.error("Failed to retrieve market data for requested tickers")

    out_path = _write_scan_report(runtime)
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
