from __future__ import annotations

from sab.scan_types import (
    _coerce_nday,
    _excd_from_suffix,
    _filter_tickers_by_markets,
    _format_ny_now_for_log,
    _infer_currency,
    _infer_market,
    _split_overseas,
    _to_float,
)


def test_scan_type_helpers_basic_behavior() -> None:
    assert _format_ny_now_for_log({}) == "-"
    assert _infer_currency("AAPL.US") == "USD"
    assert _infer_currency("AAPL.NAS-DAQ") == "USD"
    assert _infer_market("005930") == "KR"
    assert _infer_market("AAPL.NAS-DAQ") == "US"
    assert _filter_tickers_by_markets(["005930", "AAPL.US"], ["KR"]) == ["005930"]
    assert _filter_tickers_by_markets(["AAPL.NAS-DAQ"], ["US"]) == ["AAPL.NAS-DAQ"]
    assert _to_float("1.25") == 1.25
    assert _split_overseas("AAPL.US") == ("AAPL", "US")
    assert _excd_from_suffix("NASDAQ") == "NAS"
    assert _coerce_nday("3") == 3
