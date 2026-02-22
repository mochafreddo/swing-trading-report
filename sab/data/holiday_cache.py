from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from ..utils.atomic_io import atomic_write_json
from .kr_calendar import load_kr_trading_calendar
from .us_calendar import load_us_trading_calendar

logger = logging.getLogger(__name__)


@dataclass
class HolidayEntry:
    date: str
    note: str | None
    is_open: bool


def _cache_path(cache_dir: str, country_code: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"holidays_{country_code.lower()}.json")


def _parse_is_open(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"Y", "YES", "TRUE", "T", "1", "OPEN"}:
            return True
        if normalized in {"N", "NO", "FALSE", "F", "0", "CLOSE", "CLOSED"}:
            return False
        return None
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        return None
    return None


def load_cached_holidays(cache_dir: str, country_code: str) -> dict[str, HolidayEntry]:
    path = _cache_path(cache_dir, country_code)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring holiday cache %s: root JSON must be an object", path)
        return {}

    entries: dict[str, HolidayEntry] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            logger.warning(
                "Skipping holiday cache entry with non-string key in %s: %r", path, key
            )
            continue
        if len(key) != 8 or not key.isdigit():
            logger.warning(
                "Skipping holiday cache entry with invalid date key in %s: %s",
                path,
                key,
            )
            continue
        if not isinstance(value, dict):
            logger.warning(
                "Skipping holiday cache entry %s in %s: value must be an object",
                key,
                path,
            )
            continue

        note_raw = value.get("note")
        note: str | None
        if note_raw is None:
            note = None
        elif isinstance(note_raw, str):
            note = note_raw
        else:
            logger.warning(
                "Skipping holiday cache entry %s in %s: note must be string or null",
                key,
                path,
            )
            continue

        is_open_raw = value.get("is_open", True)
        is_open = _parse_is_open(is_open_raw)
        if is_open is None:
            logger.warning(
                "Skipping holiday cache entry %s in %s: invalid is_open value %r",
                key,
                path,
                is_open_raw,
            )
            continue

        entries[key] = HolidayEntry(
            date=key,
            note=note,
            is_open=is_open,
        )
    return entries


def save_holidays(
    cache_dir: str,
    country_code: str,
    entries: dict[str, HolidayEntry],
) -> None:
    path = _cache_path(cache_dir, country_code)
    payload = {
        date: {"note": entry.note, "is_open": entry.is_open}
        for date, entry in entries.items()
    }
    atomic_write_json(path, payload, indent=2, ensure_ascii=False)


def merge_holidays(
    cache_dir: str,
    country_code: str,
    fetched: list[dict[str, Any]],
) -> dict[str, HolidayEntry]:
    cached_raw = load_cached_holidays(cache_dir, country_code)
    country = country_code.strip().upper()

    builtin: dict[str, str] = {}
    if country == "US":
        builtin = load_us_trading_calendar(cache_dir)
    if country == "KR":
        builtin = load_kr_trading_calendar(cache_dir)
    trusted_dates = set(builtin)

    # Filter cached entries to avoid stale/suspicious closures (e.g., empty notes).
    def _keep_cached(date: str, entry: HolidayEntry, trusted: set[str]) -> bool:
        note = (entry.note or "").strip()
        if date in trusted:
            return True
        # Drop empty-note closures for unknown dates.
        if not note and not entry.is_open:
            return False
        # Drop obvious noise strings.
        lowered = note.lower()
        return lowered not in {"amex", "아멕스"}

    cached = {
        date: entry
        for date, entry in cached_raw.items()
        if _keep_cached(date, entry, trusted_dates)
    }

    if country == "US":
        for date, builtin_note in builtin.items():
            cached[date] = HolidayEntry(date=date, note=builtin_note, is_open=False)
    if country == "KR":
        for date, builtin_note in builtin.items():
            cached[date] = HolidayEntry(date=date, note=builtin_note, is_open=False)

    for item in fetched:
        natn = str(item.get("natn_eng_abrv_cd") or item.get("tr_natn_cd") or "").upper()
        allowed_natn = {country}
        if country == "US":
            allowed_natn.update({"US", "USA", "840"})
        if country == "KR":
            allowed_natn.update({"KR", "KOR", "410"})
        if natn and natn not in allowed_natn:
            continue

        # Prefer explicit trading date fields. Ignore settlement-only rows to
        # avoid polluting the holiday cache with settlement schedules.
        date = str(
            item.get("trd_dt")
            or item.get("TRD_DT")
            or item.get("base_date")
            or item.get("base_dt")
            or item.get("trd_date")
            or ""
        ).replace("-", "")
        if not date:
            continue
        # Do not allow fetched data to override known calendar dates.
        if date in trusted_dates:
            continue

        event = item.get("base_event") or item.get("evnt_nm") or item.get("note")
        desc = event.strip() if isinstance(event, str) else None
        flag_val = (
            item.get("open_yn")
            or item.get("mket_opn_yn")
            or item.get("cntr_div_cd")
            or item.get("opng_yn")
        )
        if flag_val is None:
            # Without a market-open indicator, only accept rows that clearly
            # describe an event (treat as a closure).
            if not desc:
                continue
            is_open = False
        else:
            is_open = str(flag_val or "N").upper() in {"Y", "OPEN", "1", "T", "TRUE"}

        note = desc or None
        lowered = note.lower() if note else ""
        if lowered in {"amex", "아멕스"}:
            continue
        cached[date] = HolidayEntry(date=date, note=note, is_open=is_open)
    save_holidays(cache_dir, country_code, cached)
    return cached


def lookup_holiday(
    cache_dir: str,
    country_code: str,
    date: dt.date,
) -> HolidayEntry | None:
    entries = load_cached_holidays(cache_dir, country_code)
    return entries.get(date.strftime("%Y%m%d"))


__all__ = [
    "HolidayEntry",
    "load_cached_holidays",
    "save_holidays",
    "merge_holidays",
    "lookup_holiday",
]
