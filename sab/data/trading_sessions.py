from __future__ import annotations

import datetime as dt
from typing import Final

from .holiday_cache import load_cached_holidays
from .kr_calendar import load_kr_trading_calendar
from .us_calendar import load_us_trading_calendar

_VALID_MARKETS: Final[set[str]] = {"KR", "US"}


def _normalize_market(market: str) -> str:
    normalized = str(market).strip().upper()
    if normalized not in _VALID_MARKETS:
        raise ValueError(f"market must be one of {sorted(_VALID_MARKETS)}")
    return normalized


def _parse_date_key(value: str) -> dt.date | None:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return dt.datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _load_closed_dates(
    data_dir: str | None,
    market: str,
    *,
    through_year: int | None = None,
) -> set[dt.date]:
    normalized_market = _normalize_market(market)
    data_dir_value = data_dir or "data"

    if normalized_market == "US":
        base_holidays = load_us_trading_calendar(
            data_dir_value,
            required_through_year=through_year,
        )
    else:
        base_holidays = load_kr_trading_calendar(data_dir_value)

    closed_dates: set[dt.date] = set()
    for date_key in base_holidays:
        parsed = _parse_date_key(date_key)
        if parsed is not None:
            closed_dates.add(parsed)

    for date_key, entry in load_cached_holidays(
        data_dir_value, normalized_market
    ).items():
        parsed = _parse_date_key(date_key)
        if parsed is None:
            continue
        if entry.is_open:
            closed_dates.discard(parsed)
        else:
            closed_dates.add(parsed)
    return closed_dates


def is_trading_session(
    session_date: dt.date,
    *,
    market: str,
    data_dir: str | None = None,
) -> bool:
    closed_dates = _load_closed_dates(data_dir, market, through_year=session_date.year)
    if session_date.weekday() >= 5:
        return False
    return session_date not in closed_dates


def count_trading_sessions(
    start_date: dt.date,
    end_date: dt.date,
    *,
    market: str,
    inclusive: bool = True,
    data_dir: str | None = None,
) -> int:
    if end_date < start_date:
        return 0

    closed_dates = _load_closed_dates(data_dir, market, through_year=end_date.year)
    cursor = start_date
    count = 0
    while cursor <= end_date:
        if cursor.weekday() < 5 and cursor not in closed_dates:
            count += 1
        cursor += dt.timedelta(days=1)

    if inclusive:
        return count

    # Exclusive end semantics when inclusive=False.
    if end_date.weekday() < 5 and end_date not in closed_dates:
        return max(0, count - 1)
    return count


__all__ = ["count_trading_sessions", "is_trading_session"]
