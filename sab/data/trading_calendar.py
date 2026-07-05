from __future__ import annotations

import json
import os
from datetime import date

from .calendar_warnings import suppress_pmc_discontinued_break_warning

_DISABLED_ENV_VALUES = {"0", "false", "no"}


class TradingCalendarError(RuntimeError):
    """Raised when a required trading calendar cannot be loaded safely."""


def load_calendar_override_file(data_dir: str | None, filename: str) -> dict[str, str]:
    if not data_dir:
        return {}
    path = os.path.join(data_dir, filename)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
    except OSError, json.JSONDecodeError:
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


def maybe_pandas_holidays(
    *,
    calendar_name: str,
    calendar_label: str | None = None,
    holiday_note: str,
    start_year: int,
    end_year: int,
    required: bool = False,
) -> dict[str, str]:
    label = calendar_label or calendar_name
    use_pandas = (
        os.getenv("SAB_USE_PMC_CALENDAR", "1").strip().lower()
        not in _DISABLED_ENV_VALUES
    )
    if not use_pandas:
        if required:
            raise TradingCalendarError(
                f"{label} trading calendar requires pandas_market_calendars; "
                "SAB_USE_PMC_CALENDAR disables it."
            )
        return {}
    try:
        import pandas_market_calendars as pmc  # type: ignore
    except Exception as exc:
        if required:
            raise TradingCalendarError(
                f"{label} trading calendar requires pandas_market_calendars."
            ) from exc
        return {}

    try:
        with suppress_pmc_discontinued_break_warning():
            cal = pmc.get_calendar(calendar_name)
            holidays = cal.holidays()
    except Exception as exc:
        if required:
            raise TradingCalendarError(
                f"{label} trading calendar could not load holidays "
                f"for {start_year}-{end_year}."
            ) from exc
        return {}
    start_dt = date.fromisoformat(f"{start_year}-01-01")
    end_dt = date.fromisoformat(f"{end_year}-12-31")
    out: dict[str, str] = {}
    for ts in getattr(holidays, "holidays", []):
        d = _holiday_to_date(ts)
        if d is None:
            continue
        if start_dt <= d <= end_dt:
            out[d.strftime("%Y%m%d")] = holiday_note
    if required and not out:
        raise TradingCalendarError(
            f"{label} trading calendar returned no holidays for "
            f"{start_year}-{end_year}."
        )
    return out


def _holiday_to_date(value: object) -> date | None:
    date_method = getattr(value, "date", None)
    if callable(date_method):
        try:
            parsed = date_method()
        except Exception:
            parsed = None
        if isinstance(parsed, date):
            return parsed

    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def dynamic_holiday_year_range(
    *,
    today: date,
    max_static_year: int,
    supplement_static_years: bool = False,
) -> tuple[int, int] | None:
    if today.year > max_static_year:
        return today.year, today.year + 5
    if today.year >= 2024:
        start_year = today.year if supplement_static_years else max_static_year + 1
        return start_year, max_static_year + 5
    return None
