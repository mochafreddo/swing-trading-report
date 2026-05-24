from __future__ import annotations

import datetime as dt
from typing import Any


def normalize_candle_date(value: Any) -> str:
    date_text = str(value or "").strip().replace("-", "")
    return date_text[:8]


def parse_eval_date(value: Any) -> dt.date | None:
    date_text = normalize_candle_date(value)
    if not date_text:
        return None
    try:
        return dt.datetime.strptime(date_text, "%Y%m%d").date()
    except ValueError:
        return None
