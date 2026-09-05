from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "portfolio_mandate"
    / "portfolio-mandate-private-v1-preview.synthetic.json"
)
FORBIDDEN_PRIVATE_FIELDS = {
    "account_id",
    "account_number",
    "cost_basis",
    "notes",
    "profit_loss",
    "quantity",
    "raw_payload",
    "tags",
}


def _fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _keys(value: Any) -> set[str]:
    if type(value) is dict:
        return set(value)
    raise AssertionError("expected an object")


def _find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if type(value) is dict:
        found.update(set(value).intersection(FORBIDDEN_PRIVATE_FIELDS))
        for nested in value.values():
            found.update(_find_forbidden_keys(nested))
    elif type(value) is list:
        for nested in value:
            found.update(_find_forbidden_keys(nested))
    return found


def test_t18_synthetic_golden_matches_cross_language_private_preview_contract() -> None:
    fixture = _fixture()

    assert _keys(fixture) == {
        "schema_version",
        "data_mode",
        "decision_date",
        "review_state",
        "portfolio_policy",
        "holdings",
    }
    assert fixture["schema_version"] == "portfolio-mandate-private.v1"
    assert fixture["data_mode"] == "PRIVATE_ZERO_WRITE"
    assert fixture["review_state"]["automation_created"] is False

    holdings = fixture["holdings"]
    assert len(holdings) == 8
    assert sum(holding["role"] == "CORE" for holding in holdings) == 5
    assert sum(holding["role"] == "SATELLITE" for holding in holdings) == 3
    assert all(
        holding["classification_state"] == "ACTIVE"
        and holding["approval_state"] == "APPROVED"
        and holding["horizon"] == "LONG_TERM"
        and holding["addition_policy"]["automatic_orders"] is False
        and holding["addition_policy"]["automatic_reinvestment"] is False
        for holding in holdings
    )

    tickers = [holding["ticker"] for holding in holdings]
    assert len(tickers) == len(set(tickers))
    queue = fixture["portfolio_policy"]["valuation_queue"]
    assert len(queue) == len(set(queue))
    assert set(queue).issubset(tickers)
    assert (
        99
        <= sum(holding["concentration"]["estimated_weight_pct"] for holding in holdings)
        <= 101
    )
    assert set(fixture["portfolio_policy"]["prohibited_operations"]).issuperset(
        {"ORDER_CREATE", "ORDER_MODIFY", "ORDER_CANCEL"}
    )
    assert _find_forbidden_keys(fixture) == set()
