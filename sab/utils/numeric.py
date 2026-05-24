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
