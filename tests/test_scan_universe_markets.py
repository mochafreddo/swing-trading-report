from __future__ import annotations

from sab.scan import _filter_tickers_by_markets


def test_filter_tickers_by_markets_keeps_kr_only_when_requested() -> None:
    tickers = ["005930", "AAPL.US", "MSFT.NASD", "000660"]

    filtered = _filter_tickers_by_markets(tickers, ["KR"])

    assert filtered == ["005930", "000660"]


def test_filter_tickers_by_markets_keeps_us_only_when_requested() -> None:
    tickers = ["005930", "AAPL.US", "MSFT.NASD", "IBM.NYS"]

    filtered = _filter_tickers_by_markets(tickers, [" us "])

    assert filtered == ["AAPL.US", "MSFT.NASD", "IBM.NYS"]


def test_filter_tickers_by_markets_returns_empty_when_no_market_allowed() -> None:
    filtered = _filter_tickers_by_markets(["005930", "AAPL.US"], [])
    assert filtered == []
