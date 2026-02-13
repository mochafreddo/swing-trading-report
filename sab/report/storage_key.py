from __future__ import annotations

from datetime import date
from typing import Final

_ALLOWED_RUN_TYPES: Final[frozenset[str]] = frozenset({"buy", "sell"})


def build_report_storage_key(
    *,
    report_date: date,
    run_type: str,
    duplicate_index: int = 0,
) -> str:
    normalized_run_type = run_type.strip().lower()
    if normalized_run_type not in _ALLOWED_RUN_TYPES:
        raise ValueError("run_type must be one of: buy, sell")

    if isinstance(duplicate_index, bool) or not isinstance(duplicate_index, int):
        raise TypeError("duplicate_index must be an int >= 0")

    if duplicate_index < 0:
        raise ValueError("duplicate_index must be >= 0")

    date_part = report_date.isoformat()
    year_part = f"{report_date.year:04d}"
    month_part = f"{report_date.month:02d}"
    suffix = "" if duplicate_index == 0 else f"-{duplicate_index}"
    return f"{year_part}/{month_part}/{date_part}{suffix}.{normalized_run_type}.json"


__all__ = ["build_report_storage_key"]
