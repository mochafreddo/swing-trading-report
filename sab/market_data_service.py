from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from . import market_data_pipeline

type _LegacyCacheKeysFn = Callable[[str, str, str | None], list[str]]
type _OnCandlesAppliedFn = Callable[[Any, str, list[dict[str, Any]]], None]
type _BeforeKisCollectionFn = Callable[[Any], None]
type _PykrxClientKwargsFn = Callable[[Any], dict[str, Any]]


def scan_legacy_cache_keys(
    ticker: str, base_symbol: str, exchange: str | None
) -> list[str]:
    legacy_key = f"candles_{ticker}"
    canonical_key = (
        f"candles_overseas_{exchange}_{base_symbol}"
        if exchange
        else f"candles_{base_symbol}"
    )
    if legacy_key == canonical_key:
        return []
    return [legacy_key]


@dataclass(frozen=True)
class MarketDataPolicy:
    tickers: Sequence[str]
    target_bars: int
    split_symbol_and_suffix_fn: Callable[[str], tuple[str, str | None]]
    exchange_from_suffix_fn: Callable[[str | None], str | None]
    pykrx_error_attr: str
    pykrx_initialized_log_message: str
    pykrx_client_kwargs_fn: _PykrxClientKwargsFn | None = None
    init_unsupported_provider_message: str | None = None
    init_mark_fatal_on_unsupported: bool = False
    collect_unsupported_provider_message: str | None = (
        "Provider '{provider}' not yet implemented"
    )
    collect_mark_fatal_on_unsupported: bool = True
    legacy_cache_keys_fn: _LegacyCacheKeysFn | None = None
    on_candles_applied_fn: _OnCandlesAppliedFn | None = None
    before_kis_collection_fn: _BeforeKisCollectionFn | None = None


class MarketDataService:
    def __init__(
        self,
        *,
        KISCredentialsCls: Any,
        KISClientCls: Any,
        PykrxClientCls: Any,
        PykrxClientErrorCls: Any,
        infer_env_from_base_fn: Callable[[str], str],
        load_json_fn: Callable[[str, str], Any],
        save_json_fn: Callable[[str, str, Any], Any],
    ) -> None:
        self._KISCredentialsCls = KISCredentialsCls
        self._KISClientCls = KISClientCls
        self._PykrxClientCls = PykrxClientCls
        self._PykrxClientErrorCls = PykrxClientErrorCls
        self._infer_env_from_base_fn = infer_env_from_base_fn
        self._load_json_fn = load_json_fn
        self._save_json_fn = save_json_fn

    def initialize_provider(self, runtime: Any, *, policy: MarketDataPolicy) -> None:
        market_data_pipeline.initialize_provider(
            runtime,
            KISCredentialsCls=self._KISCredentialsCls,
            KISClientCls=self._KISClientCls,
            ensure_pykrx_client_fn=lambda state: self._ensure_pykrx_client(
                state, policy=policy
            ),
            infer_env_from_base_fn=self._infer_env_from_base_fn,
            unsupported_provider_message=policy.init_unsupported_provider_message,
            mark_fatal_on_unsupported=policy.init_mark_fatal_on_unsupported,
        )

    def collect_market_data(self, runtime: Any, *, policy: MarketDataPolicy) -> None:
        tickers = list(policy.tickers)
        market_data_pipeline.collect_market_data(
            runtime,
            tickers=tickers,
            collect_market_data_from_kis_fn=lambda state: self._collect_from_kis(
                state,
                policy=policy,
                tickers=tickers,
            ),
            collect_market_data_from_pykrx_fn=lambda state: self._collect_from_pykrx(
                state,
                policy=policy,
                tickers=tickers,
            ),
            unsupported_provider_message=policy.collect_unsupported_provider_message,
            mark_fatal_on_unsupported=policy.collect_mark_fatal_on_unsupported,
        )

    def _ensure_pykrx_client(
        self, runtime: Any, *, policy: MarketDataPolicy
    ) -> Any | None:
        return market_data_pipeline.ensure_pykrx_client(
            runtime,
            PykrxClientCls=self._PykrxClientCls,
            get_pykrx_error_fn=lambda state: self._get_pykrx_error(
                state, policy=policy
            ),
            set_pykrx_error_fn=lambda state, message: self._set_pykrx_error(
                state, policy=policy, message=message
            ),
            pykrx_client_kwargs_fn=policy.pykrx_client_kwargs_fn,
            initialized_log_message=policy.pykrx_initialized_log_message,
        )

    def _collect_from_kis(
        self,
        runtime: Any,
        *,
        policy: MarketDataPolicy,
        tickers: list[str],
    ) -> None:
        if policy.before_kis_collection_fn is not None:
            policy.before_kis_collection_fn(runtime)
        market_data_pipeline.collect_market_data_from_kis(
            runtime,
            tickers=tickers,
            target_bars=policy.target_bars,
            load_json_fn=self._load_json_fn,
            save_json_fn=self._save_json_fn,
            ensure_pykrx_client_fn=lambda state: self._ensure_pykrx_client(
                state,
                policy=policy,
            ),
            split_symbol_and_suffix_fn=policy.split_symbol_and_suffix_fn,
            exchange_from_suffix_fn=policy.exchange_from_suffix_fn,
            get_pykrx_error_fn=lambda state: self._get_pykrx_error(
                state, policy=policy
            ),
            legacy_cache_keys_fn=policy.legacy_cache_keys_fn,
            on_candles_applied_fn=policy.on_candles_applied_fn,
        )

    def _collect_from_pykrx(
        self,
        runtime: Any,
        *,
        policy: MarketDataPolicy,
        tickers: list[str],
    ) -> None:
        market_data_pipeline.collect_market_data_from_pykrx(
            runtime,
            tickers=tickers,
            target_bars=policy.target_bars,
            PykrxClientErrorCls=self._PykrxClientErrorCls,
            on_candles_applied_fn=policy.on_candles_applied_fn,
        )

    def _get_pykrx_error(self, runtime: Any, *, policy: MarketDataPolicy) -> str | None:
        value = getattr(runtime, policy.pykrx_error_attr, None)
        if value is None:
            return None
        return str(value)

    def _set_pykrx_error(
        self,
        runtime: Any,
        *,
        policy: MarketDataPolicy,
        message: str,
    ) -> None:
        setattr(runtime, policy.pykrx_error_attr, message)


__all__ = [
    "MarketDataPolicy",
    "MarketDataService",
    "scan_legacy_cache_keys",
]
