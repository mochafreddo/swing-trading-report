"""Decision Board V0 public contract helpers.

The public facade is lazy so importing a leaf module such as
``sab.decision_board.instruments`` cannot eagerly load the compiler and create
an import cycle with ``sab.research``.
"""

# ruff: noqa: F401 -- TYPE_CHECKING imports define the lazy public facade.

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compiler import (
        ApprovalStateV0,
        CompilerEvidenceKindV0,
        CompilerEvidenceV0,
        CompilerInputError,
        DecisionCompilerV0,
        DependencyStateV0,
        EntryCompilerItemV0,
        EntrySignalStateV0,
        ExposureStateV0,
        HardExitStateV0,
        HoldingCompilerItemV0,
        ResearchStateV0,
    )
    from .contracts import (
        ContractError,
        canonical_json_bytes,
        decision_payload_hash,
        load_decision_board_report,
        validate_claim_validation,
        validate_decision_board_report,
        validate_decision_payload,
    )
    from .inputs import (
        ApprovedSwingRefV0,
        EntryIdentityApprovedV0,
        EntryIdentityResultV0,
        EntryIdentityReviewV0,
        IdentityGateIssueV0,
        SwingApprovalResultV0,
        SwingApprovedV0,
        SwingReviewV0,
        approve_swing_snapshot_v0,
        project_research_instruments_v0,
        resolve_entry_identity_v0,
    )
    from .instruments import (
        InstrumentRefV0,
        InstrumentRegistryError,
        VersionedInstrumentRegistryV0,
        copy_trusted_instrument_ref_v0,
    )
    from .policy import (
        MAX_RESEARCH_ITEMS_V0,
        HoldingResearchSelectionV0,
        select_holding_research_v0,
    )

_PUBLIC_MODULES = {
    "MAX_RESEARCH_ITEMS_V0": ".policy",
    "ApprovalStateV0": ".compiler",
    "ApprovedSwingRefV0": ".inputs",
    "CompilerEvidenceKindV0": ".compiler",
    "CompilerEvidenceV0": ".compiler",
    "CompilerInputError": ".compiler",
    "ContractError": ".contracts",
    "DecisionCompilerV0": ".compiler",
    "DependencyStateV0": ".compiler",
    "EntryCompilerItemV0": ".compiler",
    "EntryIdentityApprovedV0": ".inputs",
    "EntryIdentityResultV0": ".inputs",
    "EntryIdentityReviewV0": ".inputs",
    "EntrySignalStateV0": ".compiler",
    "ExposureStateV0": ".compiler",
    "HardExitStateV0": ".compiler",
    "HoldingCompilerItemV0": ".compiler",
    "HoldingResearchSelectionV0": ".policy",
    "IdentityGateIssueV0": ".inputs",
    "InstrumentRefV0": ".instruments",
    "InstrumentRegistryError": ".instruments",
    "ResearchStateV0": ".compiler",
    "SwingApprovalResultV0": ".inputs",
    "SwingApprovedV0": ".inputs",
    "SwingReviewV0": ".inputs",
    "VersionedInstrumentRegistryV0": ".instruments",
    "approve_swing_snapshot_v0": ".inputs",
    "canonical_json_bytes": ".contracts",
    "copy_trusted_instrument_ref_v0": ".instruments",
    "decision_payload_hash": ".contracts",
    "load_decision_board_report": ".contracts",
    "project_research_instruments_v0": ".inputs",
    "resolve_entry_identity_v0": ".inputs",
    "select_holding_research_v0": ".policy",
    "validate_claim_validation": ".contracts",
    "validate_decision_board_report": ".contracts",
    "validate_decision_payload": ".contracts",
}

__all__ = list(_PUBLIC_MODULES)


def __getattr__(name: str) -> object:
    module_name = _PUBLIC_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
