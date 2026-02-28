from __future__ import annotations

import logging

from .config import Config
from .holdings_loader import HoldingsData
from .sell_types import _infer_currency_from_ticker, _SellRuntime


def _build_sell_runtime(
    cfg: Config, logger: logging.Logger, *, holdings: HoldingsData
) -> _SellRuntime:
    holding_rows = holdings.holdings
    if not holding_rows:
        logger.warning("No holdings configured. Generating empty sell report.")

    tickers = [holding.ticker for holding in holding_rows if holding.ticker]
    unique_tickers = list(dict.fromkeys(tickers))

    ticker_currency: dict[str, str] = {}
    for holding in holding_rows:
        if not holding.ticker:
            continue
        entry_currency = (holding.entry_currency or "").strip().upper()
        if not entry_currency:
            entry_currency = _infer_currency_from_ticker(holding.ticker)
        ticker_currency[holding.ticker] = entry_currency

    return _SellRuntime(
        cfg=cfg,
        logger=logger,
        holdings=holding_rows,
        unique_tickers=unique_tickers,
        ticker_currency=ticker_currency,
    )
