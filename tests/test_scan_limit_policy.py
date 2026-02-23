from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sab.config import Config
from sab.scan import run_scan
from sab.scan_screener import _load_scan_tickers


def test_load_scan_tickers_does_not_apply_screen_limit() -> None:
    cfg = replace(Config(), screen_limit=1, watchlist_path="watchlist.txt")

    tickers = _load_scan_tickers(
        cfg,
        watchlist_path=None,
        load_watchlist_fn=lambda _path: ["005930", "000660"],
    )

    assert tickers == ["005930", "000660"]


class _FakeMarketDataService:
    def __init__(self) -> None:
        self.collected_tickers: list[str] = []

    def initialize_provider(self, runtime: Any, *, policy: Any) -> None:
        del runtime, policy

    def collect_market_data(self, runtime: Any, *, policy: Any) -> None:
        self.collected_tickers = list(policy.tickers)
        runtime.market_data = {
            ticker: [
                {
                    "date": "20250101",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                    "volume": 1_000_000.0,
                }
            ]
            for ticker in runtime.tickers
        }


def test_run_scan_applies_limit_after_screener_merge(tmp_path: Path) -> None:
    cfg = replace(
        Config(),
        screen_limit=2,
        data_dir=str(tmp_path),
        report_dir=str(tmp_path),
        screener_enabled=True,
        screener_only=False,
    )
    fake_market_data_service = _FakeMarketDataService()

    def fake_run_screeners(runtime: Any, **_kwargs: Any) -> None:
        runtime.tickers = list(dict.fromkeys(runtime.tickers + ["000660", "035420"]))

    with (
        patch("sab.scan.load_config", return_value=cfg),
        patch("sab.scan.scan_screener._load_scan_tickers", return_value=["005930"]),
        patch(
            "sab.scan.scan_screener._resolve_screener_flags", return_value=(True, False)
        ),
        patch("sab.scan.scan_screener._run_screeners", side_effect=fake_run_screeners),
        patch(
            "sab.scan._build_market_data_service", return_value=fake_market_data_service
        ),
        patch("sab.scan._resolve_scan_fx", return_value=None),
        patch("sab.scan._evaluate_scan_runtime", return_value=None),
        patch(
            "sab.scan._render_scan_report",
            return_value=str(tmp_path / "2026-02-23.buy.md"),
        ),
        patch("sab.scan.maybe_upload_report_artifact", return_value=None),
    ):
        code = run_scan(
            limit=2,
            watchlist_path=None,
            provider=None,
            screener_limit=None,
            universe="both",
        )

    assert code == 0
    assert fake_market_data_service.collected_tickers == ["005930", "000660"]
