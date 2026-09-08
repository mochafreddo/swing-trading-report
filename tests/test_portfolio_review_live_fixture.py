"""The synthetic command boundary validates inputs before touching any database."""

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from scripts.portfolio_review_live_fixture import SyntheticReview


def review_with(sql=None):
    original = Path(
        "tests/fixtures/portfolio_mandate/portfolio-mandate-private-v1-preview.synthetic.json"
    ).read_text()
    packet = {
        "owner_id": str(uuid4()),
        "approvals": [{"source_document": original}],
        "sources": [{"content": "Synthetic PRIMARY source; no provider request."}],
    }
    return SyntheticReview(
        sql or Mock(), {"packet": json.dumps(packet)}, [str(uuid4())]
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"command": "compile"},
        {"command": "DROP TABLE", "request_id": str(uuid4()), "run_id": str(uuid4())},
        {"command": "compile", "request_id": "invalid", "run_id": str(uuid4())},
        {
            "command": "compile",
            "request_id": str(uuid4()),
            "run_id": str(uuid4()),
            "owner_id": str(uuid4()),
        },
    ],
)
def test_invalid_fixture_commands_never_reach_sql(body):
    review = review_with()
    with pytest.raises((ValueError, TypeError)):
        review.command(body)
    review.sql.assert_not_called()


def test_fixture_rejects_non_synthetic_bindings():
    review = review_with()
    review.packet["approvals"][0]["source_document"] = "PRIVATE_SENTINEL"
    with pytest.raises(ValueError, match="SYNTHETIC_BINDINGS_REQUIRED"):
        SyntheticReview(Mock(), {"packet": json.dumps(review.packet)}, review.versions)


def test_stale_selection_and_request_conflict_cannot_write():
    sql = Mock(return_value=json.dumps({"rows": [{"run_id": str(uuid4())}]}))
    review = review_with(sql)
    body = {"command": "unlinked", "request_id": str(uuid4()), "run_id": str(uuid4())}
    with pytest.raises(ValueError, match="STALE_SELECTION"):
        review.command(body)
    assert sql.call_count == 1
    assert "set role authenticated" in sql.call_args.args[0]
    assert "read_portfolio_review_store_r2" in sql.call_args.args[0]
    retry = Mock()
    review.history[body["request_id"]] = (body, retry)
    assert review.command(body) == {"ok": True, "duplicate": True}
    retry.assert_called_once()
    with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
        review.command({**body, "command": "ambiguous"})
    assert retry.call_count == 1


def test_fixture_session_limit_is_bounded_before_database_io():
    review = review_with()
    review.history = {str(uuid4()): ({}, Mock()) for _ in range(128)}
    with pytest.raises(ValueError, match="SESSION_LIMIT"):
        review.command(
            {"command": "compile", "request_id": str(uuid4()), "run_id": str(uuid4())}
        )
    review.sql.assert_not_called()
