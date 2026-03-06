import datetime as dt
import json
import logging
import os
import tempfile
import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from sab.config import Config
from sab.market_data_common import build_market_data_dependencies
from sab.market_data_service import ScanMarketData
from sab.scan import run_scan


class RunScanUSHolidayCallTests(unittest.TestCase):
    def test_run_scan_calls_overseas_holidays_when_us_universe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            watchlist_path = os.path.join(tmpdir, "watchlist.txt")
            with open(watchlist_path, "w", encoding="utf-8") as watchlist_file:
                watchlist_file.write("AAPL.US\n")
            base_cfg = Config()
            cfg = replace(
                base_cfg,
                kis_app_key="key",
                kis_app_secret="secret",
                kis_base_url="https://example.com",
                universe_markets=["US"],
                data_dir=tmpdir,
                report_dir=tmpdir,
                watchlist_path=watchlist_path,
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
                    "sab.market_data_common.KISClient.overseas_holidays",
                    autospec=True,
                    return_value=[{"TRD_DT": "20250101", "open_yn": "N"}],
                ) as mock_holidays,
                patch(
                    "sab.market_data_service._current_utc_time",
                    return_value=dt.datetime(2026, 3, 6, 9, 0, tzinfo=dt.UTC),
                ),
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
            self.assertEqual(kwargs.get("start_date"), "20260306")
            self.assertEqual(kwargs.get("end_date"), "20260316")

    def test_refresh_us_holidays_skips_api_when_cache_is_within_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "holidays_us.json")
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                json.dump(
                    {
                        "20250101": {
                            "note": "New Year's Day",
                            "is_open": False,
                        }
                    },
                    cache_file,
                )

            now = dt.datetime(2026, 3, 6, 9, 0, tzinfo=dt.UTC)
            os.utime(cache_path, (now.timestamp(), now.timestamp()))

            kis_client = SimpleNamespace(overseas_holidays=unittest.mock.Mock())
            runtime = SimpleNamespace(
                cfg=SimpleNamespace(data_dir=tmpdir, universe_markets=["US"]),
                ticker_currency={"AAPL.NAS": "USD"},
                kis_client=kis_client,
                logger=logging.getLogger(__name__),
                us_holidays_cache={},
            )
            service = ScanMarketData(deps=build_market_data_dependencies())

            with patch("sab.market_data_service._current_utc_time", return_value=now):
                service._refresh_us_holidays_if_needed(cast(Any, runtime))

            kis_client.overseas_holidays.assert_not_called()
            self.assertIn("20250101", runtime.us_holidays_cache)

    def test_refresh_us_holidays_calls_api_when_cache_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "holidays_us.json")
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                json.dump({}, cache_file)

            now = dt.datetime(2026, 3, 6, 9, 0, tzinfo=dt.UTC)
            stale = now - dt.timedelta(hours=13)
            os.utime(cache_path, (stale.timestamp(), stale.timestamp()))

            kis_client = SimpleNamespace(
                overseas_holidays=unittest.mock.Mock(
                    return_value=[{"TRD_DT": "20260309", "open_yn": "N"}]
                )
            )
            runtime = SimpleNamespace(
                cfg=SimpleNamespace(data_dir=tmpdir, universe_markets=["US"]),
                ticker_currency={"AAPL.NAS": "USD"},
                kis_client=kis_client,
                logger=logging.getLogger(__name__),
                us_holidays_cache={},
            )
            service = ScanMarketData(deps=build_market_data_dependencies())

            with patch("sab.market_data_service._current_utc_time", return_value=now):
                service._refresh_us_holidays_if_needed(cast(Any, runtime))

            kis_client.overseas_holidays.assert_called_once()
            kwargs = kis_client.overseas_holidays.call_args.kwargs
            self.assertEqual(kwargs.get("country_code"), "US")
            self.assertEqual(kwargs.get("start_date"), "20260306")
            self.assertEqual(kwargs.get("end_date"), "20260316")
            self.assertIn("20260309", runtime.us_holidays_cache)

    def test_refresh_us_holidays_calls_api_when_fresh_cache_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "holidays_us.json")
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                cache_file.write("{")

            now = dt.datetime(2026, 3, 6, 9, 0, tzinfo=dt.UTC)
            os.utime(cache_path, (now.timestamp(), now.timestamp()))

            kis_client = SimpleNamespace(
                overseas_holidays=unittest.mock.Mock(
                    return_value=[{"TRD_DT": "20260309", "open_yn": "N"}]
                )
            )
            runtime = SimpleNamespace(
                cfg=SimpleNamespace(data_dir=tmpdir, universe_markets=["US"]),
                ticker_currency={"AAPL.NAS": "USD"},
                kis_client=kis_client,
                logger=logging.getLogger(__name__),
                us_holidays_cache={},
            )
            service = ScanMarketData(deps=build_market_data_dependencies())

            with patch("sab.market_data_service._current_utc_time", return_value=now):
                service._refresh_us_holidays_if_needed(cast(Any, runtime))

            kis_client.overseas_holidays.assert_called_once()
            self.assertIn("20260309", runtime.us_holidays_cache)


if __name__ == "__main__":
    unittest.main()
