"""Approved gate and private-ledger binding for one live shadow execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .cli import DecisionBoardCliConfigV0
from .runner import DecisionRunRequestV0
from .shadow_gate import (
    ShadowGateManifestError,
    ShadowGateManifestV0,
    load_shadow_gate_manifest_v0,
    validate_shadow_gate_runtime_v0,
)
from .shadow_ledger import (
    ShadowEvaluationLedgerError,
    ShadowEvaluationLedgerV0,
    load_shadow_evaluation_ledgers_v0,
)


@dataclass(frozen=True, slots=True)
class ShadowGateExecutionBindingV0:
    manifest: ShadowGateManifestV0
    ledger: ShadowEvaluationLedgerV0
    expected_item_ids: tuple[str, ...]


def load_shadow_gate_execution_binding_v0(
    config: DecisionBoardCliConfigV0,
    *,
    repo_root: str | Path,
    claim_model: str,
) -> ShadowGateExecutionBindingV0:
    if type(config) is not DecisionBoardCliConfigV0:
        raise TypeError("shadow execution config must use the exact type")
    if (
        config.gate_manifest is None
        or config.input_ledger is None
        or config.expected_action_ledger is None
        or config.gate_manifest_sha256 is None
    ):
        raise ShadowGateManifestError("shadow execution gate bundle is incomplete")
    manifest = load_shadow_gate_manifest_v0(
        config.gate_manifest,
        require_approved=True,
        input_ledger_path=config.input_ledger,
        expected_action_ledger_path=config.expected_action_ledger,
    )
    if manifest.manifest_sha256 != config.gate_manifest_sha256:
        raise ShadowGateManifestError("shadow execution manifest hash does not match")
    slots = tuple(
        slot
        for slot in manifest.slots
        if slot.run_kind is config.run_kind
        and slot.run_id == config.run_id
        and slot.expected_at == config.created_at
    )
    if len(slots) != 1:
        raise ShadowGateManifestError("shadow execution slot does not match")
    validate_shadow_gate_runtime_v0(
        manifest,
        repo_root=repo_root,
        claim_model=claim_model,
    )
    try:
        ledger = load_shadow_evaluation_ledgers_v0(
            manifest,
            input_ledger_path=config.input_ledger,
            expected_action_ledger_path=config.expected_action_ledger,
        )
    except ShadowEvaluationLedgerError:
        raise ShadowGateManifestError("shadow execution ledgers are invalid") from None
    item_ids = ledger.item_ids_for(
        run_kind=config.run_kind,
        sealed_input_hash=config.sealed_input_hash,
    )
    if not item_ids:
        raise ShadowGateManifestError("shadow execution input is outside the ledger")
    return ShadowGateExecutionBindingV0(
        manifest=manifest,
        ledger=ledger,
        expected_item_ids=item_ids,
    )


def shadow_gate_binding_matches_request_v0(
    binding: ShadowGateExecutionBindingV0,
    request: DecisionRunRequestV0,
) -> bool:
    if (
        type(binding) is not ShadowGateExecutionBindingV0
        or type(request) is not DecisionRunRequestV0
    ):
        return False
    return tuple(sorted(item.item_id for item in request.items)) == tuple(
        sorted(binding.expected_item_ids)
    )


__all__ = [
    "ShadowGateExecutionBindingV0",
    "load_shadow_gate_execution_binding_v0",
    "shadow_gate_binding_matches_request_v0",
]
