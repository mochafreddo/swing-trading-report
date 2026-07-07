from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from . import sell_evaluation, sell_runtime
from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data_coverage_policy import summarize_missing_market_data
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsData, HoldingsLoadError, load_holdings
from .market_data_common import build_market_data_dependencies
from .market_data_service import SellMarketData
from .observability import current_run_id
from .report.artifact_update import append_report_issues
from .report.sell_report import SellReportRow, write_sell_report
from .report.supabase_storage import (
    SupabaseStorageError,
    maybe_upload_report_artifact,
    suppress_report_uploads,
)
from .sell_types import _exchange_from_suffix, _SellRuntime, _split_symbol_and_suffix
from .signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid
from .signals.sell_rules import SellSettings, evaluate_sell_signals

_INCOMPLETE_TAIL_BUFFER_BARS = 1


@dataclass(frozen=True)
class SellRunResult:
    exit_code: int
    report_path: str | None = None


def _build_sell_runtime(
    cfg: Config, logger: logging.Logger, *, holdings: HoldingsData
) -> _SellRuntime:
    return sell_runtime._build_sell_runtime(cfg, logger, holdings=holdings)


def _build_market_data_service() -> SellMarketData:
    return SellMarketData(deps=build_market_data_dependencies())


def _resolve_sell_fx(runtime: _SellRuntime) -> None:
    if not runtime.unique_tickers:
        return
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate(
        cfg=runtime.cfg,
        ticker_currency=runtime.ticker_currency,
        tickers=runtime.unique_tickers,
        kis_client=runtime.kis_client,
        logger=runtime.logger,
    )
    runtime.fx_rate = resolved_rate
    runtime.fx_note = resolved_note
    if fx_messages:
        runtime.failures.extend(fx_messages)


def _collect_sell_runtime(
    runtime: _SellRuntime,
    *,
    target_bars: int,
) -> None:
    market_data_service = _build_market_data_service()
    market_data_service.initialize_provider(runtime)
    _resolve_sell_fx(runtime)
    market_data_service.collect_market_data(runtime, target_bars=target_bars)


def _evaluate_sell_runtime(runtime: _SellRuntime) -> list[SellReportRow]:
    return sell_evaluation._evaluate_holdings(
        runtime,
        SellSettingsCls=SellSettings,
        HybridSellSettingsCls=HybridSellSettings,
        evaluate_sell_signals_fn=evaluate_sell_signals,
        evaluate_sell_signals_hybrid_fn=evaluate_sell_signals_hybrid,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
    )


def _render_sell_report(
    runtime: _SellRuntime,
    results: list[SellReportRow],
    *,
    artifact_date: str | None = None,
) -> str:
    return sell_evaluation._write_sell_report(
        runtime,
        results,
        write_sell_report_fn=write_sell_report,
        artifact_date=artifact_date,
    )


def _resolve_sell_target_bars(runtime: _SellRuntime) -> int:
    base_target_bars = max(runtime.cfg.min_history_bars, 200)
    oldest_entry_date: dt.date | None = None

    for holding in runtime.holdings:
        raw_entry_date = getattr(holding, "entry_date", None)
        if not raw_entry_date:
            continue
        try:
            entry_date = dt.date.fromisoformat(str(raw_entry_date))
        except ValueError:
            continue
        if oldest_entry_date is None or entry_date < oldest_entry_date:
            oldest_entry_date = entry_date

    target_bars = base_target_bars
    today = dt.date.today()
    if oldest_entry_date is not None and oldest_entry_date < today:
        # Calendar days -> trading sessions approximation with conservative buffer.
        holding_days = (today - oldest_entry_date).days
        estimated_sessions = int(holding_days * (5 / 7)) + 30
        target_bars = max(base_target_bars, min(estimated_sessions, 4000))
    return target_bars + _INCOMPLETE_TAIL_BUFFER_BARS


def _mark_missing_sell_market_data(runtime: _SellRuntime) -> None:
    summary = summarize_missing_market_data(
        requested=runtime.unique_tickers,
        available=runtime.market_data,
        subject="holdings",
    )
    if summary is None:
        return

    runtime.failures.append(summary.message)
    if summary.fatal:
        runtime.fatal_failure = True
        runtime.logger.error("%s", summary.message)
        return
    runtime.logger.warning("%s", summary.message)


def _resolve_sell_holdings(cfg: Config) -> HoldingsData:
    if cfg.holdings.holdings:
        return cfg.holdings
    resolved_holdings_path = cfg.holdings_path or "holdings.yaml"
    return load_holdings(resolved_holdings_path)


