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
    nday: int = 0  # 0 = today, 1 = previous session, etc.
    fallback_ndays: list[int] | None = None  # optional retry list


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
        ndays: list[int] = []
        if request.nday is not None:
            try:
                ndays.append(max(0, int(request.nday)))
            except (TypeError, ValueError):
                ndays.append(0)
        for nd in request.fallback_ndays or []:
            try:
                candidate = max(0, int(nd))
            except (TypeError, ValueError):
                continue
            if candidate not in ndays:
                ndays.append(candidate)
        if not ndays:
            ndays = [0]

        nday_used: int | None = None
        tried_ndays: list[int] = []

        for nd in ndays:
            tried_ndays.append(nd)
            for exch in exchanges:
                remaining = request.limit - len(tickers)
                if remaining <= 0:
                    break
                rows = self._fetch_rank(metric, exch, remaining, nday=nd)
                if not rows:
                    continue
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
                    if nday_used is None:
                        nday_used = nd
                    if len(tickers) >= request.limit:
                        break
                if tickers:
                    # Prefer a single session's ranks; stop once we have results.
                    break
            if tickers:
                break

        return ScreenResult(
            tickers=tickers,
            metadata={
                "source": "kis_overseas_rank",
                "metric": metric,
                "exchanges": exchanges,
                "generated_at": dt.datetime.now().isoformat(),
                "nday_requested": request.nday,
                "nday_used": nday_used,
                "nday_tried": tried_ndays,
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

    def _fetch_rank(
        self, metric: str, exchange: str, limit: int, *, nday: int = 0
    ) -> list[dict[str, Any]]:
        nday_str = str(max(0, int(nday)))
        if metric in {"market_cap", "marketcap"}:
            return self._client.overseas_market_cap_rank(
                exchange=exchange, limit=limit, nday=nday_str
            )
        if metric in {"value", "amount", "trade_value"}:
            return self._client.overseas_trade_value_rank(
                exchange=exchange, limit=limit, nday=nday_str
            )
        # default to volume
        return self._client.overseas_trade_volume_rank(
            exchange=exchange, limit=limit, nday=nday_str
        )

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
