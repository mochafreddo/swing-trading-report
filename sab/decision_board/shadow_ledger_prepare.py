"""Prepare canonical private shadow ledgers without approval or live access."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .contracts import canonical_json_bytes
from .runner import RunKindV0
from .shadow_gate import ShadowGateManifestV0

_MAX_CASE_PLAN_BYTES = 8_388_608
_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ROOT_FIELDS = {"schema_version", "gate_version", "cases"}
_CASE_FIELDS = {
    "case_id",
    "run_kind",
    "sealed_input_hash",
    "item_id",
    "expected_action_set",
}
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
_INPUT_BASENAME = "decision-board-shadow-input-ledger.json"
_EXPECTED_BASENAME = "decision-board-shadow-expected-action-ledger.json"


class ShadowLedgerPreparationError(ValueError):
    """One sanitized local ledger preparation failure."""


@dataclass(frozen=True, slots=True)
class ShadowPreparedLedgerFileV0:
    basename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ShadowLedgerPreparationResultV0:
    gate_version: str
    case_count: int
    files: tuple[ShadowPreparedLedgerFileV0, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": "LEDGERS_READY",
            "gate_version": self.gate_version,
            "case_count": self.case_count,
            "files": [
                {"basename": file.basename, "sha256": file.sha256}
                for file in self.files
            ],
            "approval_signature_created": False,
            "network_access": False,
            "scheduled": False,
        }


def load_shadow_evaluation_case_plan_v0(path: str | Path) -> object:
    try:
        source = Path(path)
        if not source.is_absolute() or "\x00" in str(source):
            raise OSError
        identity = source.lstat()
        if not stat.S_ISREG(identity.st_mode) or source.is_symlink():
            raise OSError
        descriptor = os.open(
            source,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise OSError
            raw_bytes = stream.read(_MAX_CASE_PLAN_BYTES + 1)
        if len(raw_bytes) > _MAX_CASE_PLAN_BYTES:
            raise ShadowLedgerPreparationError("case plan exceeds the safe bound")
        return json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON is invalid")
            ),
        )
    except ShadowLedgerPreparationError:
        raise
    except OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise ShadowLedgerPreparationError(
            "case plan input is unavailable or invalid"
        ) from None


def prepare_shadow_evaluation_ledgers_v0(
    *,
    manifest: ShadowGateManifestV0,
    case_plan: object,
    output_dir: str | Path,
) -> ShadowLedgerPreparationResultV0:
    if type(manifest) is not ShadowGateManifestV0:
        raise TypeError("ledger preparation requires an exact gate manifest")
    if manifest.approval_state != "PENDING":
        raise ShadowLedgerPreparationError("ledger preparation requires a proposal")
    rows = _validate_case_plan(case_plan, gate_version=manifest.gate_version)
    input_ledger = {
        "schema_version": "decision-board-shadow-input-ledger.v0",
        "gate_version": manifest.gate_version,
        "cases": [
            {
                "case_id": case_id,
                "run_kind": run_kind.value,
                "sealed_input_hash": sealed_input_hash,
                "item_id": item_id,
            }
            for case_id, run_kind, sealed_input_hash, item_id, _actions in rows
        ],
    }
    expected_ledger = {
        "schema_version": "decision-board-shadow-expected-action-ledger.v0",
        "gate_version": manifest.gate_version,
        "cases": [
            {"case_id": case_id, "expected_action_set": list(actions)}
            for case_id, _run_kind, _sealed_hash, _item_id, actions in rows
        ],
    }
    encoded = (
        (_INPUT_BASENAME, canonical_json_bytes(input_ledger)),
        (_EXPECTED_BASENAME, canonical_json_bytes(expected_ledger)),
    )
    destination = _require_new_output_directory(output_dir)
    written: list[Path] = []
    try:
        for basename, payload in encoded:
            target = destination / basename
            with target.open("xb") as stream:
                stream.write(payload)
            written.append(target)
            target.chmod(0o600)
    except Exception:
        for path in written:
            with suppress(OSError):
                path.unlink()
        with suppress(OSError):
            destination.rmdir()
        raise ShadowLedgerPreparationError(
            "prepared ledgers could not be written"
        ) from None
    return ShadowLedgerPreparationResultV0(
        gate_version=manifest.gate_version,
        case_count=len(rows),
        files=tuple(
            ShadowPreparedLedgerFileV0(
                basename=basename,
                sha256=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            )
            for basename, payload in encoded
        ),
    )


def _validate_case_plan(
    value: object,
    *,
    gate_version: str,
) -> tuple[tuple[str, RunKindV0, str, str, tuple[str, ...]], ...]:
    if type(value) is not dict or set(value) != _ROOT_FIELDS:
        raise ShadowLedgerPreparationError("case plan shape is invalid")
    if value["schema_version"] != "decision-board-shadow-case-plan.v0":
        raise ShadowLedgerPreparationError("case plan schema is invalid")
    if value["gate_version"] != gate_version:
        raise ShadowLedgerPreparationError("case plan gate version does not match")
    raw_cases = value["cases"]
    if type(raw_cases) is not list or not raw_cases or len(raw_cases) > 100_000:
        raise ShadowLedgerPreparationError("case plan cases are invalid")
    rows: list[tuple[str, RunKindV0, str, str, tuple[str, ...]]] = []
    case_ids: set[str] = set()
    identities: set[tuple[RunKindV0, str, str]] = set()
    for raw_case in raw_cases:
        if type(raw_case) is not dict or set(raw_case) != _CASE_FIELDS:
            raise ShadowLedgerPreparationError("case plan case is invalid")
        case_id = _identifier(raw_case["case_id"], "case id")
        item_id = _identifier(raw_case["item_id"], "item id")
        try:
            run_kind = RunKindV0(raw_case["run_kind"])
        except TypeError, ValueError:
            raise ShadowLedgerPreparationError("case plan lane is invalid") from None
        sealed_input_hash = raw_case["sealed_input_hash"]
        if (
            type(sealed_input_hash) is not str
            or _HASH_PATTERN.fullmatch(sealed_input_hash) is None
        ):
            raise ShadowLedgerPreparationError("case plan hash is invalid")
        raw_actions = raw_case["expected_action_set"]
        if (
            type(raw_actions) is not list
            or not raw_actions
            or any(
                type(action) is not str or action not in _ACTION_ORDER
                for action in raw_actions
            )
            or len(raw_actions) != len(set(raw_actions))
        ):
            raise ShadowLedgerPreparationError("case plan actions are invalid")
        actions = tuple(sorted(raw_actions, key=_ACTION_ORDER.__getitem__))
        if any(action not in _LANE_ACTIONS[run_kind] for action in actions):
            raise ShadowLedgerPreparationError(
                "case plan actions do not match the lane"
            )
        identity = (run_kind, sealed_input_hash, item_id)
        if case_id in case_ids or identity in identities:
            raise ShadowLedgerPreparationError("case plan cases are not unique")
        case_ids.add(case_id)
        identities.add(identity)
        rows.append((case_id, run_kind, sealed_input_hash, item_id, actions))
    return tuple(sorted(rows, key=lambda row: row[0].encode("ascii")))


def _require_new_output_directory(value: str | Path) -> Path:
    destination: Path | None = None
    created = False
    try:
        destination = Path(value)
        if not destination.is_absolute() or "\x00" in str(destination):
            raise OSError
        parent = destination.parent
        parent_identity = parent.lstat()
        if (
            not stat.S_ISDIR(parent_identity.st_mode)
            or parent.is_symlink()
            or parent_identity.st_uid != os.getuid()
            or stat.S_IMODE(parent_identity.st_mode) & 0o077
        ):
            raise OSError
        destination.mkdir(mode=0o700, exist_ok=False)
        created = True
        destination.chmod(0o700)
        identity = destination.lstat()
    except OSError, TypeError:
        if created and destination is not None:
            with suppress(OSError):
                destination.rmdir()
        raise ShadowLedgerPreparationError(
            "case plan output directory is unavailable"
        ) from None
    if not stat.S_ISDIR(identity.st_mode) or destination.is_symlink():
        raise ShadowLedgerPreparationError("case plan output directory is unavailable")
    return destination


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID_PATTERN.fullmatch(value) is None:
        raise ShadowLedgerPreparationError(f"case plan {label} is invalid")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, field_value in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = field_value
    return value


__all__ = [
    "ShadowLedgerPreparationError",
    "ShadowLedgerPreparationResultV0",
    "ShadowPreparedLedgerFileV0",
    "load_shadow_evaluation_case_plan_v0",
    "prepare_shadow_evaluation_ledgers_v0",
]