def run_sell(
    *,
    provider: str | None,
    holdings_path: str | None = None,
    report_path_callback: Callable[[str], None] | None = None,
    report_date: str | None = None,
) -> int:
    logger = logging.getLogger(__name__)
    run_id = current_run_id("sell")
    logger.info(
        "Sell run started",
        extra={
            "event": "sell_started",
            "operation": "sell",
            "run_id": run_id,
            "provider": provider or "config",
            "holdings_path": holdings_path or "config",
        },
    )
    try:
        cfg: Config = load_config(
            provider_override=provider,
            holdings_override=holdings_path,
        )
    except ConfigLoadError as exc:
        logger.error(
            "Configuration loading failed: %s",
            exc,
            extra={
                "event": "sell_failed",
                "operation": "sell",
                "run_id": run_id,
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        return 1

    try:
        holdings_data = _resolve_sell_holdings(cfg)
    except HoldingsLoadError as exc:
        logger.error(
            "Holdings loading failed: %s",
            exc,
            extra={
                "event": "sell_failed",
                "operation": "sell",
                "run_id": run_id,
                "status": "failed",
                "error_type": type(exc).__name__,
            },
        )
        return 1

    runtime = _build_sell_runtime(cfg, logger, holdings=holdings_data)
    _collect_sell_runtime(runtime, target_bars=_resolve_sell_target_bars(runtime))
    _mark_missing_sell_market_data(runtime)
    results = _evaluate_sell_runtime(runtime)

    out_path = _render_sell_report(runtime, results, artifact_date=report_date)
    if report_path_callback is not None:
        report_path_callback(out_path)
    logger.info(
        "Sell report written to: %s",
        out_path,
        extra={
            "event": "sell_report_written",
            "operation": "sell",
            "run_id": run_id,
            "report_path": out_path,
            "report_type": "sell",
            "status": "success",
            "ticker_count": len(runtime.unique_tickers),
        },
    )
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="sell",
            logger=logger,
        )
    except SupabaseStorageError as exc:
        runtime.failures.append(f"Supabase upload failed: {exc}")
        runtime.fatal_failure = True
        try:
            append_report_issues(out_path, issues=runtime.failures)
        except (OSError, ValueError, json.JSONDecodeError) as update_exc:
            logger.warning(
                "Failed to update sell report after upload failure: %s",
                update_exc,
                extra={
                    "event": "sell_upload_failure_report_update_failed",
                    "operation": "sell",
                    "run_id": run_id,
                    "report_path": out_path,
                    "report_type": "sell",
                    "status": "failed",
                    "error_type": type(update_exc).__name__,
                },
            )
        logger.error(
            "Supabase report upload failed: %s",
            exc,
            extra={
                "event": "sell_upload_failed",
                "operation": "sell",
                "run_id": run_id,
                "dependency": "supabase",
                "report_path": out_path,
                "report_type": "sell",
                "status": "failed",
                "error_type": type(exc).__name__,
                "retryable": True,
            },
        )
    else:
        if uploaded_key:
            logger.info(
                "Sell report uploaded to Supabase: %s",
                uploaded_key,
                extra={
                    "event": "sell_upload_completed",
                    "operation": "sell",
                    "run_id": run_id,
                    "dependency": "supabase",
                    "report_path": out_path,
                    "storage_key": uploaded_key,
                    "report_type": "sell",
                    "status": "success",
                },
            )

    if runtime.fatal_failure:
        logger.error(
            "Sell evaluation completed with fatal errors. See report for details.",
            extra={
                "event": "sell_completed",
                "operation": "sell",
                "run_id": run_id,
                "report_path": out_path,
                "status": "failed",
                "failure_count": len(runtime.failures),
            },
        )
        return 1
    if runtime.failures:
        logger.warning(
            "Sell evaluation completed with warnings. See report for details.",
            extra={
                "event": "sell_completed",
                "operation": "sell",
                "run_id": run_id,
                "report_path": out_path,
                "status": "warning",
                "failure_count": len(runtime.failures),
            },
        )
        return 0
    logger.info(
        "Sell evaluation completed successfully.",
        extra={
            "event": "sell_completed",
            "operation": "sell",
            "run_id": run_id,
            "report_path": out_path,
            "status": "success",
            "failure_count": 0,
        },
    )
    return 0


def run_sell_with_result(
    *,
    provider: str | None,
    holdings_path: str | None = None,
    suppress_upload: bool = False,
    report_date: str | None = None,
) -> SellRunResult:
    report_paths: list[str] = []
    if suppress_upload:
        with suppress_report_uploads():
            exit_code = run_sell(
                provider=provider,
                holdings_path=holdings_path,
                report_path_callback=report_paths.append,
                report_date=report_date,
            )
    else:
        exit_code = run_sell(
            provider=provider,
            holdings_path=holdings_path,
            report_path_callback=report_paths.append,
            report_date=report_date,
        )
    return SellRunResult(
        exit_code=exit_code,
        report_path=report_paths[-1] if report_paths else None,
    )


__all__ = ["SellRunResult", "run_sell", "run_sell_with_result"]
