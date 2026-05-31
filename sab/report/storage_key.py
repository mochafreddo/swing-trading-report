from __future__ import annotations

import re
from datetime import date
from typing import Final

REPORT_RUN_TYPES: Final[tuple[str, ...]] = (
    "buy",
    "sell",
    "entry",
    "ai-brief",
    "ai-brief-skip",
)
REPORT_RUN_TYPE_PATTERN: Final[str] = (
    "(?:" + "|".join(re.escape(run_type) for run_type in REPORT_RUN_TYPES) + ")"
)
_ALLOWED_RUN_TYPE_SET: Final[frozenset[str]] = frozenset(REPORT_RUN_TYPES)


def normalize_report_run_type(run_type: str) -> str:
    normalized_run_type = run_type.strip().lower()
    if normalized_run_type not in _ALLOWED_RUN_TYPE_SET:
        allowed = ", ".join(REPORT_RUN_TYPES)
        raise ValueError(f"run_type must be one of: {allowed}")
    return normalized_run_type


def build_report_storage_key(
    *,
    report_date: date,
    run_type: str,
    duplicate_index: int = 0,
) -> str:
    normalized_run_type = normalize_report_run_type(run_type)

    if isinstance(duplicate_index, bool) or not isinstance(duplicate_index, int):
        raise TypeError("duplicate_index must be an int >= 0")

    if duplicate_index < 0:
        raise ValueError("duplicate_index must be >= 0")

    date_part = report_date.isoformat()
    year_part = f"{report_date.year:04d}"
    month_part = f"{report_date.month:02d}"
    suffix = "" if duplicate_index == 0 else f"-{duplicate_index}"
    return f"{year_part}/{month_part}/{date_part}{suffix}.{normalized_run_type}.json"


__all__ = [
    "REPORT_RUN_TYPES",
    "REPORT_RUN_TYPE_PATTERN",
    "build_report_storage_key",
    "normalize_report_run_type",
]
