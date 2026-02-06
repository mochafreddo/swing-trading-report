from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sab.config import Config
from sab.config_loader import ConfigLoadError
from sab.holdings_loader import (
    Holding,
    HoldingsData,
    HoldingSettings,
    HoldingsLoadError,
)
from sab.scan import run_scan
from sab.sell import run_sell
from sab.signals.sell_rules import SellEvaluation


@pytest.mark.parametrize(
    "err",
    [ConfigLoadError("bad config"), HoldingsLoadError("bad holdings")],
)
def test_run_scan_returns_1_when_config_loading_fails(err: Exception) -> None:
    with patch("sab.scan.load_config", side_effect=err):
        code = run_scan(
            limit=None,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe=None,
        )

    assert code == 1


@pytest.mark.parametrize(
    "err",
    [ConfigLoadError("bad config"), HoldingsLoadError("bad holdings")],
)
def test_run_sell_returns_1_when_config_loading_fails(err: Exception) -> None:
    with patch("sab.sell.load_config", side_effect=err):
        code = run_sell(provider=None)

    assert code == 1


def _build_candles(count: int = 220) -> list[dict[str, float | str]]:
    candles: list[dict[str, float | str]] = []
    base_date = dt.date(2025, 1, 1)
    for idx in range(count):
        day = base_date + dt.timedelta(days=idx)
        close = 100.0 + (idx * 0.1)
        candles.append(
            {
                "date": day.strftime("%Y%m%d"),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return candles


class _FakeKISClient:
    cache_status = "none"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def overseas_daily_candles(
        self, *, symbol: str, exchange: str, count: int
    ) -> list[dict[str, float | str]]:
        return _build_candles()

    def daily_candles(self, symbol: str, *, count: int) -> list[dict[str, float | str]]:
        return _build_candles()


def _build_holdings(tickers: list[str]) -> HoldingsData:
    return HoldingsData(
        path=None,
        settings=HoldingSettings(),
        holdings=[
            Holding(
                ticker=ticker,
                quantity=1.0,
                entry_price=100.0,
                entry_date="2025-01-01",
            )
            for ticker in tickers
        ],
    )


@pytest.mark.parametrize(
    ("tickers", "expected_exchange"),
    [
        (["AAPL.NAS", "005930"], {"AAPL.NAS": "NAS", "005930": None}),
        (["005930", "IBM.NYS"], {"005930": None, "IBM.NYS": "NYS"}),
    ],
)
def test_run_sell_maps_exchange_per_ticker_without_suffix_scope_leak(
    tmp_path: Path, tickers: list[str], expected_exchange: dict[str, str | None]
) -> None:
    cfg = replace(
        Config(),
        data_provider="kis",
        kis_app_key="key",
        kis_app_secret="secret",
        kis_base_url="https://example.com",
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        holdings=_build_holdings(tickers),
        sell_mode="generic",
    )
    captured_exchange: dict[str, str | None] = {}

    def fake_evaluate_sell_signals(
        ticker: str,
        candles: list[dict[str, float]],
        holding: dict[str, Any],
        settings: Any,
    ) -> SellEvaluation:
        captured_exchange[ticker] = holding.get("exchange")
        return SellEvaluation(
            action="HOLD",
            reasons=["ok"],
            eval_price=float(candles[-1]["close"]),
            eval_date=str(candles[-1]["date"]),
        )

    with (
        patch("sab.sell.load_config", return_value=cfg),
        patch("sab.sell.KISClient", _FakeKISClient),
        patch("sab.sell.resolve_fx_rate", return_value=(None, None, [])),
        patch(
            "sab.sell.write_sell_report",
            return_value=str(tmp_path / "2026-02-06.sell.md"),
        ),
        patch("sab.sell.evaluate_sell_signals", side_effect=fake_evaluate_sell_signals),
    ):
        code = run_sell(provider=None)

    assert code == 0
    assert captured_exchange == expected_exchange
