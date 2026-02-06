import os
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from sab.config import Config
from sab.scan import run_scan


class RunScanUSHolidayCallTests(unittest.TestCase):
    def test_run_scan_calls_overseas_holidays_when_us_universe(self) -> None:
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
                screener_enabled=False,
                screener_only=False,
            )

            with (
                patch("sab.scan.load_config", return_value=cfg),
                patch("sab.scan.load_watchlist", return_value=[]),
                patch(
                    "sab.scan.write_report",
                    return_value=os.path.join(tmpdir, "report.md"),
                ),
                patch(
                    "sab.scan.KISClient.overseas_holidays",
                    autospec=True,
                    return_value=[{"TRD_DT": "20250101", "open_yn": "N"}],
                ) as mock_holidays,
            ):
                run_scan(
                    limit=None,
                    watchlist_path=None,
                    provider=None,
                    screener_limit=None,
                    universe="watchlist",
                )

            mock_holidays.assert_called_once()
            kwargs = mock_holidays.call_args.kwargs
            self.assertEqual(kwargs.get("country_code"), "US")
            self.assertEqual(len(kwargs.get("start_date", "")), 8)
            self.assertEqual(len(kwargs.get("end_date", "")), 8)


if __name__ == "__main__":
    unittest.main()
