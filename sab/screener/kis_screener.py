from __future__ import annotations

import datetime as dt
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from ..data.cache import load_json, save_json
from ..data.kis_client import KISClient

logger = logging.getLogger(__name__)


@dataclass
class ScreenRequest:
    limit: int
    min_price: float | None = None
    min_dollar_volume: float | None = None


@dataclass
class ScreenResult:
    tickers: list[str]
    metadata: dict[str, Any]


class KISScreener:
    """Fetches ranked tickers from KIS Developers volume-rank API."""

    def __init__(
        self,
        client: KISClient,
        cache_dir: str | None = None,
        cache_ttl_minutes: float = 5.0,
    ) -> None:
        self._client = client
        self._cache_dir = cache_dir
        self._cache_ttl = cache_ttl_minutes

    def screen(self, request: ScreenRequest) -> ScreenResult:
        if self._cache_dir:
            cached = self._load_cache(request)
            if cached:
                return cached

        raw = self._client.volume_rank(limit=max(request.limit * 2, 50))

        tickers: list[str] = []
        rows: list[dict[str, Any]] = []

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

            enriched = dict(row)
            name = (
                row.get("hts_kor_isnm")
                or row.get("stck_hnm")
                or row.get("kor_sec_name")
                or ticker
            )
            enriched["ticker"] = ticker
            enriched["name"] = name

            tickers.append(ticker)
            rows.append(enriched)

            if len(tickers) >= request.limit:
                break

        result = ScreenResult(
            tickers=tickers,
            metadata={
                "source": "kis",
                "requested_limit": request.limit,
                "returned": len(tickers),
                "filters": {
                    "min_price": request.min_price,
                    "min_dollar_volume": request.min_dollar_volume,
                },
                "rows": rows,
                "by_ticker": {row["ticker"]: row for row in rows},
            },
        )

        if self._cache_dir:
            self._save_cache(request, result)

        return result

    def _cache_key(self, request: ScreenRequest) -> str:
        parts = ["screener", f"limit{request.limit}"]
        if request.min_price:
            parts.append(f"price{int(request.min_price)}")
        if request.min_dollar_volume:
            parts.append(f"vol{int(request.min_dollar_volume)}")
        return "_".join(parts)

    def _load_cache(self, request: ScreenRequest) -> ScreenResult | None:
        if self._cache_dir is None:
            return None
        key = self._cache_key(request)
        data = load_json(self._cache_dir, key)
        if not data:
            return None
        ts = data.get("timestamp")
        if not ts:
            return None
        try:
            cached_at = dt.datetime.fromisoformat(ts)
        except ValueError:
            return None
        age = (dt.datetime.now() - cached_at).total_seconds() / 60.0
        if age > self._cache_ttl:
            return None

        metadata = data.get("metadata", {})
        metadata = dict(metadata)
        metadata["cache_status"] = "hit"
        metadata["cache_age_min"] = round(age, 2)
        logger.info("Screener cache hit (age %.2f minutes) for %s", age, request.limit)
        return ScreenResult(tickers=data.get("tickers", []), metadata=metadata)

    def _save_cache(self, request: ScreenRequest, result: ScreenResult) -> None:
        if self._cache_dir is None:
            return
        key = self._cache_key(request)
        metadata = dict(result.metadata)
        metadata["cache_status"] = "refresh"
        payload = {
            "timestamp": dt.datetime.now().isoformat(),
            "tickers": result.tickers,
            "metadata": metadata,
        }
        with suppress(Exception):
            save_json(self._cache_dir, key, payload)
