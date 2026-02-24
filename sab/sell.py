from __future__ import annotations

import datetime as dt
import logging

from . import sell_evaluation, sell_runtime
from .config import Config, load_config
from .config_loader import ConfigLoadError
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .market_data_common import build_market_data_dependencies
from .market_data_service import SellMarketData
from .report.sell_report import SellReportRow, write_sell_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .sell_types import _exchange_from_suffix, _SellRuntime, _split_symbol_and_suffix
from .signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid
from .signals.sell_rules import SellSettings, evaluate_sell_signals


def _build_sell_runtime(cfg: Config, logger: logging.Logger) -> _SellRuntime:
    return sell_runtime._build_sell_runtime(cfg, logger)


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


def _render_sell_report(runtime: _SellRuntime, results: list[SellReportRow]) -> str:
    return sell_evaluation._write_sell_report(
        runtime,
        results,
        write_sell_report_fn=write_sell_report,
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

    if oldest_entry_date is None:
        return base_target_bars

    today = dt.date.today()
    if oldest_entry_date >= today:
        return base_target_bars

    # Calendar days -> trading sessions approximation with conservative buffer.
    holding_days = (today - oldest_entry_date).days
    estimated_sessions = int(holding_days * (5 / 7)) + 30
    return max(base_target_bars, min(estimated_sessions, 4000))


def run_sell(*, provider: str | None, holdings_path: str | None = None) -> int:
    logger = logging.getLogger(__name__)
    try:
        cfg: Config = load_config(
            provider_override=provider,
            holdings_override=holdings_path,
        )
    except (ConfigLoadError, HoldingsLoadError) as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    runtime = _build_sell_runtime(cfg, logger)
    _collect_sell_runtime(runtime, target_bars=_resolve_sell_target_bars(runtime))
    if runtime.unique_tickers and not runtime.market_data:
        runtime.fatal_failure = True
        runtime.failures.append("Failed to retrieve market data for holdings")
        logger.error("Failed to retrieve market data for requested holdings")
    results = _evaluate_sell_runtime(runtime)

    out_path = _render_sell_report(runtime, results)
    logger.info("Sell report written to: %s", out_path)
    try:
        uploaded_key = maybe_upload_report_artifact(
            artifact_path=out_path,
            run_type="sell",
            logger=logger,
        )
    except SupabaseStorageError as exc:
        runtime.failures.append(f"Supabase upload failed: {exc}")
        runtime.fatal_failure = True
        logger.error("Supabase report upload failed: %s", exc)
    else:
        if uploaded_key:
            logger.info("Sell report uploaded to Supabase: %s", uploaded_key)

    if runtime.fatal_failure:
        logger.error(
            "Sell evaluation completed with fatal errors. See report for details."
        )
        return 1
    if runtime.failures:
        logger.warning(
            "Sell evaluation completed with warnings. See report for details."
        )
    return 0


__all__ = ["run_sell"]
