from __future__ import annotations

import inspect

import pytest
import sab.decision_board.cli as decision_cli
import sab.decision_board.runner as decision_runner
import sab.decision_board.scheduler as decision_scheduler
from sab.decision_board.results import (
    DecisionRunIssueCodeV0,
    create_decision_run_failed_v0,
)
from sab.decision_board.runner import UploadModeV0


def test_shadow_invokes_once_defaults_no_upload_and_preserves_pipeline_identity() -> (
    None
):
    existing_pipeline_result = object()
    calls: list[UploadModeV0] = []

    def run_once(upload_mode: UploadModeV0):
        calls.append(upload_mode)
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
        )

    preserved, summary = decision_scheduler.run_decision_board_shadow_non_gating_v0(
        existing_pipeline_result,
        run_once,
    )
    assert preserved is existing_pipeline_result
    assert calls == [UploadModeV0.DISABLED]
    assert summary.to_public_dict() == {"status": "FAILED", "exit_code": 2}

    with pytest.raises(TypeError):
        type(summary)()  # type: ignore[call-arg]


def test_shadow_source_has_no_notification_or_order_dependency() -> None:
    source = "\n".join(
        inspect.getsource(module).lower()
        for module in (decision_scheduler, decision_cli, decision_runner)
    )
    for forbidden in (
        "telegram",
        "slack",
        "send_notification",
        "create_order",
        "modify_order",
        "cancel_order",
        "conditional_order",
    ):
        assert forbidden not in source
