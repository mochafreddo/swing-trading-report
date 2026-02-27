import os
import sys
import types
import unittest
import warnings
from datetime import date
from unittest.mock import patch

from sab.data.us_calendar import _maybe_pandas_holidays, load_us_trading_calendar


class USCalendarTests(unittest.TestCase):
    def test_builtin_contains_key_holidays(self) -> None:
        cal = load_us_trading_calendar()
        self.assertIn("20251127", cal)  # Thanksgiving 2025
        self.assertEqual(cal["20251127"], "Thanksgiving")
        self.assertIn("20250704", cal)  # Independence Day 2025
        self.assertIn("20260619", cal)  # Juneteenth 2026

    def test_pmc_discontinued_break_warning_is_suppressed(self) -> None:
        message = "['break_end', 'break_start'] are discontinued"

        class _FakeTimestamp:
            def __init__(self, value: date) -> None:
                self._value = value

            def date(self) -> date:
                return self._value

        class _FakeHolidays:
            holidays = [_FakeTimestamp(date(2027, 1, 2))]

        class _FakeCalendar:
            def holidays(self) -> _FakeHolidays:
                warnings.warn_explicit(
                    message=message,
                    category=UserWarning,
                    filename="market_calendar.py",
                    lineno=122,
                    module="pandas_market_calendars.market_calendar",
                )
                return _FakeHolidays()

        def _fake_get_calendar(_name: str) -> _FakeCalendar:
            return _FakeCalendar()

        fake_pmc = types.SimpleNamespace(get_calendar=_fake_get_calendar)
        with (
            patch.dict(os.environ, {"SAB_USE_PMC_CALENDAR": "1"}, clear=False),
            patch.dict(sys.modules, {"pandas_market_calendars": fake_pmc}),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            holidays = _maybe_pandas_holidays(2027, 2027)

        self.assertEqual(holidays, {"20270102": "US Market Holiday"})
        self.assertFalse(
            any(
                "break_start" in str(item.message) and "break_end" in str(item.message)
                for item in caught
            )
        )

    def test_non_pmc_warning_with_same_message_is_not_suppressed(self) -> None:
        message = "['break_end', 'break_start'] are discontinued"

        class _FakeTimestamp:
            def __init__(self, value: date) -> None:
                self._value = value

            def date(self) -> date:
                return self._value

        class _FakeHolidays:
            holidays = [_FakeTimestamp(date(2027, 1, 2))]

        class _FakeCalendar:
            def holidays(self) -> _FakeHolidays:
                warnings.warn_explicit(
                    message=message,
                    category=UserWarning,
                    filename="other_source.py",
                    lineno=7,
                    module="custom.calendar",
                )
                return _FakeHolidays()

        def _fake_get_calendar(_name: str) -> _FakeCalendar:
            return _FakeCalendar()

        fake_pmc = types.SimpleNamespace(get_calendar=_fake_get_calendar)
        with (
            patch.dict(os.environ, {"SAB_USE_PMC_CALENDAR": "1"}, clear=False),
            patch.dict(sys.modules, {"pandas_market_calendars": fake_pmc}),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            _maybe_pandas_holidays(2027, 2027)

        self.assertTrue(
            any(
                "break_start" in str(item.message) and "break_end" in str(item.message)
                for item in caught
            )
        )


if __name__ == "__main__":
    unittest.main()
