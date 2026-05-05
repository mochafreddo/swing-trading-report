from __future__ import annotations

from datetime import date

import pytest
from sab.report.retention import (
    extract_report_date_from_key,
    select_expired_report_keys,
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("2026/02/2026-02-14.buy.json", date(2026, 2, 14)),
        ("2026/02/2026-02-14.sell.json", date(2026, 2, 14)),
        ("2026/02/2026-02-14.entry.json", date(2026, 2, 14)),
        ("2026/02/2026-02-14.ai-brief.json", date(2026, 2, 14)),
        ("2026/02/2026-02-14-1.buy.json", date(2026, 2, 14)),
        ("2026/02/2026-02-14-22.sell.json", date(2026, 2, 14)),
    ],
)
def test_extract_report_date_from_key_parses_valid_patterns(
    key: str, expected: date
) -> None:
    assert extract_report_date_from_key(key) == expected


@pytest.mark.parametrize(
    "key",
    [
        "2026/02/2026-02-14.buy.txt",
        "2026/02/2026-0214.buy.json",
        "2026/2/2026-02-14.buy.json",
        "reports/2026/02/2026-02-14.buy.json",
        "2026/02/2026-02-30.buy.json",
        r"2026\02\2026-02-14.buy.json",
    ],
)
def test_extract_report_date_from_key_rejects_invalid_patterns(key: str) -> None:
    assert extract_report_date_from_key(key) is None


def test_select_expired_report_keys_applies_30_day_boundary() -> None:
    keys = [
        "2026/01/2026-01-14.buy.json",
        "2026/01/2026-01-15.buy.json",
        "2026/02/2026-02-14.sell.json",
        "2026/01/2026-01-13-1.sell.json",
    ]

    expired = select_expired_report_keys(
        keys,
        retention_days=30,
        today=date(2026, 2, 14),
    )

    assert expired == [
        "2026/01/2026-01-13-1.sell.json",
        "2026/01/2026-01-14.buy.json",
    ]


@pytest.mark.parametrize("retention_days", [0, -1, -30])
def test_select_expired_report_keys_rejects_non_positive_retention(
    retention_days: int,
) -> None:
    with pytest.raises(ValueError, match="retention_days"):
        select_expired_report_keys(
            ["2026/01/2026-01-14.buy.json"],
            retention_days=retention_days,
            today=date(2026, 2, 14),
        )


def test_select_expired_report_keys_ignores_non_target_json_files() -> None:
    keys = [
        "2026/01/2026-01-01.buy.json",
        "2026/01/2026-01-01.meta.json",
        "2026/01/2026-01-01.buy.json.gz",
        "archive/2026-01-01.buy.json",
    ]

    expired = select_expired_report_keys(
        keys,
        retention_days=30,
        today=date(2026, 2, 14),
    )

    assert expired == ["2026/01/2026-01-01.buy.json"]
