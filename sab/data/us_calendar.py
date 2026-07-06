from __future__ import annotations

from datetime import date

from .trading_calendar import (
    dynamic_holiday_year_range,
    load_calendar_override_file,
    maybe_pandas_holidays,
)

# Built-in US market holiday dates (NYSE/NASDAQ) for 2024–2026.
# Keys are YYYYMMDD, values are human-readable notes.
_BUILTIN_US_HOLIDAYS: dict[str, str] = {
    # 2024
    "20240101": "New Year's Day",
    "20240115": "Martin Luther King Jr. Day",
    "20240219": "Presidents Day",
    "20240329": "Good Friday",
    "20240527": "Memorial Day",
    "20240619": "Juneteenth",
    "20240704": "Independence Day",
    "20240902": "Labor Day",
    "20241128": "Thanksgiving",
    "20241225": "Christmas",
    # 2025
    "20250101": "New Year's Day",
    "20250120": "Martin Luther King Jr. Day",
    "20250217": "Presidents Day",
    "20250418": "Good Friday",
    "20250526": "Memorial Day",
    "20250619": "Juneteenth",
    "20250704": "Independence Day",
    "20250901": "Labor Day",
    "20251127": "Thanksgiving",
    "20251225": "Christmas",
    # 2026
    "20260101": "New Year's Day",
    "20260119": "Martin Luther King Jr. Day",
    "20260216": "Presidents Day",
    "20260403": "Good Friday",
    "20260525": "Memorial Day",
    "20260619": "Juneteenth",
    "20260703": "Independence Day (observed)",
    "20260907": "Labor Day",
    "20261126": "Thanksgiving",
    "20261225": "Christmas",
}


def _load_override_file(data_dir: str | None) -> dict[str, str]:
    return load_calendar_override_file(data_dir, "us_trading_calendar.json")


def _maybe_pandas_holidays(
    start_year: int, end_year: int, *, required: bool = False
) -> dict[str, str]:
    return maybe_pandas_holidays(
        calendar_name="XNYS",
        calendar_label="US",
        holiday_note="US Market Holiday",
        start_year=start_year,
        end_year=end_year,
        required=required,
    )


def load_us_trading_calendar(
    data_dir: str | None = None,
    *,
    required_through_year: int | None = None,
) -> dict[str, str]:
    """Return mapping of YYYYMMDD -> note for known US market holidays."""
    overrides = _load_override_file(data_dir)
    merged = dict(_BUILTIN_US_HOLIDAYS)

    # Auto-generate future years using pandas_market_calendars if available.
    today = date.today()
    max_static_year = 2026
    year_range = dynamic_holiday_year_range(
        today=today,
        max_static_year=max_static_year,
    )
    required_year_range: tuple[int, int] | None = None
    if required_through_year is not None and required_through_year > max_static_year:
        required_year_range = (
            max_static_year + 1,
            max(required_through_year, max_static_year + 5),
        )
        if year_range is None:
            year_range = required_year_range
        else:
            year_range = (
                min(year_range[0], required_year_range[0]),
                max(year_range[1], required_year_range[1]),
            )
    if year_range is not None:
        merged.update(
            _maybe_pandas_holidays(
                *year_range,
                required=bool(required_year_range) or today.year > max_static_year,
            )
        )

    merged.update(overrides)
    return merged


__all__ = ["load_us_trading_calendar"]
