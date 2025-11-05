from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..data.kis_client import KISClient


@dataclass
class ScreenRequest:
    limit: int
    min_price: Optional[float] = None
    min_dollar_volume: Optional[float] = None


@dataclass
class ScreenResult:
    tickers: List[str]
    metadata: Dict[str, Any]


class KISScreener:
    """Fetches ranked tickers from KIS Developers volume-rank API."""

    def __init__(self, client: KISClient) -> None:
        self._client = client

    def screen(self, request: ScreenRequest) -> ScreenResult:
        raw = self._client.volume_rank(limit=max(request.limit * 2, 50))

        tickers: List[str] = []
        rows: List[Dict[str, Any]] = []

        for row in raw:
            price = row.get("price", 0.0) or 0.0
            amount = row.get("amount", 0.0) or 0.0

            if request.min_price and price < request.min_price:
                continue
            if request.min_dollar_volume and amount < request.min_dollar_volume:
                continue

            ticker = str(row.get("ticker", "")).strip()
            if not ticker:
                continue
            if ticker in tickers:
                continue

            tickers.append(ticker)
            rows.append(row)

            if len(tickers) >= request.limit:
                break

        return ScreenResult(
            tickers=tickers,
            metadata={
                "source": "kis",
                "requested_limit": request.limit,
                "returned": len(tickers),
                "filters": {
                    "min_price": request.min_price,
                    "min_dollar_volume": request.min_dollar_volume,
                },
            },
        )
