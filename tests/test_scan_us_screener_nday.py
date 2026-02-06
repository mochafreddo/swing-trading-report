import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from sab.config import Config
from sab.scan import run_scan


class RunScanUSScreenerNdayTests(unittest.TestCase):
    def _base_cfg(self, tmpdir: str) -> Config:
        base = Config()
        return replace(
            base,
            kis_app_key="key",
            kis_app_secret="secret",
            kis_base_url="https://example.com",
            universe_markets=["US"],
            data_dir=tmpdir,
            report_dir=tmpdir,
            screener_enabled=True,
            screener_only=True,
            us_screener_mode="kis",
            us_screener_limit=5,
        )

    def test_run_scan_passes_preferred_nday_and_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = self._base_cfg(tmpdir)

            # Force session info to prefer nday=1 (e.g., intraday/holiday).
            fake_session = {
                "state": "intraday",
                "is_holiday": False,
                "preferred_nday": 1,
                "session_date": None,
                "ny_now": None,
            }

            with (
                patch("sab.scan.load_config", return_value=cfg),
                patch("sab.scan.load_watchlist", return_value=[]),
                patch(
                    "sab.scan.write_report",
                    return_value=os.path.join(tmpdir, "report.md"),
                ),
                patch("sab.scan.us_session_info", return_value=fake_session),
                patch("sab.scan.KISClient.overseas_holidays", return_value=[]),
                patch("sab.scan.KISClient.overseas_daily_candles", return_value=[]),
                patch(
                    "sab.scan.KUS.screen",
                    autospec=True,
                    return_value=type(
                        "KRes",
                        (),
                        {
                            "tickers": ["AAPL.NAS"],
                            "metadata": {"nday_used": 1, "nday_tried": [1]},
                        },
                    )(),
                ) as mock_screen,
            ):
                run_scan(
                    limit=None,
                    watchlist_path=None,
                    provider=None,
                    screener_limit=None,
                    universe="screener",
                )

            # Ensure preferred nday=1 and fallbacks exclude 0.
            args, kwargs = mock_screen.call_args
            req = kwargs.get("request") or args[1]
            self.assertEqual(req.nday, 1)
            self.assertNotIn(0, req.fallback_ndays)
            self.assertTrue(all(n >= 1 for n in req.fallback_ndays))


if __name__ == "__main__":
    unittest.main()
