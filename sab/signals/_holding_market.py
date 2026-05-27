from __future__ import annotations

from typing import Any

_US_EXCHANGE_CODES = {"US", "NASDAQ", "NASD", "NAS", "NYSE", "NYS", "AMEX", "AMS"}


def resolve_holding_market(*, ticker: str, holding: dict[str, Any]) -> str | None:
    exchange_raw = str(holding.get("exchange") or "").strip().upper()
    if exchange_raw in _US_EXCHANGE_CODES:
        return "US"

    currency_raw = (
        str(holding.get("entry_currency") or holding.get("currency") or "")
        .strip()
        .upper()
    )
    if currency_raw == "USD":
        return "US"
    if currency_raw == "KRW":
        return "KR"

    normalized_ticker = str(ticker or "").strip().upper()
    if "." in normalized_ticker:
        suffix = normalized_ticker.rsplit(".", 1)[1].strip().upper()
        if suffix in _US_EXCHANGE_CODES:
            return "US"

    return None
