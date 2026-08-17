"""Private, content-addressed ledgers for approved shadow evaluation cases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .contracts import canonical_json_bytes
from .runner import RunKindV0

if TYPE_CHECKING:
    from .shadow_gate import ShadowGateManifestV0

_MAX_LEDGER_BYTES = 8_388_608
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_INPUT_ROOT_FIELDS = {"schema_version", "gate_version", "cases"}
_INPUT_CASE_FIELDS = {"case_id", "run_kind", "sealed_input_hash", "item_id"}
_EXPECTED_ROOT_FIELDS = {"schema_version", "gate_version", "cases"}
_EXPECTED_CASE_FIELDS = {"case_id", "expected_action_set"}
_ACTION_ORDER = {
    "BUY": 0,
    "AVOID": 1,
    "HOLD": 2,
    "SELL": 3,
    "REVIEW": 4,
    "OMITTED": 5,
}
_LANE_ACTIONS = {
    RunKindV0.ENTRY: frozenset({"BUY", "AVOID", "REVIEW", "OMITTED"}),
    RunKindV0.HOLDING: frozenset({"HOLD", "SELL", "REVIEW", "OMITTED"}),
}


class ShadowEvaluationLedgerError(ValueError):
    """One sanitized private-ledger validation failure."""


@dataclass(frozen=True, slots=True)
class ShadowEvaluationCaseV0:
    case_id: str
    run_kind: RunKindV0
    sealed_input_hash: str
    item_id: str
    expected_action_set: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShadowEvaluationLedgerV0:
    gate_version: str
    input_ledger_sha256: str
    expected_action_ledger_sha256: str
    cases: tuple[ShadowEvaluationCaseV0, ...]

    def item_ids_for(
        self,
        *,
        run_kind: RunKindV0,
        sealed_input_hash: str,
    ) -> tuple[str, ...]:
        return tuple(
            case.item_id
            for case in self.cases
            if case.run_kind is run_kind and case.sealed_input_hash == sealed_input_hash
        )


def load_shadow_evaluation_ledger_json_v0(path: str | Path) -> object:
    try:
        raw_bytes = Path(path).read_bytes()
        if len(raw_bytes) > _MAX_LEDGER_BYTES:
            raise ShadowEvaluationLedgerError("shadow ledger exceeds the safe bound")
        return json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON is invalid")
            ),
        )
    except ShadowEvaluationLedgerError:
        raise
    except OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise ShadowEvaluationLedgerError(
            "shadow ledger input is unavailable or invalid"
        ) from None


def validate_shadow_evaluation_ledgers_v0(
    manifest: ShadowGateManifestV0,
    *,
    input_ledger: object,
    expected_action_ledger: object,
) -> ShadowEvaluationLedgerV0:
    from .shadow_gate import ShadowGateManifestV0

    if type(manifest) is not ShadowGateManifestV0:
        raise TypeError("shadow ledger requires an exact gate manifest")
    input_gate_version, input_rows = _validate_input_ledger(input_ledger)
    expected_gate_version, expected_rows = _validate_expected_ledger(
        expected_action_ledger
    )
    if input_gate_version != manifest.gate_version or expected_gate_version != (
        manifest.gate_version
    ):
        raise ShadowEvaluationLedgerError("shadow ledger gate version does not match")
    input_hash = _canonical_hash(input_ledger)
    expected_hash = _canonical_hash(expected_action_ledger)
    if input_hash != manifest.input_ledger_sha256:
        raise ShadowEvaluationLedgerError("shadow input ledger hash does not match")
    if expected_hash != manifest.expected_action_ledger_sha256:
        raise ShadowEvaluationLedgerError(
            "shadow expected-action ledger hash does not match"
        )
    if len(input_rows) != manifest.expected_action_case_count:
        raise ShadowEvaluationLedgerError("shadow ledger case count does not match")
    input_by_id = {row[0]: row for row in input_rows}
    if set(input_by_id) != set(expected_rows):
        raise ShadowEvaluationLedgerError("shadow ledger case identities do not match")
    cases: list[ShadowEvaluationCaseV0] = []
    for case_id, run_kind, sealed_input_hash, item_id in input_rows:
        expected_actions = expected_rows[case_id]
        if any(action not in _LANE_ACTIONS[run_kind] for action in expected_actions):
            raise ShadowEvaluationLedgerError(
                "shadow expected-action set does not match its lane"
            )
        cases.append(
            ShadowEvaluationCaseV0(
                case_id=case_id,
                run_kind=run_kind,
                sealed_input_hash=sealed_input_hash,
                item_id=item_id,
                expected_action_set=expected_actions,
            )
        )
    return ShadowEvaluationLedgerV0(
        gate_version=manifest.gate_version,
        input_ledger_sha256=input_hash,
        expected_action_ledger_sha256=expected_hash,
        cases=tuple(cases),
    )


def load_shadow_evaluation_ledgers_v0(
    manifest: ShadowGateManifestV0,
    *,
    input_ledger_path: str | Path,
    expected_action_ledger_path: str | Path,
) -> ShadowEvaluationLedgerV0:
    return validate_shadow_evaluation_ledgers_v0(
        manifest,
        input_ledger=load_shadow_evaluation_ledger_json_v0(input_ledger_path),
        expected_action_ledger=load_shadow_evaluation_ledger_json_v0(
            expected_action_ledger_path
        ),
    )


def _validate_input_ledger(
    value: object,
) -> tuple[str, tuple[tuple[str, RunKindV0, str, str], ...]]:
    if type(value) is not dict or set(value) != _INPUT_ROOT_FIELDS:
        raise ShadowEvaluationLedgerError("shadow input ledger shape is invalid")
    if value["schema_version"] != "decision-board-shadow-input-ledger.v0":
        raise ShadowEvaluationLedgerError("shadow input ledger schema is invalid")
    gate_version = _identifier(value["gate_version"], "gate version")
    raw_cases = value["cases"]
    if type(raw_cases) is not list or not raw_cases:
        raise ShadowEvaluationLedgerError("shadow input ledger cases are invalid")
    cases: list[tuple[str, RunKindV0, str, str]] = []
    case_ids: set[str] = set()
    identities: set[tuple[RunKindV0, str, str]] = set()
    for raw_case in raw_cases:
        if type(raw_case) is not dict or set(raw_case) != _INPUT_CASE_FIELDS:
            raise ShadowEvaluationLedgerError("shadow input ledger case is invalid")
        case_id = _identifier(raw_case["case_id"], "case id")
        item_id = _identifier(raw_case["item_id"], "item id")
        try:
            run_kind = RunKindV0(raw_case["run_kind"])
        except TypeError, ValueError:
            raise ShadowEvaluationLedgerError(
                "shadow input ledger lane is invalid"
            ) from None
        sealed_input_hash = raw_case["sealed_input_hash"]
        if (
            type(sealed_input_hash) is not str
            or _HASH_PATTERN.fullmatch(sealed_input_hash) is None
        ):
            raise ShadowEvaluationLedgerError("shadow input ledger hash is invalid")
        identity = (run_kind, sealed_input_hash, item_id)
        if case_id in case_ids or identity in identities:
            raise ShadowEvaluationLedgerError(
                "shadow input ledger cases are not unique"
            )
        case_ids.add(case_id)
        identities.add(identity)
        cases.append((case_id, run_kind, sealed_input_hash, item_id))
    if cases != sorted(cases, key=lambda row: row[0].encode("ascii")):
        raise ShadowEvaluationLedgerError("shadow input ledger cases are not ordered")
    return gate_version, tuple(cases)


def _validate_expected_ledger(value: object) -> tuple[str, dict[str, tuple[str, ...]]]:
    if type(value) is not dict or set(value) != _EXPECTED_ROOT_FIELDS:
        raise ShadowEvaluationLedgerError(
            "shadow expected-action ledger shape is invalid"
        )
    if value["schema_version"] != "decision-board-shadow-expected-action-ledger.v0":
        raise ShadowEvaluationLedgerError(
            "shadow expected-action ledger schema is invalid"
        )
    gate_version = _identifier(value["gate_version"], "gate version")
    raw_cases = value["cases"]
    if type(raw_cases) is not list or not raw_cases:
        raise ShadowEvaluationLedgerError(
            "shadow expected-action ledger cases are invalid"
        )
    cases: dict[str, tuple[str, ...]] = {}
    ordered_ids: list[str] = []
    for raw_case in raw_cases:
        if type(raw_case) is not dict or set(raw_case) != _EXPECTED_CASE_FIELDS:
            raise ShadowEvaluationLedgerError(
                "shadow expected-action ledger case is invalid"
            )
        case_id = _identifier(raw_case["case_id"], "case id")
        raw_actions = raw_case["expected_action_set"]
        if (
            type(raw_actions) is not list
            or not raw_actions
            or any(
                type(action) is not str or action not in _ACTION_ORDER
                for action in raw_actions
            )
        ):
            raise ShadowEvaluationLedgerError("shadow expected-action set is invalid")
        actions = tuple(raw_actions)
        if len(actions) != len(set(actions)) or actions != tuple(
            sorted(actions, key=_ACTION_ORDER.__getitem__)
        ):
            raise ShadowEvaluationLedgerError(
                "shadow expected-action set is not canonical"
            )
        if case_id in cases:
            raise ShadowEvaluationLedgerError(
                "shadow expected-action ledger cases are not unique"
            )
        cases[case_id] = actions
        ordered_ids.append(case_id)
    if ordered_ids != sorted(ordered_ids, key=str.encode):
        raise ShadowEvaluationLedgerError(
            "shadow expected-action ledger cases are not ordered"
        )
    return gate_version, cases


def _canonical_hash(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID_PATTERN.fullmatch(value) is None:
        raise ShadowEvaluationLedgerError(f"shadow ledger {label} is invalid")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, field_value in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = field_value
    return value


__all__ = [
    "ShadowEvaluationCaseV0",
    "ShadowEvaluationLedgerError",
    "ShadowEvaluationLedgerV0",
    "load_shadow_evaluation_ledger_json_v0",
    "load_shadow_evaluation_ledgers_v0",
    "validate_shadow_evaluation_ledgers_v0",
]
