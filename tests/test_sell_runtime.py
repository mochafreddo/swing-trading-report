from __future__ import annotations

import logging

from sab.config import Config
from sab.holdings_loader import Holding, HoldingsData, HoldingSettings
from sab.sell_runtime import _build_sell_runtime


def _holdings_data(rows: list[Holding]) -> HoldingsData:
    return HoldingsData(
        path=None,
        settings=HoldingSettings(),
        holdings=rows,
    )


def test_build_sell_runtime_excludes_inactive_holdings() -> None:
    runtime = _build_sell_runtime(
        Config(),
        logging.getLogger("test"),
        holdings=_holdings_data(
            [
                Holding(ticker="005930", quantity=0, entry_price=0),
                Holding(
                    ticker="AAPL.NAS",
                    quantity=2,
                    entry_price=150,
                    entry_currency="USD",
                ),
            ]
        ),
    )

    assert [holding.ticker for holding in runtime.holdings] == ["AAPL.NAS"]
    assert runtime.unique_tickers == ["AAPL.NAS"]
    assert runtime.ticker_currency == {"AAPL.NAS": "USD"}


def test_build_sell_runtime_handles_all_inactive_holdings() -> None:
    runtime = _build_sell_runtime(
        Config(),
        logging.getLogger("test"),
        holdings=_holdings_data(
            [
                Holding(ticker="005930", quantity=0, entry_price=0),
                Holding(ticker="000660", quantity=0, entry_price=0),
            ]
        ),
    )

    assert runtime.holdings == []
    assert runtime.unique_tickers == []
    assert runtime.ticker_currency == {}
