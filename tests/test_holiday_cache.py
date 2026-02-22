import datetime as dt
import json
import tempfile
import unittest

from sab.data.holiday_cache import (
    HolidayEntry,
    load_cached_holidays,
    lookup_holiday,
    merge_holidays,
)


class HolidayCacheTests(unittest.TestCase):
    def test_merge_handles_multiple_field_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            items = [
                {
                    "base_date": "20250107",
                    "base_event": "Custom Closure",
                    "cntr_div_cd": "N",
                },
                {
                    "TRD_DT": "20250108",
                    "evnt_nm": "Normal Session",
                    "open_yn": "Y",
                },
                # Missing optional fields should not break merge
                {
                    "TRD_DT": "20250109",
                },
                # Non-US entry should be ignored
                {
                    "trd_dt": "20250110",
                    "natn_eng_abrv_cd": "HK",
                    "tr_mket_name": "Hong Kong",
                },
                # US entry using trading date key (not settlement)
                {
                    "trd_dt": "20250111",
                    "natn_eng_abrv_cd": "US",
                    "tr_mket_name": "NYSE",
                    "dmst_sttl_dt": "20250113",
                },
                # US entry with open flag true
                {
                    "trd_dt": "20250112",
                    "tr_natn_cd": "840",
                    "tr_mket_name": "NASDAQ",
                    "open_yn": "Y",
                },
            ]

            merged = merge_holidays(tmpdir, "US", items)

            self.assertIn("20250107", merged)
            self.assertIn("20250108", merged)
            self.assertIn("20250112", merged)
            self.assertNotIn("20250109", merged)
            self.assertNotIn("20250110", merged)
            self.assertNotIn("20250111", merged)

            jan7 = merged["20250107"]
            self.assertIsInstance(jan7, HolidayEntry)
            self.assertEqual(jan7.note, "Custom Closure")
            self.assertFalse(jan7.is_open)

            jan8 = merged["20250108"]
            self.assertEqual(jan8.note, "Normal Session")
            self.assertTrue(jan8.is_open)

            looked_up = lookup_holiday(tmpdir, "US", dt.date(2025, 1, 8))
            self.assertIsNotNone(looked_up)
            assert looked_up is not None
            self.assertTrue(looked_up.is_open)

    def test_merge_filters_suspicious_cached_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Seed a cached file with a suspicious closure (empty note) and a custom valid note.
            suspicious = {
                "20251211": {"note": "", "is_open": False},
                "20251212": {"note": "아멕스", "is_open": False},
                "20251213": {"note": "Custom Closure", "is_open": False},
            }
            cache_path = f"{tmpdir}/holidays_us.json"
            with open(cache_path, "w", encoding="utf-8") as fp:
                json.dump(suspicious, fp)

            merged = merge_holidays(tmpdir, "US", [])

            self.assertNotIn("20251211", merged)
            self.assertNotIn("20251212", merged)
            self.assertIn("20251213", merged)
            self.assertFalse(merged["20251213"].is_open)

    def test_merge_ignores_settlement_only_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            items = [
                # Row resembling settlement schedule (no TRD_DT/open flag)
                {
                    "natn_eng_abrv_cd": "US",
                    "tr_mket_name": "아멕스",
                    "acpl_sttl_dt": "20251218",
                    "dmst_sttl_dt": "20251218",
                }
            ]
            merged = merge_holidays(tmpdir, "US", items)
            self.assertNotIn("20251218", merged)

    def test_load_cached_holidays_returns_empty_for_non_object_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = f"{tmpdir}/holidays_us.json"
            with open(cache_path, "w", encoding="utf-8") as fp:
                json.dump(["invalid", "root"], fp)

            loaded = load_cached_holidays(tmpdir, "US")
            self.assertEqual(loaded, {})

    def test_load_cached_holidays_skips_invalid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = f"{tmpdir}/holidays_us.json"
            payload = {
                "20250101": {"note": "Valid Closure", "is_open": False},
                "bad-date": {"note": "Invalid key", "is_open": False},
                "20250102": {"note": 123, "is_open": False},
                "20250103": {"note": "Bad flag", "is_open": "MAYBE"},
                "20250104": ["not", "an", "object"],
                "20250105": {"note": None, "is_open": "N"},
                "20250106": {"note": "Open day", "is_open": "Y"},
                "20250107": {"note": "Numeric closed", "is_open": 0},
            }
            with open(cache_path, "w", encoding="utf-8") as fp:
                json.dump(payload, fp)

            loaded = load_cached_holidays(tmpdir, "US")

            self.assertSetEqual(
                set(loaded),
                {"20250101", "20250105", "20250106", "20250107"},
            )
            self.assertFalse(loaded["20250101"].is_open)
            self.assertFalse(loaded["20250105"].is_open)
            self.assertTrue(loaded["20250106"].is_open)
            self.assertFalse(loaded["20250107"].is_open)


if __name__ == "__main__":
    unittest.main()
