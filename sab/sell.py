from __future__ import annotations

import logging

from . import sell_evaluation, sell_market_data, sell_runtime
from .config import Config, load_config
from .config_loader import ConfigLoadError
from .data.cache import load_json, save_json
from .data.kis_client import KISClient, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError
from .fx import resolve_fx_rate
from .holdings_loader import HoldingsLoadError
from .report.sell_report import SellReportRow, write_sell_report
from .report.supabase_storage import SupabaseStorageError, maybe_upload_report_artifact
from .sell_types import _exchange_from_suffix, _SellRuntime, _split_symbol_and_suffix
from .signals.hybrid_sell import HybridSellSettings, evaluate_sell_signals_hybrid
from .signals.sell_rules import SellSettings, evaluate_sell_signals


def _infer_env_from_base(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


class SellService:
    @staticmethod
    def build_runtime(cfg: Config, logger: logging.Logger) -> _SellRuntime:
        return sell_runtime._build_sell_runtime(cfg, logger)

    @staticmethod
    def _ensure_pykrx_client(runtime: _SellRuntime) -> PykrxClient | None:
        return sell_market_data._ensure_pykrx_client(
            runtime,
            PykrxClientCls=PykrxClient,
        )

    def collect(self, runtime: _SellRuntime, *, target_bars: int) -> None:
        sell_market_data._initialize_provider(
            runtime,
            KISCredentialsCls=KISCredentials,
            KISClientCls=KISClient,
            ensure_pykrx_client_fn=self._ensure_pykrx_client,
            infer_env_from_base_fn=_infer_env_from_base,
        )
        sell_market_data._resolve_sell_fx(runtime, resolve_fx_rate_fn=resolve_fx_rate)
        sell_market_data._collect_market_data(
            runtime,
            target_bars=target_bars,
            collect_market_data_from_kis_fn=self._collect_market_data_from_kis,
            collect_market_data_from_pykrx_fn=self._collect_market_data_from_pykrx,
        )

    def _collect_market_data_from_kis(
        self,
        runtime: _SellRuntime,
        *,
        target_bars: int,
    ) -> None:
        sell_market_data._collect_market_data_from_kis(
            runtime,
            target_bars=target_bars,
            load_json_fn=load_json,
            save_json_fn=save_json,
            ensure_pykrx_client_fn=self._ensure_pykrx_client,
            split_symbol_and_suffix_fn=_split_symbol_and_suffix,
            exchange_from_suffix_fn=_exchange_from_suffix,
        )

    @staticmethod
    def _collect_market_data_from_pykrx(
        runtime: _SellRuntime,
        *,
        target_bars: int,
    ) -> None:
        sell_market_data._collect_market_data_from_pykrx(
            runtime,
            target_bars=target_bars,
            PykrxClientErrorCls=PykrxClientError,
        )

    @staticmethod
    def evaluate(runtime: _SellRuntime) -> list[SellReportRow]:
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

    @staticmethod
    def render(runtime: _SellRuntime, results: list[SellReportRow]) -> str:
        return sell_evaluation._write_sell_report(
            runtime,
            results,
            write_sell_report_fn=write_sell_report,
        )


def run_sell(*, provider: str | None) -> int:
    logger = logging.getLogger(__name__)
    service = SellService()
    try:
        cfg: Config = load_config(provider_override=provider)
    except (ConfigLoadError, HoldingsLoadError) as exc:
        logger.error("Configuration loading failed: %s", exc)
        return 1

    runtime = service.build_runtime(cfg, logger)
    service.collect(runtime, target_bars=max(cfg.min_history_bars, 200))
    results = service.evaluate(runtime)

    out_path = service.render(runtime, results)
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
