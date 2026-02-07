from __future__ import annotations

import json
import os
from datetime import date
from typing import Dict

# KRX holiday seeds (non-exhaustive) for 2024–2026.
_BUILTIN_KR_HOLIDAYS: Dict[str, str] = {
    # 2024 (partial, major closures)
    "20240101": "New Year's Day",
    "20240209": "Lunar New Year",
    "20240212": "Lunar New Year",
    "20240301": "Independence Movement Day",
    "20240506": "Children's Day (observed)",
    "20240606": "Memorial Day",
    "20240815": "Liberation Day",
    "20240916": "Chuseok",
    "20240917": "Chuseok",
    "20240918": "Chuseok",
    "20241003": "National Foundation Day",
    "20241009": "Hangeul Day",
    "20241225": "Christmas",
    # 2025 (partial, major closures)
    "20250101": "New Year's Day",
    "20250127": "Seollal",
    "20250128": "Seollal",
    "20250129": "Seollal",
    "20250301": "Independence Movement Day",
    "20250505": "Children's Day",
    "20250606": "Memorial Day",
    "20250815": "Liberation Day",
    "20251006": "Chuseok",
    "20251007": "Chuseok",
    "20251008": "Chuseok",
    "20251003": "National Foundation Day",
    "20251009": "Hangeul Day",
    "20251225": "Christmas",
    # 2026 (partial, major closures)
    "20260101": "New Year's Day",
    "20260217": "Seollal",
    "20260218": "Seollal",
    "20260219": "Seollal",
    "20260301": "Independence Movement Day",
    "20260505": "Children's Day",
    "20260606": "Memorial Day",
    "20260815": "Liberation Day",
    "20260924": "Chuseok",
    "20260925": "Chuseok",
    "20260926": "Chuseok",
    "20261003": "National Foundation Day",
    "20261009": "Hangeul Day",
    "20261225": "Christmas",
}


def _load_override_file(data_dir: str | None) -> Dict[str, str]:
    if not data_dir:
        return {}
    path = os.path.join(data_dir, "kr_trading_calendar.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
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


def _maybe_pandas_holidays(start_year: int, end_year: int) -> Dict[str, str]:
    use_pandas = os.getenv("SAB_USE_PMC_CALENDAR", "1").strip().lower() not in {"0", "false", "no"}
    if not use_pandas:
        return {}
    try:
        import pandas_market_calendars as pmc  # type: ignore
    except Exception:
        return {}

    cal = pmc.get_calendar("XKRX")
    start_dt = date.fromisoformat(f"{start_year}-01-01")
    end_dt = date.fromisoformat(f"{end_year}-12-31")
    try:
        holidays = cal.holidays()
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for ts in getattr(holidays, "holidays", []):
        try:
            d = ts.date()
        except Exception:
            continue
        if start_dt <= d <= end_dt:
            out[d.strftime("%Y%m%d")] = "KR Market Holiday"
    return out


def load_kr_trading_calendar(data_dir: str | None = None) -> Dict[str, str]:
    overrides = _load_override_file(data_dir)
    merged = dict(_BUILTIN_KR_HOLIDAYS)
    today = date.today()
    max_static_year = 2026
    if today.year > max_static_year:
        merged.update(_maybe_pandas_holidays(today.year, today.year + 5))
    elif today.year >= 2024:
        merged.update(_maybe_pandas_holidays(max_static_year + 1, max_static_year + 5))
    merged.update(overrides)
    return merged


__all__ = ["load_kr_trading_calendar"]
