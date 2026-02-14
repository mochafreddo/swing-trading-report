from __future__ import annotations

import logging

from .config import Config
from .sell_types import _infer_currency_from_ticker, _SellRuntime


def _build_sell_runtime(cfg: Config, logger: logging.Logger) -> _SellRuntime:
    holdings = cfg.holdings.holdings
    if not holdings:
        logger.warning("No holdings configured. Generating empty sell report.")

    tickers = [holding.ticker for holding in holdings if holding.ticker]
    unique_tickers = list(dict.fromkeys(tickers))

    ticker_currency: dict[str, str] = {}
    for holding in holdings:
        if not holding.ticker:
            continue
        entry_currency = (holding.entry_currency or "").strip().upper()
        if not entry_currency:
            entry_currency = _infer_currency_from_ticker(holding.ticker)
        ticker_currency[holding.ticker] = entry_currency

    return _SellRuntime(
        cfg=cfg,
        logger=logger,
        holdings=holdings,
        unique_tickers=unique_tickers,
        ticker_currency=ticker_currency,
    )
