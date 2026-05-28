from __future__ import annotations

import math
from typing import Any


def to_finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def to_positive_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    parsed = to_finite_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def to_int(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except TypeError, ValueError:
        return default
