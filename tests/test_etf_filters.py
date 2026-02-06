from __future__ import annotations

from sab.signals.etf_filters import is_etf_or_leveraged


def test_is_etf_or_leveraged_detects_us_etf_by_name() -> None:
    meta = {"name": "Vanguard Total Stock Market ETF"}
    assert is_etf_or_leveraged("VTI.AMS", meta) is True


def test_is_etf_or_leveraged_detects_issuer_without_etf_token() -> None:
    meta = {"name": "iShares JP Morgan USD Emerging Markets Bond"}
    assert is_etf_or_leveraged("EMB.NAS", meta) is True


def test_is_etf_or_leveraged_detects_spdr_without_etf_token() -> None:
    meta = {"name": "SPDR Utilities Select Sector"}
    assert is_etf_or_leveraged("XLU.AMS", meta) is True


def test_is_etf_or_leveraged_detects_kr_leverage_by_name() -> None:
    meta = {"name": "KODEX 레버리지"}
    assert is_etf_or_leveraged("122630", meta) is True


def test_is_etf_or_leveraged_detects_leveraged_keyword_in_name() -> None:
    meta = {"name": "ProShares UltraPro QQQ"}
    assert is_etf_or_leveraged("TQQQ.NAS", meta) is True


def test_is_etf_or_leveraged_detects_ticker_hint_3x() -> None:
    # Even without a name, obvious 3X tickers should be treated as leveraged.
    meta: dict[str, str] = {}
    assert is_etf_or_leveraged("ABC3X.US", meta) is True


def test_is_etf_or_leveraged_detects_meta_flag_and_type_field() -> None:
    meta = {"name": "Apple Inc.", "is_etf": True, "security_type": "Equity"}
    assert is_etf_or_leveraged("AAPL.NAS", meta) is True


def test_is_etf_or_leveraged_detects_meta_type_keyword() -> None:
    meta = {"name": "Apple Inc.", "instrument_type": "ETF"}
    assert is_etf_or_leveraged("AAPL.NAS", meta) is True


def test_is_etf_or_leveraged_ignores_invesco_stock_without_fund_context() -> None:
    meta = {"name": "Invesco Ltd."}
    assert is_etf_or_leveraged("IVZ.NYS", meta) is False


def test_is_etf_or_leveraged_ignores_plain_stock() -> None:
    meta = {"name": "Apple Inc."}
    assert is_etf_or_leveraged("AAPL.NAS", meta) is False
