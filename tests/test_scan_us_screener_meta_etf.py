from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from sab.config import Config
from sab.scan import run_scan
from sab.screener.kis_overseas_screener import ScreenResult as OverseasScreenResult


def _build_us_candles(n: int = 200) -> list[dict[str, float | str]]:
    candles: list[dict[str, float | str]] = []
    base_date = dt.date(2025, 1, 1)
    for i in range(n):
        d = base_date + dt.timedelta(days=i)
        close = 100.0 + i * 0.5
        candles.append(
            {
                "date": d.strftime("%Y%m%d"),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000.0,
            }
        )
    return candles


class RunScanUSScreenerMetaETFTests(unittest.TestCase):
    def test_us_screener_propagates_name_into_meta_for_hybrid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_cfg = Config()
            cfg = replace(
                base_cfg,
                kis_app_key="key",
                kis_app_secret="secret",
                kis_base_url="https://example.com",
                universe_markets=["US"],
                data_dir=tmpdir,
                report_dir=tmpdir,
                screener_enabled=True,
                screener_only=True,
                us_screener_mode="kis",
                strategy_mode="sma_ema_hybrid",
                exclude_etf_etn=True,
            )

            # ScreenResult with ETF-style name in by_ticker metadata.
            kres = OverseasScreenResult(
                tickers=["VTI.AMS"],
                metadata={
                    "source": "kis_overseas_rank",
                    "by_ticker": {
                        "VTI.AMS": {
                            "name": "Vanguard Total Stock Market ETF",
                        }
                    },
                },
            )

            captured_meta: dict[str, object] = {}

            def fake_eval_hybrid(ticker, candles, settings, meta):
                # Capture meta passed from scan so we can assert name propagation.
                captured_meta.update(meta)
                from sab.signals.hybrid_buy import HybridEvaluationResult

                return HybridEvaluationResult(
                    ticker, None, "Did not meet hybrid signal criteria"
                )

            with (
                patch("sab.scan.load_config", return_value=cfg),
                patch("sab.scan.load_watchlist", return_value=[]),
                patch(
                    "sab.scan.write_report",
                    return_value=os.path.join(tmpdir, "report.md"),
                ),
                patch("sab.scan.KUS.screen", return_value=kres),
                patch("sab.scan.KISClient.overseas_holidays", return_value=[]),
                patch(
                    "sab.scan.KISClient.overseas_daily_candles",
                    return_value=_build_us_candles(),
                ),
                patch("sab.scan.evaluate_ticker_hybrid", side_effect=fake_eval_hybrid),
            ):
                run_scan(
                    limit=None,
                    watchlist_path=None,
                    provider=None,
                    screener_limit=None,
                    universe="screener",
                )

            # Name from KIS screener metadata should be visible to hybrid evaluator.
            self.assertEqual(
                captured_meta.get("name"),
                "Vanguard Total Stock Market ETF",
            )


if __name__ == "__main__":
    unittest.main()
