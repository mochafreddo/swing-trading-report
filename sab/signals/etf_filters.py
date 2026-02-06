from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def is_etf_or_leveraged(ticker: str, meta: Mapping[str, Any]) -> bool:
    """Heuristic to detect ETFs/ETNs and leveraged/inverse products.

    Uses available name fields from KIS rank/price APIs when possible and
    falls back to simple ticker pattern hints.
    """

    t = (ticker or "").upper()

    raw_name = (
        meta.get("name")
        or meta.get("hts_kor_isnm")
        or meta.get("stck_hnm")
        or meta.get("kor_sec_name")
        or ""
    )
    name = str(raw_name).upper()

    # Core ETF/ETN / KR leveraged keywords.
    base_keywords = ["ETF", "ETN", "레버리지", "인버스"]

    # Additional leveraged/inverse hints often present in product names.
    lev_keywords = ["ULTRA", "ULTRAPRO", "BULL", "BEAR", "LEVERAGED", "2X", "3X"]

    if any(k in name for k in base_keywords + lev_keywords):
        return True

    # Very coarse ticker-based hints as a fallback only.
    ticker_hints = ["2X", "3X"]
    return bool(any(h in t for h in ticker_hints))


__all__ = ["is_etf_or_leveraged"]
