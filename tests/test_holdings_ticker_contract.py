from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
from sab.tickers import parse_ticker, validate_strict_holdings_ticker

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_PATH = _ROOT / "tests" / "contracts" / "holding_ticker_cases.json"
_MIGRATION_PATH = (
    _ROOT
    / "supabase"
    / "migrations"
    / "20260306113000_align_holdings_storage_with_app_contract.sql"
)
_SQL_STORAGE_US_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:\.[ABC])?\.(NAS|NYS|AMS)$")


def _load_contract_cases() -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        json.loads(_FIXTURE_PATH.read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize(
    "case",
    _load_contract_cases(),
    ids=lambda case: str(case["input"]),
)
def test_holdings_ticker_contract_fixture(case: dict[str, Any]) -> None:
    issue = validate_strict_holdings_ticker(case["input"])

    if case["valid"]:
        assert issue is None
        assert parse_ticker(case["input"]).ticker == case["canonical"]
        return

    assert issue is not None


def test_holdings_contract_migration_rejects_ambiguous_us_suffix() -> None:
    sql = _MIGRATION_PATH.read_text(encoding="utf-8")

    assert "when 'NASDAQ' then 'NAS'" in sql
    assert "when 'NYSE' then 'NYS'" in sql
    assert "when 'AMEX' then 'AMS'" in sql
    assert "'^[A-Z][A-Z0-9]*(\\.[ABC])?\\.(NAS|NYS|AMS)$'" in sql
    assert re.search(r"where not \(", sql)
    assert re.search(
        r"create unique index(?: if not exists)?\s+holdings_ticker_canonical_unique_idx\s+on public\.holdings",
        sql,
        re.IGNORECASE,
    )


@pytest.mark.parametrize(
    "case",
    _load_contract_cases(),
    ids=lambda case: f"sql-storage-{case['input']}",
)
def test_holdings_contract_storage_fixture(case: dict[str, Any]) -> None:
    if case["valid"]:
        canonical = case["canonical"]
        if canonical.isdigit():
            assert canonical == case["canonical"]
            assert re.fullmatch(r"^\d{6}$", canonical)
        else:
            assert _SQL_STORAGE_US_PATTERN.fullmatch(canonical)
        return

    assert not _SQL_STORAGE_US_PATTERN.fullmatch(case["input"].strip().upper())
