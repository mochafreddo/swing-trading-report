from __future__ import annotations

import json
import os
from datetime import date

from .calendar_warnings import suppress_pmc_discontinued_break_warning

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
    if not data_dir:
        return {}
    path = os.path.join(data_dir, "us_trading_calendar.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        key_str = str(key or "").replace("-", "")
        if not key_str:
            continue
        note = None
        if isinstance(val, dict):
            note = val.get("note")
        elif isinstance(val, str):
            note = val
        out[key_str] = note or ""
    return out


def _maybe_pandas_holidays(start_year: int, end_year: int) -> dict[str, str]:
    use_pandas = os.getenv("SAB_USE_PMC_CALENDAR", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if not use_pandas:
        return {}
    try:
        import pandas_market_calendars as pmc  # type: ignore
    except Exception:
        return {}

    try:
        with suppress_pmc_discontinued_break_warning():
            cal = pmc.get_calendar("XNYS")
            holidays = cal.holidays()
    except Exception:
        return {}
    start_dt = date.fromisoformat(f"{start_year}-01-01")
    end_dt = date.fromisoformat(f"{end_year}-12-31")
    out: dict[str, str] = {}
    for ts in getattr(holidays, "holidays", []):
        try:
            d = ts.date()
        except Exception:
            continue
        if start_dt <= d <= end_dt:
            out[d.strftime("%Y%m%d")] = "US Market Holiday"
    return out


def load_us_trading_calendar(data_dir: str | None = None) -> dict[str, str]:
    """Return mapping of YYYYMMDD -> note for known US market holidays."""
    overrides = _load_override_file(data_dir)
    merged = dict(_BUILTIN_US_HOLIDAYS)

    # Auto-generate future years using pandas_market_calendars if available.
    today = date.today()
    max_static_year = 2026
    if today.year > max_static_year:
        dyn = _maybe_pandas_holidays(today.year, today.year + 5)
        merged.update(dyn)
    elif today.year >= 2024:
        dyn = _maybe_pandas_holidays(max_static_year + 1, max_static_year + 5)
        merged.update(dyn)

    merged.update(overrides)
    return merged


__all__ = ["load_us_trading_calendar"]
