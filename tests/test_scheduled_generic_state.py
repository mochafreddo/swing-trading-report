from __future__ import annotations

import pytest
from sab.scheduler.generic_state import build_scheduled_state_key


def test_scheduled_state_key_uses_pipeline_kind_scope_and_session_date() -> None:
    assert (
        build_scheduled_state_key(
            pipeline="scan",
            kind="success",
            scope="mixed",
            session_date="2026-06-26",
        )
        == "scheduled-scan:success:MIXED:2026-06-26"
    )


def test_scheduled_state_key_appends_runner_role_and_attempt_id() -> None:
    assert (
        build_scheduled_state_key(
            pipeline="sell",
            kind="ATTEMPT",
            scope="kr",
            session_date="2026-06-26",
            runner_role="local-primary",
            attempt_id="try-1",
        )
        == "scheduled-sell:attempt:KR:2026-06-26:local-primary:try-1"
    )


def test_scheduled_state_key_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="scope must be KR, US, or MIXED"):
        build_scheduled_state_key(
            pipeline="scan",
            kind="success",
            scope="both",
            session_date="2026-06-26",
        )


def test_scheduled_state_key_rejects_unknown_pipeline() -> None:
    with pytest.raises(ValueError, match="pipeline must be scan, sell, or ai-brief"):
        build_scheduled_state_key(
            pipeline="entry",
            kind="success",
            scope="KR",
            session_date="2026-06-26",
        )


def test_scheduled_state_key_rejects_ai_brief_mixed_scope() -> None:
    with pytest.raises(ValueError, match="ai-brief scope must be KR or US"):
        build_scheduled_state_key(
            pipeline="ai-brief",
            kind="success",
            scope="MIXED",
            session_date="2026-06-26",
        )


def test_scheduled_state_key_rejects_unsafe_tokens() -> None:
    with pytest.raises(ValueError, match="kind contains unsafe characters"):
        build_scheduled_state_key(
            pipeline="scan",
            kind="success:latest",
            scope="KR",
            session_date="2026-06-26",
        )


@pytest.mark.parametrize(
    "kind", ["success\n", "success\r", "success\tlatest", " success ", "a*b"]
)
def test_scheduled_state_key_rejects_unsafe_tokens_before_strip(kind: str) -> None:
    with pytest.raises(ValueError, match="kind contains unsafe characters"):
        build_scheduled_state_key(
            pipeline="scan",
            kind=kind,
            scope="KR",
            session_date="2026-06-26",
        )


def test_scheduled_state_key_requires_attempt_suffix_pair() -> None:
    with pytest.raises(
        ValueError, match="runner_role and attempt_id must be provided together"
    ):
        build_scheduled_state_key(
            pipeline="scan",
            kind="attempt",
            scope="KR",
            session_date="2026-06-26",
            runner_role="local-primary",
        )


def test_scheduled_state_key_rejects_suffixes_for_non_attempt_kind() -> None:
    with pytest.raises(
        ValueError,
        match="runner_role and attempt_id are only supported for attempt markers",
    ):
        build_scheduled_state_key(
            pipeline="scan",
            kind="success",
            scope="KR",
            session_date="2026-06-26",
            runner_role="local-primary",
            attempt_id="try-1",
        )
