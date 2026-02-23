from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .data.holiday_cache import HolidayEntry
from .data.kis_client import KISClient
from .data.pykrx_client import PykrxClient

US_SUFFIXES = {"US", "NASDAQ", "NASD", "NAS", "NYSE", "NYS", "AMEX", "AMS"}


def _format_ny_now_for_log(session_info: dict[str, object]) -> str:
    ny_now = session_info.get("ny_now")
    if isinstance(ny_now, dt.datetime):
        return ny_now.isoformat(timespec="seconds")
    if ny_now is None:
        return "-"
    return str(ny_now)


def _infer_currency(ticker: str) -> str:
    suffix = None
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[1].strip().upper()
    if suffix in US_SUFFIXES:
        return "USD"
    return "KRW"


def _infer_market(ticker: str) -> str:
    suffix = None
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[1].strip().upper()
    if suffix in US_SUFFIXES:
        return "US"
    return "KR"


def _filter_tickers_by_markets(
    tickers: list[str], universe_markets: list[str]
) -> list[str]:
    allowed_markets = {market.strip().upper() for market in universe_markets if market}
    if not allowed_markets:
        return []
    return [ticker for ticker in tickers if _infer_market(ticker) in allowed_markets]


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        val = float(value)
        if math.isnan(val):
            return None
        return val
    except (TypeError, ValueError):
        return None


def _split_overseas(ticker: str) -> tuple[str, str | None]:
    if "." not in ticker:
        return ticker, None
    base, suffix = ticker.rsplit(".", 1)
    return base.strip().upper(), suffix.strip().upper()


def _excd_from_suffix(suffix: str | None) -> str | None:
    if not suffix:
        return None
    mapping = {
        "US": "NAS",
        "NASDAQ": "NAS",
        "NASD": "NAS",
        "NAS": "NAS",
        "NYSE": "NYS",
        "NYS": "NYS",
        "AMEX": "AMS",
        "AMS": "AMS",
    }
    return mapping.get(suffix)


def _coerce_nday(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 1
    return 1


@dataclass
class _ScanRuntime:
    cfg: Config
    logger: logging.Logger
    tickers: list[str]
    failures: list[str] = field(default_factory=list)
    market_data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    ticker_data_source: dict[str, str] = field(default_factory=dict)
    cache_hint: str | None = None
    fatal_failure: bool = False
    kis_client: KISClient | None = None
    pykrx_client: PykrxClient | None = None
    pykrx_import_error: str | None = None
    pykrx_warning_added: bool = False
    screener_meta_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    screener_seeded: bool = False
    ticker_currency: dict[str, str] = field(default_factory=dict)
    fx_rate: float | None = None
    fx_meta_note: str | None = None
    us_holidays_cache: dict[str, HolidayEntry] = field(default_factory=dict)
    latest_dates: dict[str, str] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
