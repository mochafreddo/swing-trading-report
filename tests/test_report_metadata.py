from __future__ import annotations

from sab.report.metadata import collect_row_tickers, infer_market_from_currency


def test_collect_row_tickers_preserves_first_seen_order() -> None:
    rows: list[dict[str, object]] = [
        {"ticker": " AAPL.NAS "},
        {"ticker": ""},
        {"ticker": None},
        {"ticker": "005930"},
        {"ticker": "AAPL.NAS"},
        {"ticker": "MSFT.NAS"},
    ]

    assert collect_row_tickers(rows) == ["AAPL.NAS", "005930", "MSFT.NAS"]


def test_infer_market_from_currency_matches_report_contract() -> None:
    assert infer_market_from_currency([]) == ("MIXED", None)
    assert infer_market_from_currency([{"currency": "usd"}]) == ("US", None)
    assert infer_market_from_currency([{"currency": "KRW"}]) == ("KR", None)
    assert infer_market_from_currency([{"currency": "USD"}, {"currency": "KRW"}]) == (
        "MIXED",
        ["KR", "US"],
    )
