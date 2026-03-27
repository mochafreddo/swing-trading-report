from __future__ import annotations

from datetime import date

import pytest
from sab.report.storage_key import build_report_storage_key


@pytest.mark.parametrize(
    ("run_type", "expected"),
    [
        ("buy", "2026/02/2026-02-13.buy.json"),
        ("sell", "2026/02/2026-02-13.sell.json"),
        ("entry", "2026/02/2026-02-13.entry.json"),
    ],
)
def test_build_report_storage_key_uses_default_pattern(
    run_type: str, expected: str
) -> None:
    key = build_report_storage_key(report_date=date(2026, 2, 13), run_type=run_type)
    assert key == expected


def test_build_report_storage_key_adds_duplicate_suffix() -> None:
    key = build_report_storage_key(
        report_date=date(2026, 2, 13),
        run_type="buy",
        duplicate_index=3,
    )
    assert key == "2026/02/2026-02-13-3.buy.json"


def test_build_report_storage_key_normalizes_run_type_case() -> None:
    key = build_report_storage_key(report_date=date(2026, 2, 13), run_type=" BUY ")
    assert key == "2026/02/2026-02-13.buy.json"


def test_build_report_storage_key_rejects_unknown_run_type() -> None:
    with pytest.raises(ValueError, match="run_type must be one of"):
        build_report_storage_key(report_date=date(2026, 2, 13), run_type="scan")


def test_build_report_storage_key_rejects_negative_duplicate_index() -> None:
    with pytest.raises(ValueError, match="duplicate_index must be >= 0"):
        build_report_storage_key(
            report_date=date(2026, 2, 13),
            run_type="buy",
            duplicate_index=-1,
        )


@pytest.mark.parametrize("invalid_index", [True, False, "1", 1.5])
def test_build_report_storage_key_rejects_non_int_duplicate_index(
    invalid_index: object,
) -> None:
    with pytest.raises(TypeError, match="duplicate_index must be an int >= 0"):
        build_report_storage_key(
            report_date=date(2026, 2, 13),
            run_type="buy",
            duplicate_index=invalid_index,  # type: ignore[arg-type]
        )
