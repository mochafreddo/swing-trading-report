from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_suffix(suffix: str | None) -> str:
    if not suffix:
        return ""
    return "".join(ch for ch in str(suffix).upper() if ch.isalnum())


SUFFIX_TO_EXCHANGE = {
    "NASDAQ": "NAS",
    "NASD": "NAS",
    "NAS": "NAS",
    "NYSE": "NYS",
    "NYS": "NYS",
    "AMEX": "AMS",
    "AMS": "AMS",
}

_NORMALIZED_SUFFIX_TO_EXCHANGE = {
    normalize_suffix(key): value for key, value in SUFFIX_TO_EXCHANGE.items()
}

US_EXCHANGE_CODES = frozenset(_NORMALIZED_SUFFIX_TO_EXCHANGE.values())
US_SUFFIXES = frozenset(_NORMALIZED_SUFFIX_TO_EXCHANGE.keys())
SUPPORTED_ENTRY_CURRENCIES = frozenset({"KRW", "USD"})
KR_TICKER_CODE_PATTERN = re.compile(r"^\d{6}$")
US_BASE_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*$")
US_CLASS_DOT_SYMBOL_PATTERN = re.compile(r"^([A-Z][A-Z0-9]*)\.([ABC])$")
US_CLASS_SLASH_SYMBOL_PATTERN = re.compile(r"^([A-Z][A-Z0-9]*)/([ABC])$")


def canonical_exchange_from_suffix(suffix: str | None) -> str | None:
    return _NORMALIZED_SUFFIX_TO_EXCHANGE.get(normalize_suffix(suffix))


def is_us_suffix(suffix: str | None) -> bool:
    return canonical_exchange_from_suffix(suffix) in US_EXCHANGE_CODES


def is_us_exchange(value: str | None) -> bool:
    text = str(value or "").strip().upper()
    if not text:
        return False
    normalized = normalize_suffix(text)
    if normalized in US_EXCHANGE_CODES:
        return True
    return normalized in US_SUFFIXES


def split_symbol_and_suffix(ticker: str) -> tuple[str, str | None]:
    normalized = str(ticker or "").strip().upper()
    if "." not in normalized:
        return normalized, None
    symbol, suffix = normalized.rsplit(".", 1)
    return symbol.strip().upper(), suffix.strip().upper()


@dataclass(frozen=True)
class ParsedTicker:
    ticker: str
    symbol: str
    suffix: str | None
    exchange: str | None
    market: str


def parse_ticker(ticker: str) -> ParsedTicker:
    symbol, suffix = split_symbol_and_suffix(ticker)
    exchange = canonical_exchange_from_suffix(suffix)
    market = "US" if exchange in US_EXCHANGE_CODES else "KR"
    normalized_symbol = symbol
    if exchange is not None:
        normalized_symbol = _canonicalize_us_symbol(symbol)
    if suffix is None:
        normalized_ticker = normalized_symbol
    elif exchange is not None:
        normalized_ticker = f"{normalized_symbol}.{exchange}"
    else:
        normalized_ticker = f"{normalized_symbol}.{suffix}"
    return ParsedTicker(
        ticker=normalized_ticker,
        symbol=normalized_symbol,
        suffix=suffix,
        exchange=exchange,
        market=market,
    )


def infer_market_from_ticker(ticker: str) -> str:
    return parse_ticker(ticker).market


def infer_currency_from_ticker(ticker: str) -> str:
    return "USD" if infer_market_from_ticker(ticker) == "US" else "KRW"


def _canonicalize_us_symbol(symbol: str) -> str:
    class_dot_match = US_CLASS_DOT_SYMBOL_PATTERN.fullmatch(symbol)
    if class_dot_match is not None:
        base, class_code = class_dot_match.groups()
        return f"{base}.{class_code}"
    class_slash_match = US_CLASS_SLASH_SYMBOL_PATTERN.fullmatch(symbol)
    if class_slash_match is not None:
        base, class_code = class_slash_match.groups()
        return f"{base}.{class_code}"
    return symbol


def _is_valid_us_symbol(symbol: str) -> bool:
    canonical_symbol = _canonicalize_us_symbol(symbol)
    return bool(
        US_BASE_SYMBOL_PATTERN.fullmatch(canonical_symbol)
        or US_CLASS_DOT_SYMBOL_PATTERN.fullmatch(canonical_symbol)
    )


def validate_strict_holdings_ticker(ticker: str) -> str | None:
    parsed = parse_ticker(ticker)
    if not parsed.symbol:
        return "ticker symbol must not be empty"
    if parsed.suffix is None:
        if not KR_TICKER_CODE_PATTERN.fullmatch(parsed.symbol):
            return (
                "ticker must be a 6-digit KR code "
                "or include a supported US exchange suffix"
            )
        return None
    if normalize_suffix(parsed.suffix) == "US":
        return "explicit US exchange suffix required; use .NAS, .NYS, or .AMS"
    if parsed.exchange is None:
        return f"unsupported ticker suffix {parsed.suffix!r}"
    if not _is_valid_us_symbol(parsed.symbol):
        return (
            f"invalid US ticker symbol {parsed.symbol!r}; "
            "use alpha-leading symbol (e.g. AAPL) "
            "or class notation BASE.CLASS (e.g. BRK.B)"
        )
    return None


def validate_strict_us_ticker(ticker: str) -> str | None:
    parsed = parse_ticker(ticker)
    if not parsed.symbol:
        return "ticker symbol must not be empty"
    if parsed.suffix is None:
        return "US ticker must include a supported US exchange suffix"
    if normalize_suffix(parsed.suffix) == "US":
        return "explicit US exchange suffix required; use .NAS, .NYS, or .AMS"
    if parsed.exchange is None:
        return f"unsupported ticker suffix {parsed.suffix!r}"
    if not _is_valid_us_symbol(parsed.symbol):
        return (
            f"invalid US ticker symbol {parsed.symbol!r}; "
            "use alpha-leading symbol (e.g. AAPL) "
            "or class notation BASE.CLASS (e.g. BRK.B)"
        )
    return None


__all__ = [
    "ParsedTicker",
    "SUPPORTED_ENTRY_CURRENCIES",
    "SUFFIX_TO_EXCHANGE",
    "US_EXCHANGE_CODES",
    "US_SUFFIXES",
    "canonical_exchange_from_suffix",
    "infer_currency_from_ticker",
    "infer_market_from_ticker",
    "is_us_exchange",
    "is_us_suffix",
    "normalize_suffix",
    "parse_ticker",
    "split_symbol_and_suffix",
    "validate_strict_holdings_ticker",
    "validate_strict_us_ticker",
]
