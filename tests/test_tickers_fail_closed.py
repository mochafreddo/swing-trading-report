from __future__ import annotations

from sab.tickers import (
    canonical_exchange_from_suffix,
    infer_market_from_ticker,
    parse_ticker,
    validate_strict_us_ticker,
)


def test_parse_ticker_does_not_auto_map_ambiguous_us_suffix() -> None:
    parsed = parse_ticker("AAPL.US")

    assert parsed.exchange is None
    assert parsed.market == "KR"
    assert parsed.ticker == "AAPL.US"


def test_canonical_exchange_rejects_ambiguous_us_suffix() -> None:
    assert canonical_exchange_from_suffix("US") is None
    assert canonical_exchange_from_suffix("NASD") == "NAS"


def test_infer_market_treats_ambiguous_us_suffix_as_non_us() -> None:
    assert infer_market_from_ticker("AAPL.US") == "KR"
    assert infer_market_from_ticker("AAPL.NAS") == "US"


def test_validate_strict_us_ticker_rejects_exchange_marker_like_symbol() -> None:
    issue = validate_strict_us_ticker("AAPL.O.NAS")

    assert issue is not None
    assert "invalid US ticker symbol" in issue


def test_validate_strict_us_ticker_rejects_multi_dot_symbol() -> None:
    issue = validate_strict_us_ticker("ABC.DEF.NYS")

    assert issue is not None
    assert "invalid US ticker symbol" in issue


def test_validate_strict_us_ticker_accepts_common_class_symbol() -> None:
    issue = validate_strict_us_ticker("BRK.B.NYS")

    assert issue is None


def test_parse_ticker_keeps_dot_class_as_canonical() -> None:
    parsed = parse_ticker("BRK.B.NYS")

    assert parsed.symbol == "BRK.B"
    assert parsed.ticker == "BRK.B.NYS"


def test_parse_ticker_canonicalizes_slash_class_to_dot() -> None:
    parsed = parse_ticker("BRK/B.NYS")

    assert parsed.symbol == "BRK.B"
    assert parsed.ticker == "BRK.B.NYS"


def test_validate_strict_us_ticker_rejects_non_class_slash_symbol() -> None:
    issue = validate_strict_us_ticker("AAPL/O.NAS")

    assert issue is not None
    assert "invalid US ticker symbol" in issue


def test_validate_strict_us_ticker_rejects_numeric_only_symbol() -> None:
    issue = validate_strict_us_ticker("005930.NAS")

    assert issue is not None
    assert "invalid US ticker symbol" in issue
