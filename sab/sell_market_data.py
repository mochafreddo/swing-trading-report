from __future__ import annotations

from typing import Any

from .market_data_pipeline import collect_market_data as _collect_market_data_shared
from .market_data_pipeline import (
    collect_market_data_from_kis as _collect_market_data_from_kis_shared,
)
from .market_data_pipeline import (
    collect_market_data_from_pykrx as _collect_market_data_from_pykrx_shared,
)
from .market_data_pipeline import ensure_pykrx_client as _ensure_pykrx_client_shared
from .market_data_pipeline import initialize_provider as _initialize_provider_shared
from .sell_types import _SellRuntime


def _ensure_pykrx_client(runtime: _SellRuntime, *, PykrxClientCls: Any) -> Any | None:
    return _ensure_pykrx_client_shared(
        runtime,
        PykrxClientCls=PykrxClientCls,
        get_pykrx_error_fn=lambda state: state.pykrx_init_error,
        set_pykrx_error_fn=lambda state, message: setattr(
            state, "pykrx_init_error", message
        ),
        pykrx_client_kwargs_fn=lambda state: {"cache_dir": state.cfg.data_dir},
        initialized_log_message="PyKRX client initialized",
    )


def _initialize_provider(
    runtime: _SellRuntime,
    *,
    KISCredentialsCls: Any,
    KISClientCls: Any,
    ensure_pykrx_client_fn: Any,
    infer_env_from_base_fn: Any,
) -> None:
    _initialize_provider_shared(
        runtime,
        KISCredentialsCls=KISCredentialsCls,
        KISClientCls=KISClientCls,
        ensure_pykrx_client_fn=ensure_pykrx_client_fn,
        infer_env_from_base_fn=infer_env_from_base_fn,
        unsupported_provider_message="Provider '{provider}' not supported for sell command",
        mark_fatal_on_unsupported=True,
    )


def _resolve_sell_fx(runtime: _SellRuntime, *, resolve_fx_rate_fn: Any) -> None:
    if not runtime.unique_tickers:
        return
    resolved_rate, resolved_note, fx_messages = resolve_fx_rate_fn(
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


def _collect_market_data_from_kis(
    runtime: _SellRuntime,
    *,
    target_bars: int,
    load_json_fn: Any,
    save_json_fn: Any,
    ensure_pykrx_client_fn: Any,
    split_symbol_and_suffix_fn: Any,
    exchange_from_suffix_fn: Any,
) -> None:
    _collect_market_data_from_kis_shared(
        runtime,
        tickers=runtime.unique_tickers,
        target_bars=target_bars,
        load_json_fn=load_json_fn,
        save_json_fn=save_json_fn,
        ensure_pykrx_client_fn=ensure_pykrx_client_fn,
        split_symbol_and_suffix_fn=split_symbol_and_suffix_fn,
        exchange_from_suffix_fn=exchange_from_suffix_fn,
        get_pykrx_error_fn=lambda state: state.pykrx_init_error,
    )


def _collect_market_data_from_pykrx(
    runtime: _SellRuntime,
    *,
    target_bars: int,
    PykrxClientErrorCls: Any,
) -> None:
    _collect_market_data_from_pykrx_shared(
        runtime,
        tickers=runtime.unique_tickers,
        target_bars=target_bars,
        PykrxClientErrorCls=PykrxClientErrorCls,
    )


def _collect_market_data(
    runtime: _SellRuntime,
    *,
    target_bars: int,
    collect_market_data_from_kis_fn: Any,
    collect_market_data_from_pykrx_fn: Any,
) -> None:
    _collect_market_data_shared(
        runtime,
        tickers=runtime.unique_tickers,
        collect_market_data_from_kis_fn=lambda state: collect_market_data_from_kis_fn(
            state, target_bars=target_bars
        ),
        collect_market_data_from_pykrx_fn=lambda state: (
            collect_market_data_from_pykrx_fn(state, target_bars=target_bars)
        ),
        unsupported_provider_message=None,
        mark_fatal_on_unsupported=False,
    )
