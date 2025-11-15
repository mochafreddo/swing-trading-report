from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from ..data.kis_client import KISClient


@dataclass
class ScreenRequest:
    limit: int
    metric: str  # 'volume' | 'market_cap' | 'value'
    exchange: str | None = None  # NAS/NYS/AMS or None for default rotation


@dataclass
class ScreenResult:
    tickers: list[str]
    metadata: dict[str, Any]


class KISOverseasScreener:
    """KIS overseas rank screener (volume/market cap/value).

    Note: Endpoint/fields may vary by KIS environment. If runtime errors occur,
    adjust the endpoint paths and parsing accordingly.
    """

    def __init__(self, client: KISClient) -> None:
        self._client = client

    def screen(self, request: ScreenRequest) -> ScreenResult:
        metric = (request.metric or "volume").lower()
        exchanges = self._resolve_exchanges(request.exchange)
        tickers: list[str] = []
        by_ticker: dict[str, Any] = {}
        for exch in exchanges:
            remaining = request.limit - len(tickers)
            if remaining <= 0:
                break
            rows = self._fetch_rank(metric, exch, remaining)
            for row in rows:
                sym = self._symbol_from_row(row)
                if not sym:
                    continue
                ticker = sym if "." in sym else f"{sym}.{exch}"
                if ticker in tickers:
                    continue
                tickers.append(ticker)
                enriched = dict(row)
                enriched.setdefault("exchange", exch)
                by_ticker[ticker] = enriched
                if len(tickers) >= request.limit:
                    break

        return ScreenResult(
            tickers=tickers,
            metadata={
                "source": "kis_overseas_rank",
                "metric": metric,
                "exchanges": exchanges,
                "generated_at": dt.datetime.now().isoformat(),
                "by_ticker": by_ticker,
            },
        )

    def _resolve_exchanges(self, exchange: str | None) -> list[str]:
        if exchange:
            return [self._normalize_exchange(exchange)]
        return ["NAS", "NYS", "AMS"]

    @staticmethod
    def _normalize_exchange(exchange: str) -> str:
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
        code = (exchange or "NAS").strip().upper()
        return mapping.get(code, code)

    def _fetch_rank(self, metric: str, exchange: str, limit: int) -> list[dict[str, Any]]:
        if metric in {"market_cap", "marketcap"}:
            return self._client.overseas_market_cap_rank(exchange=exchange, limit=limit)
        if metric in {"value", "amount", "trade_value"}:
            return self._client.overseas_trade_value_rank(exchange=exchange, limit=limit)
        # default to volume
        return self._client.overseas_trade_volume_rank(exchange=exchange, limit=limit)

    @staticmethod
    def _symbol_from_row(row: dict[str, Any]) -> str:
        sym = (
            row.get("SYMB")
            or row.get("symb")
            or row.get("rsym")
            or row.get("symbol")
            or row.get("ticker")
            or ""
        )
        if not isinstance(sym, str):
            return ""
        return sym.strip().upper()


__all__ = ["KISOverseasScreener", "ScreenRequest", "ScreenResult"]
