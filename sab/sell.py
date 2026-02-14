from __future__ import annotations

import logging

from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.kis_client import KISClient, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .report.sell_report import SellReportRow, write_sell_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .sell_evaluation import _build_sell_mode_note as _build_sell_mode_note_impl
from .sell_evaluation import _evaluate_holdings as _evaluate_holdings_impl
from .sell_evaluation import _write_sell_report as _write_sell_report_impl
from .sell_market_data import _collect_market_data as _collect_market_data_impl
from .sell_market_data import (
    _collect_market_data_from_kis as _collect_market_data_from_kis_impl,
)
from .sell_market_data import (
    _collect_market_data_from_pykrx as _collect_market_data_from_pykrx_impl,
)
from .sell_market_data import _ensure_pykrx_client as _ensure_pykrx_client_impl
from .sell_market_data import _initialize_provider as _initialize_provider_impl
from .sell_market_data import _resolve_sell_fx as _resolve_sell_fx_impl
from .sell_runtime import _build_sell_runtime as _build_sell_runtime_impl
from .sell_types import (
    _exchange_from_suffix,
    _SellRuntime,
    _split_symbol_and_suffix,
)
from .sell_types import (
    _infer_currency_from_ticker as _infer_currency_from_ticker_impl,
)
from .signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid
from .signals.sell_rules import SellSettings, evaluate_sell_signals


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


def _infer_currency_from_ticker(ticker: str) -> str:
    return _infer_currency_from_ticker_impl(ticker)


def _build_sell_runtime(cfg: Config, logger: logging.Logger) -> _SellRuntime:
    return _build_sell_runtime_impl(cfg, logger)


def _ensure_pykrx_client(runtime: _SellRuntime) -> PykrxClient | None:
    return _ensure_pykrx_client_impl(runtime, PykrxClientCls=PykrxClient)


def _initialize_provider(runtime: _SellRuntime) -> None:
    _initialize_provider_impl(
        runtime,
        KISCredentialsCls=KISCredentials,
        KISClientCls=KISClient,
        ensure_pykrx_client_fn=_ensure_pykrx_client,
        infer_env_from_base_fn=_infer_env_from_base,
    )


def _resolve_sell_fx(runtime: _SellRuntime) -> None:
    _resolve_sell_fx_impl(runtime, resolve_fx_rate_fn=resolve_fx_rate)


def _collect_market_data_from_kis(runtime: _SellRuntime, *, target_bars: int) -> None:
    _collect_market_data_from_kis_impl(
        runtime,
        target_bars=target_bars,
        load_json_fn=load_json,
        save_json_fn=save_json,
        ensure_pykrx_client_fn=_ensure_pykrx_client,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
    )


def _collect_market_data_from_pykrx(runtime: _SellRuntime, *, target_bars: int) -> None:
    _collect_market_data_from_pykrx_impl(
        runtime,
        target_bars=target_bars,
        PykrxClientErrorCls=PykrxClientError,
    )


def _collect_market_data(runtime: _SellRuntime, *, target_bars: int) -> None:
    _collect_market_data_impl(
        runtime,
        target_bars=target_bars,
        collect_market_data_from_kis_fn=_collect_market_data_from_kis,
        collect_market_data_from_pykrx_fn=_collect_market_data_from_pykrx,
    )


def _evaluate_holdings(runtime: _SellRuntime) -> list[SellReportRow]:
    return _evaluate_holdings_impl(
        runtime,
        SellSettingsCls=SellSettings,
        HybridSellSettingsCls=HybridSellSettings,
        evaluate_sell_signals_fn=evaluate_sell_signals,
        evaluate_sell_signals_hybrid_fn=evaluate_sell_signals_hybrid,
        SellReportRowCls=SellReportRow,
        split_symbol_and_suffix_fn=_split_symbol_and_suffix,
        exchange_from_suffix_fn=_exchange_from_suffix,
    )


def _build_sell_mode_note(cfg: Config) -> str | None:
    return _build_sell_mode_note_impl(cfg)


def _write_sell_report(runtime: _SellRuntime, results: list[SellReportRow]) -> str:
    return _write_sell_report_impl(
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
    _initialize_provider(runtime)
    _resolve_sell_fx(runtime)
    _collect_market_data(runtime, target_bars=max(cfg.min_history_bars, 200))
    results = _evaluate_holdings(runtime)

    out_path = _write_sell_report(runtime, results)
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
