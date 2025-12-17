from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo

from sab.data.holiday_cache import load_cached_holidays
from sab.data.us_calendar import load_us_trading_calendar

STATE_PRE_OPEN = "pre_open"
STATE_INTRADAY = "intraday"
STATE_AFTER_CLOSE = "after_close"
STATE_CLOSED = "closed"


def is_us_market_open(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(tz=ZoneInfo("UTC"))
    ny = now.astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() >= 5:
        return False
    open_time = ny.replace(hour=9, minute=30, second=0, microsecond=0)
    close_time = ny.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_time <= ny <= close_time


def us_market_status(now: dt.datetime | None = None) -> str:
    return "open" if is_us_market_open(now) else "closed"


def us_session_info(
    now: dt.datetime | None = None,
    *,
    data_dir: str | None = None,
) -> dict[str, object]:
    """Return US session state and preferred nday for KIS rank calls.

    preferred_nday:
    - 0 when the prior session has closed (post 16:00 ET same day).
    - 1 when we are pre-open, intraday, weekend, or a known holiday (use last
      confirmed session).
    """
    aware_now = now
    if aware_now is None:
        aware_now = dt.datetime.now(tz=ZoneInfo("UTC"))
    elif aware_now.tzinfo is None:
        aware_now = aware_now.replace(tzinfo=ZoneInfo("UTC"))

    ny_now = aware_now.astimezone(ZoneInfo("America/New_York"))
    session_date = ny_now.date()
    weekday = ny_now.weekday()  # 0=Mon

    data_dir = data_dir or os.getenv("SAB_DATA_DIR") or "data"
    # Load holiday map (built-ins + overrides + cached KIS fetches).
    holidays = load_us_trading_calendar(data_dir)
    cached = load_cached_holidays(data_dir, "US")
    # cached values have is_open flag; treat is_open False as holiday/closure
    for key, entry in cached.items():
        if not entry.is_open:
            holidays[key] = entry.note or holidays.get(key, "")

    is_holiday = session_date.strftime("%Y%m%d") in holidays

    if weekday >= 5 or is_holiday:
        state = STATE_CLOSED
    else:
        t = ny_now.time()
        if t < dt.time(9, 30):
            state = STATE_PRE_OPEN
        elif t < dt.time(16, 0):
            state = STATE_INTRADAY
        else:
            state = STATE_AFTER_CLOSE

    preferred_nday = 0 if state == STATE_AFTER_CLOSE and not is_holiday else 1

    return {
        "state": state,
        "session_date": session_date,
        "is_holiday": is_holiday,
        "preferred_nday": preferred_nday,
        "ny_now": ny_now,
    }


__all__ = [
    "is_us_market_open",
    "us_market_status",
    "us_session_info",
    "STATE_PRE_OPEN",
    "STATE_INTRADAY",
    "STATE_AFTER_CLOSE",
    "STATE_CLOSED",
]
