from __future__ import annotations

import sab.scan as scan


def test_scan_shim_symbols_are_exposed() -> None:
    expected = [
        "_coerce_nday",
        "_excd_from_suffix",
        "_filter_tickers_by_markets",
        "_format_ny_now_for_log",
        "_infer_currency",
        "_infer_market",
        "_split_overseas",
        "_to_float",
    ]
    for name in expected:
        assert hasattr(scan, name)
        assert callable(getattr(scan, name))


def test_scan_shim_symbols_basic_behavior() -> None:
    assert scan._format_ny_now_for_log({}) == "-"
    assert scan._infer_currency("AAPL.US") == "USD"
    assert scan._infer_market("005930") == "KR"
    assert scan._filter_tickers_by_markets(["005930", "AAPL.US"], ["KR"]) == ["005930"]
    assert scan._to_float("1.25") == 1.25
    assert scan._split_overseas("AAPL.US") == ("AAPL", "US")
    assert scan._excd_from_suffix("NASDAQ") == "NAS"
    assert scan._coerce_nday("3") == 3
