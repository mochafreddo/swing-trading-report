from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


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


__all__ = ["is_us_market_open", "us_market_status"]
