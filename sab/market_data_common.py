from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .data.cache import load_json, save_json
from .data.kis_client import KISClient, KISCredentials
from .data.pykrx_client import PykrxClient, PykrxClientError

type Candle = dict[str, Any]
type _LoadJsonFn = Callable[[str, str], list[Candle] | None]
type _SaveJsonFn = Callable[[str, str, list[Candle]], Any]


def infer_env_from_base_url(base_url: str) -> str:
    return "demo" if "vts" in base_url.lower() else "real"


@dataclass(frozen=True)
class MarketDataDependencies:
    KISCredentialsCls: type[KISCredentials]
    KISClientCls: type[KISClient]
    PykrxClientCls: type[PykrxClient]
    PykrxClientErrorCls: type[PykrxClientError]
    infer_env_from_base_fn: Callable[[str], str]
    load_json_fn: _LoadJsonFn
    save_json_fn: _SaveJsonFn


def build_market_data_dependencies(
    *,
    KISCredentialsCls: type[KISCredentials] | None = None,
    KISClientCls: type[KISClient] | None = None,
    PykrxClientCls: type[PykrxClient] | None = None,
    PykrxClientErrorCls: type[PykrxClientError] | None = None,
    infer_env_from_base_fn: Callable[[str], str] | None = None,
    load_json_fn: _LoadJsonFn | None = None,
    save_json_fn: _SaveJsonFn | None = None,
) -> MarketDataDependencies:
    return MarketDataDependencies(
        KISCredentialsCls=KISCredentials
        if KISCredentialsCls is None
        else KISCredentialsCls,
        KISClientCls=KISClient if KISClientCls is None else KISClientCls,
        PykrxClientCls=PykrxClient if PykrxClientCls is None else PykrxClientCls,
        PykrxClientErrorCls=(
            PykrxClientError if PykrxClientErrorCls is None else PykrxClientErrorCls
        ),
        infer_env_from_base_fn=(
            infer_env_from_base_url
            if infer_env_from_base_fn is None
            else infer_env_from_base_fn
        ),
        load_json_fn=load_json if load_json_fn is None else load_json_fn,
        save_json_fn=save_json if save_json_fn is None else save_json_fn,
    )


__all__ = [
    "Candle",
    "MarketDataDependencies",
    "build_market_data_dependencies",
    "infer_env_from_base_url",
]
