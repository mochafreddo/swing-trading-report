from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .kr_calendar import load_kr_trading_calendar
from .us_calendar import load_us_trading_calendar


@dataclass
class HolidayEntry:
    date: str
    note: Optional[str]
    is_open: bool


def _cache_path(cache_dir: str, country_code: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"holidays_{country_code.lower()}.json")


def load_cached_holidays(cache_dir: str, country_code: str) -> Dict[str, HolidayEntry]:
    path = _cache_path(cache_dir, country_code)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}

    entries: Dict[str, HolidayEntry] = {}
    for key, value in data.items():
        entries[key] = HolidayEntry(
            date=key,
            note=value.get("note"),
            is_open=value.get("is_open", True),
        )
    return entries


def save_holidays(cache_dir: str, country_code: str, entries: Dict[str, HolidayEntry]) -> None:
    path = _cache_path(cache_dir, country_code)
    payload = {
        date: {"note": entry.note, "is_open": entry.is_open}
        for date, entry in entries.items()
    }
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)


def merge_holidays(
    cache_dir: str,
    country_code: str,
    fetched: list[dict[str, Any]],
) -> Dict[str, HolidayEntry]:
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
        if lowered in {"amex", "아멕스"}:
            return False
        return True

    cached = {
        date: entry for date, entry in cached_raw.items() if _keep_cached(date, entry, trusted_dates)
    }

    if country == "US":
        for date, note in builtin.items():
            cached[date] = HolidayEntry(date=date, note=note, is_open=False)
    if country == "KR":
        for date, note in builtin.items():
            cached[date] = HolidayEntry(date=date, note=note, is_open=False)

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
) -> Optional[HolidayEntry]:
    entries = load_cached_holidays(cache_dir, country_code)
    return entries.get(date.strftime("%Y%m%d"))


__all__ = [
    "HolidayEntry",
    "load_cached_holidays",
    "save_holidays",
    "merge_holidays",
    "lookup_holiday",
]
