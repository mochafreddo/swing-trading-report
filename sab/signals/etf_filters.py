from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_NAME_FIELDS = (
    "name",
    "hts_kor_isnm",
    "stck_hnm",
    "kor_sec_name",
    "security_name",
    "product_name",
    "long_name",
)

_FLAG_FIELDS = (
    "is_etf",
    "is_etn",
    "is_etp",
    "is_leveraged",
    "is_inverse",
    "etf_yn",
    "etn_yn",
    "etp_yn",
    "leveraged_yn",
    "inverse_yn",
)

_TYPE_FIELDS = (
    "security_type",
    "product_type",
    "instrument_type",
    "asset_type",
    "quote_type",
    "category",
    "kind",
    "symbol_type",
)

_TYPE_KEYWORDS = (
    "ETF",
    "ETN",
    "ETP",
    "EXCHANGE TRADED",
    "INDEX FUND",
    "LEVERAGED",
    "INVERSE",
)

_EXPLICIT_NAME_KEYWORDS = ("ETF", "ETN", "ETP", "레버리지", "인버스")
_LEVERAGE_NAME_KEYWORDS = ("ULTRA", "ULTRAPRO", "BULL", "BEAR", "LEVERAGED", "2X", "3X")
_ETF_ISSUER_KEYWORDS = ("ISHARES", "SPDR", "VANGUARD")
_ETF_ISSUER_WITH_CONTEXT = (
    "PROSHARES",
    "DIREXION",
    "WISDOMTREE",
    "VANECK",
    "GLOBAL X",
    "FIRST TRUST",
    "INVESCO",
)
_ETF_CONTEXT_KEYWORDS = (
    "FUND",
    "TRUST",
    "INDEX",
    "BOND",
    "SECTOR",
    "DIVIDEND",
    "INCOME",
    "TREASURY",
    "S&P",
    "NASDAQ",
    "MSCI",
    "RUSSELL",
    "SMALL CAP",
    "MID CAP",
    "LARGE CAP",
    "TOTAL STOCK",
    "MARKET",
    "WORLD",
    "SELECT",
)
_TRUTHY_TEXT = {"1", "Y", "YES", "TRUE", "T"}


def _as_upper_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text.upper() if text else ""


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return bool(text) and any(keyword in text for keyword in keywords)


def _is_truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return _as_upper_text(value) in _TRUTHY_TEXT


def _extract_name(meta: Mapping[str, Any]) -> str:
    for field in _NAME_FIELDS:
        text = _as_upper_text(meta.get(field))
        if text:
            return text
    return ""


def is_etf_or_leveraged(ticker: str, meta: Mapping[str, Any]) -> bool:
    """Heuristic to detect ETFs/ETNs and leveraged/inverse products.

    Uses available name fields from KIS rank/price APIs when possible and
    falls back to simple ticker pattern hints.
    """

    t = _as_upper_text(ticker)
    name = _extract_name(meta)

    # Direct ETF/ETN flags from providers (when available) should win first.
    if any(_is_truthy_flag(meta.get(field)) for field in _FLAG_FIELDS):
        return True

    # Product/security type fields can explicitly mark ETF/ETN assets.
    if any(
        _contains_any(_as_upper_text(meta.get(field)), _TYPE_KEYWORDS)
        for field in _TYPE_FIELDS
    ):
        return True

    # Name heuristics
    if _contains_any(name, _EXPLICIT_NAME_KEYWORDS + _LEVERAGE_NAME_KEYWORDS):
        return True
    if _contains_any(name, _ETF_ISSUER_KEYWORDS):
        return True
    if _contains_any(name, _ETF_ISSUER_WITH_CONTEXT) and _contains_any(
        name, _ETF_CONTEXT_KEYWORDS
    ):
        return True

    # Very coarse ticker-based hints as a fallback only.
    return _contains_any(t, ("2X", "3X"))


__all__ = ["is_etf_or_leveraged"]
