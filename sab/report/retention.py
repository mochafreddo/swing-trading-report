from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable

from .storage_key import REPORT_RUN_TYPE_PATTERN

_REPORT_KEY_PATTERN = re.compile(
    rf"^\d{{4}}/\d{{2}}/(?P<report_date>\d{{4}}-\d{{2}}-\d{{2}})(?:-\d+)?\.{REPORT_RUN_TYPE_PATTERN}\.json$"
)


def extract_report_date_from_key(key: str) -> dt.date | None:
    match = _REPORT_KEY_PATTERN.fullmatch(key.strip())
    if not match:
        return None

    try:
        return dt.date.fromisoformat(match.group("report_date"))
    except ValueError:
        return None


def select_expired_report_keys(
    keys: Iterable[str],
    *,
    retention_days: int,
    today: dt.date | None = None,
) -> list[str]:
    if retention_days <= 0:
        raise ValueError("retention_days must be > 0")

    reference_day = today or dt.date.today()
    cutoff = reference_day - dt.timedelta(days=retention_days)

    expired_keys: list[str] = []
    for key in keys:
        report_date = extract_report_date_from_key(key)
        if report_date is None:
            continue
        if report_date < cutoff:
            expired_keys.append(key)

    return sorted(expired_keys)


__all__ = ["extract_report_date_from_key", "select_expired_report_keys"]
