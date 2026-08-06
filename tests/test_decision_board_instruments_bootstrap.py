from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path


def test_decision_board_instrument_gate_modules_exist() -> None:
    assert find_spec("sab.decision_board.instruments") is not None
    assert find_spec("sab.decision_board.inputs") is not None


def test_decision_board_package_exports_instrument_gate_api() -> None:
    from sab import decision_board

    assert {
        "InstrumentRefV0",
        "VersionedInstrumentRegistryV0",
        "ApprovedSwingRefV0",
        "approve_swing_snapshot_v0",
        "resolve_entry_identity_v0",
        "project_research_instruments_v0",
    } <= set(decision_board.__all__)


def test_instrument_gate_docs_define_fail_closed_boundary() -> None:
    holdings_docs = Path("docs/holdings-schema.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "REVIEW_STRATEGY_NOT_APPROVED" in holdings_docs
    assert "VersionedInstrumentRegistryV0" in architecture
    assert "ticker suffix" in architecture
    assert "private" in architecture
    assert "deep-immutable" in architecture
    assert "caller-injected `now`" in architecture
    assert "NFC" in architecture
    assert "ASCII-only" in holdings_docs
