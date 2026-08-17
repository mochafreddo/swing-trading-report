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
    from .production_adapter import (
        DecisionBoardProductionAdapterV0,
        DecisionBoardProductionComponentsV0,
    )

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
    gate_manifest_sha256: str | None = None
    gate_manifest: Path | None = None
    input_ledger: Path | None = None
    expected_action_ledger: Path | None = None

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
        gate_manifest_sha256: str | None = None,
        gate_manifest: str | None = None,
        input_ledger: str | None = None,
        expected_action_ledger: str | None = None,
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
        if gate_manifest_sha256 is not None and (
            type(gate_manifest_sha256) is not str
            or _HASH_PATTERN.fullmatch(gate_manifest_sha256) is None
        ):
            raise ValueError("gate_manifest_sha256 is invalid")
        gate_paths = (gate_manifest, input_ledger, expected_action_ledger)
        if any(path is not None for path in gate_paths) and not all(
            type(path) is str and bool(path) for path in gate_paths
        ):
            raise ValueError("gate bundle paths must be complete")
        return cls(
            run_kind=kind,
            run_id=run_id,
            idempotency_key=idempotency_key,
            created_at=timestamp,
            sealed_input_hash=sealed_input_hash,
            upload_mode=mode,
            report_dir=Path(report_dir),
            gate_manifest_sha256=gate_manifest_sha256,
            gate_manifest=None if gate_manifest is None else Path(gate_manifest),
            input_ledger=None if input_ledger is None else Path(input_ledger),
            expected_action_ledger=(
                None if expected_action_ledger is None else Path(expected_action_ledger)
            ),
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
    components: DecisionBoardProductionComponentsV0 | None = None,
) -> DecisionRunResultV0:
    """Execute an explicitly injected adapter or retain the fail-closed default."""

    if adapter is not None and components is not None:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
        )
    if components is not None:
        from .production_adapter import (
            DecisionBoardAdapterUnavailableError,
            compose_decision_board_production_adapter_v0,
        )

        try:
            adapter = compose_decision_board_production_adapter_v0(components)
        except DecisionBoardAdapterUnavailableError:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
            )
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
            )
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


def execute_decision_board_shadow_live_cli_v0(
    config: DecisionBoardCliConfigV0,
) -> DecisionRunResultV0:
    """Compose the explicit live boundary or retain a fail-closed result."""

    from .live_runtime import (
        build_decision_board_live_adapter_from_env_v0,
        decision_board_live_claim_model_from_env_v0,
    )
    from .production_adapter import DecisionBoardAdapterUnavailableError
    from .shadow_execution import load_shadow_gate_execution_binding_v0

    try:
        claim_model = decision_board_live_claim_model_from_env_v0()
    except DecisionBoardAdapterUnavailableError:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
        )
    except Exception:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
        )
    try:
        binding = load_shadow_gate_execution_binding_v0(
            config,
            repo_root=Path.cwd(),
            claim_model=claim_model,
        )
    except Exception:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
        )
    try:
        adapter = build_decision_board_live_adapter_from_env_v0()
        if (
            getattr(adapter.evidence_builder.claim_verifier, "model", None)
            != claim_model
        ):
            raise ValueError("live claim model changed during composition")
    except DecisionBoardAdapterUnavailableError:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
        )
    except Exception:
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
        )
    return adapter.execute(config, binding=binding)


__all__ = [
    "DecisionBoardCliConfigV0",
    "execute_decision_board_cli_v0",
    "execute_decision_board_shadow_live_cli_v0",
]
