from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .data.kis_client import KISClient
from .data.pykrx_client import PykrxClient
from .fx import SUFFIX_TO_EXCD


def _normalize_suffix(suffix: str | None) -> str:
    if not suffix:
        return ""
    return "".join(ch for ch in suffix.upper() if ch.isalnum())


US_SUFFIXES = {_normalize_suffix(s) for s in SUFFIX_TO_EXCD}


def _split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    if "." not in ticker:
        return ticker.strip().upper(), None
    base, suffix = ticker.rsplit(".", 1)
    return base.strip().upper(), suffix.strip().upper()


def _exchange_from_suffix(suffix: str | None) -> str | None:
    if not suffix:
        return None
    norm = _normalize_suffix(suffix)
    for key, value in SUFFIX_TO_EXCD.items():
        if _normalize_suffix(key) == norm:
            return value
    return SUFFIX_TO_EXCD.get(norm)


def _infer_currency_from_ticker(ticker: str) -> str:
    _, suffix = _split_symbol_and_suffix(ticker)
    norm = _normalize_suffix(suffix)
    if norm in US_SUFFIXES:
        return "USD"
    return "KRW"


@dataclass
class _SellRuntime:
    cfg: Config
    logger: logging.Logger
    holdings: list[Any]
    unique_tickers: list[str]
    ticker_currency: dict[str, str]
    failures: list[str] = field(default_factory=list)
    market_data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ticker_data_source: dict[str, str] = field(default_factory=dict)
    cache_hint: str | None = None
    fatal_failure: bool = False
    kis_client: KISClient | None = None
    pykrx_client: PykrxClient | None = None
    pykrx_init_error: str | None = None
    pykrx_warning_added: bool = field(default=False)
    missing_logged: set[str] = field(default_factory=set)
    fx_rate: float | None = None
    fx_note: str | None = None
