"""One-shot non-gating scheduler seam for local Decision Board shadow runs."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass

from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_failed_v0,
    serialize_decision_run_result_v0,
)
from .runner import UploadModeV0


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class DecisionBoardShadowSummaryV0:
    status: str
    exit_code: int

    def __new__(cls) -> DecisionBoardShadowSummaryV0:
        del cls
        raise TypeError("shadow summaries require the trusted factory")

    def to_public_dict(self) -> dict[str, object]:
        record = _SUMMARIES.get(id(self))
        snapshot = (self.status, self.exit_code)
        if record is None or record[0]() is not self or record[1] != snapshot:
            raise TypeError("shadow summary is not an unchanged issued value")
        return {"status": self.status, "exit_code": self.exit_code}


_SUMMARIES: dict[
    int,
    tuple[weakref.ReferenceType[DecisionBoardShadowSummaryV0], tuple[str, int]],
] = {}


def _summary(result: DecisionRunResultV0) -> DecisionBoardShadowSummaryV0:
    public = serialize_decision_run_result_v0(result)
    status = public["status"]
    exit_code = public["exit_code"]
    if type(status) is not str or type(exit_code) is not int:
        raise TypeError("terminal result summary is invalid")
    value = object.__new__(DecisionBoardShadowSummaryV0)
    object.__setattr__(value, "status", status)
    object.__setattr__(value, "exit_code", exit_code)
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[DecisionBoardShadowSummaryV0]) -> None:
        if _SUMMARIES.get(value_id, (None,))[0] is reference:
            _SUMMARIES.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _SUMMARIES[value_id] = reference, (status, exit_code)
    return value


def run_decision_board_shadow_v0(
    run_once: Callable[[UploadModeV0], DecisionRunResultV0],
) -> DecisionBoardShadowSummaryV0:
    try:
        result = run_once(UploadModeV0.DISABLED)
        return _summary(result)
    except Exception:
        return _summary(
            create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
            )
        )


def run_decision_board_shadow_non_gating_v0(
    existing_pipeline_result: object,
    run_once: Callable[[UploadModeV0], DecisionRunResultV0],
) -> tuple[object, DecisionBoardShadowSummaryV0]:
    summary = run_decision_board_shadow_v0(run_once)
    return existing_pipeline_result, summary


__all__ = [
    "DecisionBoardShadowSummaryV0",
    "run_decision_board_shadow_non_gating_v0",
    "run_decision_board_shadow_v0",
]
