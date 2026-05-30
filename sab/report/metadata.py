from __future__ import annotations

from collections.abc import Iterable, Mapping


def collect_row_tickers(rows: Iterable[Mapping[str, object]]) -> list[str]:
    seen: set[str] = set()
    tickers: list[str] = []
    for row in rows:
        ticker_raw = row.get("ticker")
        if ticker_raw is None:
            continue
        ticker = str(ticker_raw).strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def infer_market_from_currency(
    rows: Iterable[Mapping[str, object]],
) -> tuple[str, list[str] | None]:
    markets: set[str] = set()
    for row in rows:
        currency = str(row.get("currency") or "").strip().upper()
        if currency == "USD":
            markets.add("US")
        elif currency:
            markets.add("KR")
    if not markets:
        return "MIXED", None
    if len(markets) == 1:
        return next(iter(markets)), None
    return "MIXED", sorted(markets)
