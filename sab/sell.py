from __future__ import annotations

import logging

from . import sell_evaluation, sell_runtime
from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.kis_client import KISClient, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .market_data_service import MarketDataPolicy, MarketDataService
from .report.sell_report import SellReportRow, write_sell_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .sell_types import _exchange_from_suffix, _SellRuntime, _split_symbol_and_suffix
from .signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid
from .signals.sell_rules import SellSettings, evaluate_sell_signals


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def _build_sell_runtime(cfg: Config, logger: logging.Logger) -> _SellRuntime:
    return sell_runtime._build_sell_runtime(cfg, logger)


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


def _build_sell_market_data_policy(
    runtime: _SellRuntime, *, target_bars: int
) -> MarketDataPolicy:
    return MarketDataPolicy(
        tickers=runtime.unique_tickers,
        target_bars=target_bars,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
        pykrx_error_attr="pykrx_init_error",
        pykrx_initialized_log_message="PyKRX client initialized",
        pykrx_client_kwargs_fn=lambda state: {"cache_dir": state.cfg.data_dir},
        init_unsupported_provider_message=(
            "Provider '{provider}' not supported for sell command"
        ),
        init_mark_fatal_on_unsupported=True,
        collect_unsupported_provider_message=None,
        collect_mark_fatal_on_unsupported=False,
    )


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
    policy = _build_sell_market_data_policy(runtime, target_bars=target_bars)
    market_data_service.initialize_provider(runtime, policy=policy)
    _resolve_sell_fx(runtime)
    market_data_service.collect_market_data(runtime, policy=policy)


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


def run_sell(*, provider: str | None) -> int:
    logger = logging.getLogger(__name__)
    try:
        cfg: Config = load_config(provider_override=provider)
    except (ConfigLoadError, HoldingsLoadError) as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    runtime = _build_sell_runtime(cfg, logger)
    _collect_sell_runtime(runtime, target_bars=max(cfg.min_history_bars, 200))
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
