"""Sanitized local CLI boundary for Decision Board V0 shadow runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_failed_v0,
)
from .runner import RunKindV0, UploadModeV0

if TYPE_CHECKING:
    from .production_adapter import DecisionBoardProductionAdapterV0

_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class DecisionBoardCliConfigV0:
    run_kind: RunKindV0
    run_id: str
    idempotency_key: str
    created_at: datetime
    sealed_input_hash: str
    upload_mode: UploadModeV0
    report_dir: Path

    @classmethod
    def from_strings(
        cls,
        *,
        run_kind: str,
        run_id: str,
        idempotency_key: str,
        created_at: str,
        sealed_input_hash: str,
        upload_mode: str,
        report_dir: str,
    ) -> DecisionBoardCliConfigV0:
        kind = RunKindV0(run_kind.upper())
        mode = UploadModeV0(upload_mode.upper())
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("created_at must include a UTC offset")
        offset = timestamp.utcoffset()
        assert offset is not None
        if offset.total_seconds() != 0:
            raise ValueError("created_at must be UTC")
        if _RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError("run_id is invalid")
        if _HASH_PATTERN.fullmatch(idempotency_key) is None:
            raise ValueError("idempotency_key is invalid")
        if _HASH_PATTERN.fullmatch(sealed_input_hash) is None:
            raise ValueError("sealed_input_hash is invalid")
        return cls(
            run_kind=kind,
            run_id=run_id,
            idempotency_key=idempotency_key,
            created_at=timestamp,
            sealed_input_hash=sealed_input_hash,
            upload_mode=mode,
            report_dir=Path(report_dir),
        )

    def to_public_dict(self) -> dict[str, str]:
        return {
            "run_kind": self.run_kind.value,
            "run_id": self.run_id,
            "idempotency_key": self.idempotency_key,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "sealed_input_hash": self.sealed_input_hash,
            "upload_mode": self.upload_mode.value,
        }


def execute_decision_board_cli_v0(
    config: DecisionBoardCliConfigV0,
    *,
    adapter: DecisionBoardProductionAdapterV0 | None = None,
) -> DecisionRunResultV0:
    """Execute an explicitly injected adapter or retain the fail-closed default."""

    if adapter is None:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
        )
    from .production_adapter import DecisionBoardProductionAdapterV0

    if type(adapter) is not DecisionBoardProductionAdapterV0:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
        )
    return adapter.execute(config)


__all__ = ["DecisionBoardCliConfigV0", "execute_decision_board_cli_v0"]
