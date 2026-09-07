"""The Web sample remains entirely synthetic and satisfies the existing probe."""

import json
from pathlib import Path

import pytest
from sab.portfolio_mandate.toss_order_probe import _aggregate, _Stop

CASES = json.loads(
    (
        Path(__file__).parent
        / "fixtures/portfolio_mandate/toss-order-decimal-validation.synthetic.json"
    ).read_text()
)


def test_web_order_history_sample_matches_python_probe_contract() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "web/fixtures/toss-order-history.synthetic.json"
        ).read_text()
    )
    assert fixture["mode"] == "SYNTHETIC_ONLY"
    seen = set()
    cursor = None
    for page in fixture["pages"]:
        assert page["requestCursor"] == cursor
        result = page["response"]["result"]
        for order in result["orders"]:
            identity, _, _ = _aggregate(order)
            assert identity.startswith("synthetic-order-")
            assert identity not in seen
            seen.add(identity)
        cursor = result["nextCursor"]
        assert result["hasNext"] == (cursor is not None)
    assert cursor is None
    assert len(seen) == 3


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_order_decimal_validation(case: dict) -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "web/fixtures/toss-order-history.synthetic.json"
        ).read_text()
    )
    order = fixture["pages"][0]["response"]["result"]["orders"][1]
    target = order
    parts = case["field"].split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = case["value"]
    if case["valid"]:
        assert _aggregate(order)[0] == order["orderId"]
    else:
        with pytest.raises(_Stop, match=r"^MALFORMED_PAYLOAD$"):
            _aggregate(order)
