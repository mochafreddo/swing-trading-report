from __future__ import annotations

from decimal import Decimal

import pytest
from sab.utils.numeric import to_finite_float


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, 12.0),
        (12.5, 12.5),
        ("12.5", 12.5),
        ("-0.25", -0.25),
        (Decimal("12.5"), 12.5),
    ],
)
def test_to_finite_float_returns_float_for_finite_values(
    value: object,
    expected: float,
) -> None:
    assert to_finite_float(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        object(),
        "",
        "not-a-number",
        float("nan"),
        float("inf"),
        float("-inf"),
        "nan",
        "inf",
        "-inf",
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_to_finite_float_rejects_invalid_or_non_finite_values(value: object) -> None:
    assert to_finite_float(value) is None
