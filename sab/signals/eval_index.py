from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sab.data.us_calendar import load_us_trading_calendar

KR_ZONE = ZoneInfo("Asia/Seoul")
US_ZONE = ZoneInfo("America/New_York")
UTC_ZONE = ZoneInfo("UTC")

STATE_INTRADAY = "INTRADAY"
STATE_PRE_OPEN = "PRE_OPEN"
STATE_AFTER_CLOSE = "AFTER_CLOSE"
STATE_CLOSED = "CLOSED"


@dataclass(frozen=True)
class EvalContext:
    candles: list[dict[str, Any]]
    meta: dict[str, Any]
    now: dt.datetime
    market: str
    session_date: dt.date
    state: str


_US_HOLIDAYS_CACHE: dict[str, bool] | None = None


def _load_us_holidays() -> dict[str, bool]:
    global _US_HOLIDAYS_CACHE
    if _US_HOLIDAYS_CACHE is not None:
        return _US_HOLIDAYS_CACHE

    data_dir = os.getenv("SAB_DATA_DIR") or "data"
    path = os.path.join(data_dir, "holidays_us.json")
    holidays: dict[str, bool] = {}

    # Seed with built-in US calendar.
    for date in load_us_trading_calendar(data_dir):
        holidays[date] = True

    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
            if isinstance(raw, dict):
                for key, value in raw.items():
                    if not isinstance(key, str) or not isinstance(value, dict):
                        continue
                    holidays[key] = not bool(value.get("is_open", True))
    except (OSError, json.JSONDecodeError):
        pass

    _US_HOLIDAYS_CACHE = holidays
    return holidays


def _is_us_holiday(date: dt.date) -> bool:
    holidays = _load_us_holidays()
    entry = holidays.get(date.strftime("%Y%m%d"))
    return bool(entry)


def _ensure_now(now: dt.datetime | None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(tz=UTC_ZONE)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC_ZONE)
    return now


def _to_zone(now: dt.datetime, zone: ZoneInfo) -> dt.datetime:
    return now.astimezone(zone)


def _parse_candle_date(value: Any) -> dt.date | None:
    date_str = str(value or "").strip()
    if not date_str:
        return None
    try:
        return dt.datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        return None


def _infer_market(meta: dict[str, Any]) -> str:
    currency = str(meta.get("currency", "KRW")).upper()
    if currency == "USD":
        return "US"
    return "KR"


def _session_state(market: str, local_now: dt.datetime) -> str:
    weekday = local_now.weekday()  # 0 = Monday
    if weekday >= 5:
        return STATE_CLOSED

    t = local_now.time()
    if market == "US":
        if t < dt.time(9, 30):
            return STATE_PRE_OPEN
        if t < dt.time(16, 0):
            return STATE_INTRADAY
        return STATE_AFTER_CLOSE

    # Default: KR market hours (09:00–15:30)
    if t < dt.time(9, 0):
        return STATE_PRE_OPEN
    if t < dt.time(15, 30):
        return STATE_INTRADAY
    return STATE_AFTER_CLOSE


def choose_eval_index(
    candles: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
    provider: str | None = None,
    now: dt.datetime | None = None,
    lookback_for_volume: int = 5,
    thin_ratio: float = 0.2,
    volume_floor: float = 1_000.0,
) -> tuple[int, bool]:
    """Decide which candle index should be used for evaluation."""
    if not candles:
        return -1, False
    if len(candles) == 1:
        return 0, False

    meta = meta or {}
    provider_hint = (
        str(meta.get("data_source") or meta.get("provider") or provider or "kis")
        .strip()
        .lower()
    )
    if provider_hint == "pykrx":
        return len(candles) - 1, False

    market = _infer_market(meta)
    zone = US_ZONE if market == "US" else KR_ZONE
    aware_now = _ensure_now(now)
    local_now = _to_zone(aware_now, zone)
    state = _session_state(market, local_now)
    session_date = local_now.date()

    idx_latest = len(candles) - 1
    last = candles[-1]
    last_date = _parse_candle_date(last.get("date"))

    # If the latest candle date is earlier than the current session date,
    # we are already looking at the most recent completed bar (e.g., EOD feed).
    if last_date and last_date < session_date:
        return idx_latest, False

    # Compute volume heuristic using only data before the latest candle.
    prev_slice_start = max(0, idx_latest - lookback_for_volume)
    prev_slice = candles[prev_slice_start:idx_latest]
    avg_vol = 0.0
    if prev_slice:
        avg_vol = sum(float(c.get("volume") or 0.0) for c in prev_slice) / len(
            prev_slice
        )
    last_vol = float(last.get("volume") or 0.0)
    very_thin_today = avg_vol > volume_floor and last_vol < avg_vol * thin_ratio

    idx_eval = idx_latest
    is_us_holiday = False
    if market == "US":
        is_us_holiday = _is_us_holiday(session_date)
        if is_us_holiday:
            state = STATE_CLOSED

        if (state == STATE_INTRADAY and last_date == session_date) or (
            state in {STATE_PRE_OPEN, STATE_AFTER_CLOSE}
            and very_thin_today
            and last_date == session_date
        ):
            idx_eval = idx_latest - 1
    else:
        if state == STATE_INTRADAY and very_thin_today and last_date == session_date:
            idx_eval = idx_latest - 1

    if idx_eval < 0:
        idx_eval = 0
    return idx_eval, idx_eval != idx_latest


__all__ = ["choose_eval_index"]
