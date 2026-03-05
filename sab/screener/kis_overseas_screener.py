from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from ..data.kis_client import KISClient
from ..tickers import (
    canonical_exchange_from_suffix,
    normalize_suffix,
    parse_ticker,
    split_symbol_and_suffix,
    validate_strict_us_ticker,
)

_CLASS_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:[/.][ABC])$")


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
        try:
            limit = max(0, int(request.limit))
        except TypeError, ValueError:
            limit = 0
        ndays: list[int] = []
        if request.nday is not None:
            try:
                ndays.append(max(0, int(request.nday)))
            except TypeError, ValueError:
                ndays.append(0)
        for nd in request.fallback_ndays or []:
            try:
                candidate = max(0, int(nd))
            except TypeError, ValueError:
                continue
            if candidate not in ndays:
                ndays.append(candidate)
        if not ndays:
            ndays = [0]

        nday_used: int | None = None
        tried_ndays: list[int] = []
        selection_mode = "round_robin_exchange"
        exchange_bucket_sizes: dict[str, int] = {}

        if limit <= 0:
            return ScreenResult(
                tickers=[],
                metadata={
                    "source": "kis_overseas_rank",
                    "metric": metric,
                    "exchanges": exchanges,
                    "generated_at": dt.datetime.now().isoformat(),
                    "nday_requested": request.nday,
                    "nday_used": None,
                    "nday_tried": tried_ndays,
                    "selection_mode": selection_mode,
                    "exchange_bucket_sizes": exchange_bucket_sizes,
                    "by_ticker": by_ticker,
                },
            )

        for nd in ndays:
            tried_ndays.append(nd)
            exchange_rows: dict[str, list[tuple[str, dict[str, Any]]]] = {}
            current_exchange_bucket_sizes: dict[str, int] = {}
            base_fetch_limit = max(1, (limit + len(exchanges) - 1) // len(exchanges))
            for exch in exchanges:
                rows = self._fetch_rank(metric, exch, base_fetch_limit, nday=nd)
                if not rows:
                    continue
                normalized_rows = self._normalize_rows(rows, exchange=exch)
                if normalized_rows:
                    exchange_rows[exch] = normalized_rows
                    current_exchange_bucket_sizes[exch] = len(normalized_rows)
            if exchange_rows:
                tickers, by_ticker = self._round_robin_select(
                    exchanges=exchanges,
                    exchange_rows=exchange_rows,
                    limit=limit,
                )
                remaining = limit - len(tickers)
                if remaining > 0:
                    for exch in exchanges:
                        if remaining <= 0:
                            break
                        existing_rows = exchange_rows.get(exch, [])
                        if not existing_rows:
                            continue
                        target_limit = min(limit, len(existing_rows) + remaining)
                        if target_limit <= len(existing_rows):
                            continue
                        refill_rows = self._fetch_rank(
                            metric, exch, target_limit, nday=nd
                        )
                        normalized_refill = self._normalize_rows(
                            refill_rows, exchange=exch
                        )
                        if not normalized_refill:
                            continue
                        exchange_rows[exch] = normalized_refill
                        current_exchange_bucket_sizes[exch] = len(normalized_refill)
                        tickers, by_ticker = self._round_robin_select(
                            exchanges=exchanges,
                            exchange_rows=exchange_rows,
                            limit=limit,
                        )
                        remaining = limit - len(tickers)
            if tickers:
                # Prefer a single session's ranks; stop once we have results.
                nday_used = nd
                exchange_bucket_sizes = current_exchange_bucket_sizes
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
                "selection_mode": selection_mode,
                "exchange_bucket_sizes": exchange_bucket_sizes,
                "by_ticker": by_ticker,
            },
        )

    def _normalize_rows(
        self, rows: list[dict[str, Any]], *, exchange: str
    ) -> list[tuple[str, dict[str, Any]]]:
        normalized_rows: list[tuple[str, dict[str, Any]]] = []
        bucket_exchange = self._normalize_exchange(exchange)
        for idx, row in enumerate(rows):
            sym = self._symbol_from_row(row)
            if not sym:
                raise ValueError(
                    "invalid overseas rank row: "
                    f"exchange={bucket_exchange}, index={idx}, empty symbol"
                )
            base_symbol, suffix = split_symbol_and_suffix(sym)
            if not base_symbol:
                raise ValueError(
                    "invalid overseas rank row: "
                    f"exchange={bucket_exchange}, index={idx}, symbol={sym!r}"
                )

            resolved_base_symbol = base_symbol
            ticker_exchange: str
            if suffix is None or normalize_suffix(suffix) == "US":
                ticker_exchange = bucket_exchange
            else:
                canonical_exchange = canonical_exchange_from_suffix(suffix)
                if canonical_exchange is None and self._looks_like_class_symbol(sym):
                    resolved_base_symbol = sym
                    ticker_exchange = bucket_exchange
                elif canonical_exchange is None:
                    raise ValueError(
                        "invalid overseas rank row: "
                        f"exchange={bucket_exchange}, index={idx}, symbol={sym!r} "
                        f"(unsupported suffix {suffix!r})"
                    )
                else:
                    ticker_exchange = canonical_exchange

            ticker_raw = f"{resolved_base_symbol}.{ticker_exchange}"
            ticker = parse_ticker(ticker_raw).ticker
            ticker_issue = validate_strict_us_ticker(ticker)
            if ticker_issue is not None:
                raise ValueError(
                    "invalid overseas rank row: "
                    f"exchange={bucket_exchange}, index={idx}, symbol={sym!r} "
                    f"({ticker_issue})"
                )
            enriched = dict(row)
            enriched.setdefault("exchange", ticker_exchange)
            normalized_rows.append((ticker, enriched))
        return normalized_rows

    @staticmethod
    def _looks_like_class_symbol(symbol: str) -> bool:
        return _CLASS_SYMBOL_PATTERN.fullmatch(symbol) is not None

    @staticmethod
    def _round_robin_select(
        *,
        exchanges: list[str],
        exchange_rows: dict[str, list[tuple[str, dict[str, Any]]]],
        limit: int,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        tickers: list[str] = []
        by_ticker: dict[str, dict[str, Any]] = {}
        cursors = dict.fromkeys(exchanges, 0)
        selected: set[str] = set()
        while len(tickers) < limit:
            progressed = False
            for exchange in exchanges:
                rows = exchange_rows.get(exchange, [])
                cursor = cursors.get(exchange, 0)
                while cursor < len(rows):
                    ticker, row = rows[cursor]
                    cursor += 1
                    cursors[exchange] = cursor
                    if ticker in selected:
                        continue
                    tickers.append(ticker)
                    by_ticker[ticker] = row
                    selected.add(ticker)
                    progressed = True
                    break
                if len(tickers) >= limit:
                    break
            if not progressed:
                break
        return tickers, by_ticker

    def _resolve_exchanges(self, exchange: str | None) -> list[str]:
        if exchange:
            return [self._normalize_exchange(exchange)]
        return ["NAS", "NYS", "AMS"]

    @staticmethod
    def _normalize_exchange(exchange: str) -> str:
        mapping = {
            "NASDAQ": "NAS",
            "NASD": "NAS",
            "NAS": "NAS",
            "NYSE": "NYS",
            "NYS": "NYS",
            "AMEX": "AMS",
            "AMS": "AMS",
        }
        code = (exchange or "").strip().upper()
        if not code:
            return "NAS"
        normalized = mapping.get(code)
        if normalized is None:
            raise ValueError(
                f"unsupported overseas exchange {exchange!r}; use NAS, NYS, or AMS"
            )
        return normalized

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
