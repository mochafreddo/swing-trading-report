from __future__ import annotations

import logging
import os

from . import scan_evaluation, scan_screener
from .config import Config, load_config, load_watchlist
from .config_loader import ConfigLoadError
from .data.holiday_cache import lookup_holiday
from .data_coverage_policy import MIN_DATA_COVERAGE, is_data_coverage_fatal
from .fx import resolve_fx_rate
from .market_data_common import build_market_data_dependencies
from .market_data_service import ScanMarketData
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


def _build_market_data_service() -> ScanMarketData:
    return ScanMarketData(deps=build_market_data_dependencies())


def _record_system_issue(runtime: _ScanRuntime, message: str) -> None:
    runtime.failures.append(message)
    runtime.system_issues.append(message)


def _mark_missing_scan_market_data(runtime: _ScanRuntime) -> None:
    if not runtime.tickers:
        return
    total = len(runtime.tickers)
    missing = [
        ticker for ticker in runtime.tickers if ticker not in runtime.market_data
    ]
    if not missing:
        return
    missing_count = len(missing)
    covered_count = total - missing_count
    data_coverage = covered_count / total if total > 0 else 0.0
    preview = ", ".join(missing[:10])
    if missing_count > 10:
        preview = f"{preview}, +{missing_count - 10} more"
    message = (
        "Missing market data for "
        f"{missing_count}/{total} tickers (coverage={data_coverage:.2f}, "
        f"required>={MIN_DATA_COVERAGE:.2f}): {preview}"
    )
    _record_system_issue(runtime, message)
    if is_data_coverage_fatal(data_coverage):
        runtime.fatal_failure = True
        runtime.logger.error("%s", message)
        return
    runtime.logger.warning("%s", message)


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
        runtime.system_issues.extend(fx_messages)


def _collect_scan_runtime(
    runtime: _ScanRuntime,
    *,
    screener_enabled: bool,
    screener_only: bool,
    screener_limit: int,
    screener_limit_from_cli: bool,
    evaluation_limit: int | None,
) -> None:
    market_data_service = _build_market_data_service()
    market_data_service.initialize_provider(
        runtime,
        screener_enabled=screener_enabled,
    )

    scan_screener._run_screeners(
        runtime,
        screener_enabled=screener_enabled,
        screener_only=screener_only,
        screener_limit=screener_limit,
        screener_limit_from_cli=screener_limit_from_cli,
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
    if runtime.fatal_failure:
        return
    scan_screener._enforce_ticker_limit(runtime, ticker_limit=evaluation_limit)

    _resolve_scan_fx(runtime)
    if runtime.fatal_failure:
        return
    market_data_service.collect_market_data(runtime)


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
    markets: str | None = None,
) -> int:
    logger = logging.getLogger(__name__)
    markets_override: list[str] | None = None
    if markets is not None:
        parsed_markets = [item.strip() for item in markets.split(",") if item.strip()]
        if parsed_markets:
            markets_override = parsed_markets
    try:
        cfg: Config = load_config(
            provider_override=provider,
            limit_override=limit,
            markets_override=markets_override,
        )
    except ConfigLoadError as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    screener_enabled, screener_only = scan_screener._resolve_screener_flags(
        cfg, universe
    )
    if screener_only:
        logger.info("Screener-only universe selected; skipping watchlist loading.")
        loaded_tickers: list[str] = []
    else:
        resolved_watchlist_path = (
            watchlist_path or cfg.watchlist_path or "watchlist.txt"
        )
        if not os.path.exists(resolved_watchlist_path):
            logger.error(
                "Watchlist file '%s' does not exist; aborting for fail-closed safety.",
                resolved_watchlist_path,
            )
            return 1
        try:
            loaded_tickers = scan_screener._load_scan_tickers(
                cfg,
                watchlist_path,
                load_watchlist_fn=load_watchlist,
            )
        except ConfigLoadError as exc:
            logger.error("Watchlist loading failed: %s", exc)
            return 1
    filtered_tickers = _filter_tickers_by_markets(loaded_tickers, cfg.universe_markets)
    if len(filtered_tickers) != len(loaded_tickers):
        logger.info(
            "Watchlist filtered by universe markets=%s (%s -> %s tickers)",
            ",".join(cfg.universe_markets),
            len(loaded_tickers),
            len(filtered_tickers),
        )
    deduped_tickers = list(dict.fromkeys(filtered_tickers))
    if len(deduped_tickers) != len(filtered_tickers):
        logger.info(
            "Watchlist deduplicated after market filter (%s -> %s tickers)",
            len(filtered_tickers),
            len(deduped_tickers),
        )

    runtime = _ScanRuntime(
        cfg=cfg,
        logger=logger,
        tickers=deduped_tickers,
    )
    screener_limit_from_cli = screener_limit is not None
    effective_screener_limit: int = (
        cfg.screener_limit if screener_limit is None else screener_limit
    )

    _collect_scan_runtime(
        runtime,
        screener_enabled=screener_enabled,
        screener_only=screener_only,
        screener_limit=effective_screener_limit,
        screener_limit_from_cli=screener_limit_from_cli,
        evaluation_limit=cfg.screen_limit,
    )

    if not runtime.fatal_failure and not runtime.tickers:
        msg = "No tickers provided (watchlist empty or missing)"
        _record_system_issue(runtime, msg)
        runtime.logger.error(msg)
        runtime.fatal_failure = True

    if not runtime.fatal_failure:
        _evaluate_scan_runtime(runtime)
        _mark_missing_scan_market_data(runtime)

    out_path = _render_scan_report(runtime)
    runtime.logger.info("Buy report written to: %s", out_path)
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="buy",
            logger=runtime.logger,
        )
    except SupabaseStorageError as exc:
        _record_system_issue(runtime, f"Supabase upload failed: {exc}")
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
