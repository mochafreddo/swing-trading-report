from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .data.kis_client import KISClient
from .data.pykrx_client import PykrxClient
from .tickers import (
    SUFFIX_TO_EXCHANGE,
    canonical_exchange_from_suffix,
    infer_currency_from_ticker,
    normalize_suffix,
    split_symbol_and_suffix,
)


def _normalize_suffix(suffix: str | None) -> str:
    return normalize_suffix(suffix)


US_SUFFIXES = {_normalize_suffix(s) for s in SUFFIX_TO_EXCHANGE}


def _split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    return split_symbol_and_suffix(ticker)


def _exchange_from_suffix(suffix: str | None) -> str | None:
    return canonical_exchange_from_suffix(suffix)


def _infer_currency_from_ticker(ticker: str) -> str:
    return infer_currency_from_ticker(ticker)


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
