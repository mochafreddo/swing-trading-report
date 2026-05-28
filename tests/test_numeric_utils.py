from __future__ import annotations

from decimal import Decimal

import pytest
from sab.utils.numeric import to_finite_float, to_int, to_positive_float


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, 12),
        (-3, -3),
        (12.9, 12),
        ("7", 7),
        (" 7 ", 7),
        ("12.5", 12),
        (True, 1),
        (False, 0),
        (Decimal("4.9"), 4),
    ],
)
def test_to_int_coerces_numeric_values(value: object, expected: int) -> None:
    result = to_int(value)
    assert result == expected
    assert isinstance(result, int)


@pytest.mark.parametrize(
    "value",
    [None, object(), "", "not-a-number", "nan"],
)
def test_to_int_returns_default_for_invalid_values(value: object) -> None:
    assert to_int(value) == 0
    assert to_int(value, default=-1) == -1


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, 12.0),
        (0.01, 0.01),
        ("12.5", 12.5),
        (Decimal("12.5"), 12.5),
    ],
)
def test_to_positive_float_returns_float_for_positive_values(
    value: object,
    expected: float,
) -> None:
    assert to_positive_float(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        0.0,
        -0.01,
        -5,
        True,
        False,
        "0",
        "-1",
        "",
        "not-a-number",
        float("nan"),
        float("inf"),
    ],
)
def test_to_positive_float_rejects_non_positive_or_invalid(value: object) -> None:
    assert to_positive_float(value) is None
