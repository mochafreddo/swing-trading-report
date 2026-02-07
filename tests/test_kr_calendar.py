import unittest

from sab.data.kr_calendar import load_kr_trading_calendar


class KRCalendarTests(unittest.TestCase):
    def test_builtin_contains_2024_key_holidays(self) -> None:
        cal = load_kr_trading_calendar()
        self.assertIn("20240606", cal)  # Memorial Day 2024
        self.assertEqual(cal["20240606"], "Memorial Day")
        self.assertIn("20240815", cal)  # Liberation Day 2024
        self.assertEqual(cal["20240815"], "Liberation Day")


if __name__ == "__main__":
    unittest.main()
