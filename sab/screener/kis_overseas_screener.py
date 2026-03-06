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
_METRIC_NAME_ALIASES: dict[str, str] = {
    "amount": "value",
    "market_cap": "market_cap",
    "marketcap": "market_cap",
    "trade_value": "value",
    "value": "value",
    "volume": "volume",
}
_METRIC_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "volume": (
        "ACC_TRDVOL",
        "ACML_VOL",
        "OVRS_TRDVOL",
        "TRDVOL",
        "trade_volume",
        "volume",
    ),
    "value": (
        "ACC_TRDVAL",
        "ACML_AMT",
        "ACML_TR_AMT",
        "ACML_TR_PBMN",
        "OVRS_TR_PBMN",
        "TRDVAL",
        "trade_value",
        "value",
    ),
    "market_cap": (
        "MKTCAP",
        "OVRS_MKTCAP",
        "marketCap",
        "market_cap",
    ),
}
_METRIC_FIELD_PATTERNS: dict[str, tuple[str, ...]] = {
    "volume": ("vol",),
    "value": ("amt", "pbmn", "trdval", "value"),
    "market_cap": ("cap", "mktc"),
}
_METRIC_FIELD_IGNORE_PATTERNS = ("rank", "ratio", "rate", "pct", "prdy", "change")


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
        metric = self._normalize_metric_name(request.metric)
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
        selection_mode = "global_metric_merge"
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
            fetch_limit = max(1, limit)
            for exch in exchanges:
                rows = self._fetch_rank(metric, exch, fetch_limit, nday=nd)
                if not rows:
                    continue
                normalized_rows = self._normalize_rows(
                    rows,
                    exchange=exch,
                    metric=metric,
                )
                if normalized_rows:
                    exchange_rows[exch] = normalized_rows
                    current_exchange_bucket_sizes[exch] = len(normalized_rows)
            if exchange_rows:
                tickers, by_ticker = self._global_metric_select(
                    exchanges=exchanges,
                    exchange_rows=exchange_rows,
                    metric=metric,
                    limit=limit,
                )
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
        self,
        rows: list[dict[str, Any]],
        *,
        exchange: str,
        metric: str,
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
            enriched["bucket_exchange"] = bucket_exchange
            enriched["provider_rank"] = idx + 1
            enriched["metric_name"] = metric
            enriched["metric_value"] = self._extract_metric_value(row, metric=metric)
            normalized_rows.append((ticker, enriched))
        return normalized_rows

    @staticmethod
    def _looks_like_class_symbol(symbol: str) -> bool:
        return _CLASS_SYMBOL_PATTERN.fullmatch(symbol) is not None

    @staticmethod
    def _global_metric_select(
        *,
        exchanges: list[str],
        exchange_rows: dict[str, list[tuple[str, dict[str, Any]]]],
        metric: str,
        limit: int,
    ) -> tuple[list[str], dict[str, dict[str, Any]]]:
        combined_rows: list[tuple[str, dict[str, Any]]] = []
        for exchange in exchanges:
            combined_rows.extend(exchange_rows.get(exchange, []))

        def _sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, float, int, str]:
            ticker, row = item
            metric_value = KISOverseasScreener._to_numeric(row.get("metric_value"))
            provider_rank = row.get("provider_rank")
            try:
                normalized_rank = (
                    int(provider_rank) if provider_rank is not None else 10**9
                )
            except TypeError, ValueError:
                normalized_rank = 10**9
            if metric_value is None:
                return (1, 0.0, normalized_rank, ticker)
            return (0, -metric_value, normalized_rank, ticker)

        combined_rows.sort(key=_sort_key)

        tickers: list[str] = []
        by_ticker: dict[str, dict[str, Any]] = {}
        selected: set[str] = set()
        for ticker, row in combined_rows:
            if ticker in selected:
                continue
            by_ticker[ticker] = dict(row)
            by_ticker[ticker].setdefault("metric_name", metric)
            tickers.append(ticker)
            selected.add(ticker)
            if len(tickers) >= limit:
                break
        return tickers, by_ticker

    @staticmethod
    def _normalize_metric_name(metric: str | None) -> str:
        normalized = str(metric or "volume").strip().lower()
        return _METRIC_NAME_ALIASES.get(normalized, "volume")

    @staticmethod
    def _to_numeric(value: Any) -> float | None:
        try:
            parsed = float(str(value).replace(",", ""))
        except TypeError, ValueError:
            return None
        if parsed != parsed:
            return None
        return parsed

    @classmethod
    def _extract_metric_value(cls, row: dict[str, Any], *, metric: str) -> float | None:
        aliases = _METRIC_FIELD_ALIASES.get(metric, ())
        for field_name in aliases:
            if field_name not in row:
                continue
            parsed = cls._to_numeric(row.get(field_name))
            if parsed is not None:
                return parsed

        patterns = _METRIC_FIELD_PATTERNS.get(metric, ())
        for key, value in row.items():
            lowered = str(key).strip().lower()
            if not lowered:
                continue
            if any(ignore in lowered for ignore in _METRIC_FIELD_IGNORE_PATTERNS):
                continue
            if not any(pattern in lowered for pattern in patterns):
                continue
            parsed = cls._to_numeric(value)
            if parsed is not None:
                return parsed
        return None

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
