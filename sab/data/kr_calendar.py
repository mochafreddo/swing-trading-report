from __future__ import annotations

from datetime import date

from .trading_calendar import (
    dynamic_holiday_year_range,
    load_calendar_override_file,
    maybe_pandas_holidays,
)

# KRX holiday seeds (non-exhaustive) for 2024–2026.
_BUILTIN_KR_HOLIDAYS: dict[str, str] = {
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


def _load_override_file(data_dir: str | None) -> dict[str, str]:
    return load_calendar_override_file(data_dir, "kr_trading_calendar.json")


def _maybe_pandas_holidays(start_year: int, end_year: int) -> dict[str, str]:
    return maybe_pandas_holidays(
        calendar_name="XKRX",
        holiday_note="KR Market Holiday",
        start_year=start_year,
        end_year=end_year,
    )


def load_kr_trading_calendar(data_dir: str | None = None) -> dict[str, str]:
    overrides = _load_override_file(data_dir)
    merged = dict(_BUILTIN_KR_HOLIDAYS)
    today = date.today()
    max_static_year = 2026
    year_range = dynamic_holiday_year_range(
        today=today,
        max_static_year=max_static_year,
        supplement_static_years=True,
    )
    if year_range is not None:
        merged.update(_maybe_pandas_holidays(*year_range))
    merged.update(overrides)
    return merged


__all__ = ["load_kr_trading_calendar"]
