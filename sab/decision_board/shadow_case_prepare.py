"""Prepare canonical local shadow snapshots and their private case plan."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .compiler import EntryCompilerItemV0, HoldingCompilerItemV0
from .contracts import canonical_json_bytes, decision_payload_hash
from .policy import select_holding_research_v0
from .runner import RunKindV0, UploadModeV0, create_decision_run_request_v0
from .shadow_gate import ShadowGateManifestV0
from .supabase_request import (
    decode_sealed_request_snapshot_v0,
    parse_sealed_request_snapshot_items_v0,
)

_MAX_CASE_SPEC_BYTES = 8_388_608
_ROOT_FIELDS = {"schema_version", "gate_version", "snapshots"}
_SNAPSHOT_SPEC_FIELDS = {"snapshot", "cases"}
_CASE_FIELDS = {"case_id", "item_id", "expected_action_set"}
_ACTION_ORDER = {
    "BUY": 0,
    "AVOID": 1,
    "HOLD": 2,
    "SELL": 3,
    "REVIEW": 4,
    "OMITTED": 5,
}
_LANE_ACTIONS = {
    "ENTRY": frozenset({"BUY", "AVOID", "REVIEW", "OMITTED"}),
    "HOLDING": frozenset({"HOLD", "SELL", "REVIEW", "OMITTED"}),
}
_CASE_PLAN_BASENAME = "decision-board-shadow-case-plan.json"
_CASE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


class ShadowCasePreparationError(ValueError):
    """One sanitized local shadow case preparation failure."""


@dataclass(frozen=True, slots=True)
class ShadowPreparedCaseFileV0:
    basename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ShadowCasePreparationResultV0:
    gate_version: str
    snapshot_count: int
    case_count: int
    files: tuple[ShadowPreparedCaseFileV0, ...]

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": "SHADOW_CASES_READY",
            "gate_version": self.gate_version,
            "snapshot_count": self.snapshot_count,
            "case_count": self.case_count,
            "files": [
                {"basename": file.basename, "sha256": file.sha256}
                for file in self.files
            ],
            "approval_signature_created": False,
            "network_access": False,
            "scheduled": False,
            "uploaded": False,
        }


def load_shadow_evaluation_case_spec_v0(path: str | Path) -> object:
    try:
        source = Path(path)
        if not source.is_absolute() or "\x00" in str(source):
            raise OSError
        identity = source.lstat()
        if not stat.S_ISREG(identity.st_mode) or source.is_symlink():
            raise OSError
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != os.getuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
            ):
                raise OSError
            raw_bytes = stream.read(_MAX_CASE_SPEC_BYTES + 1)
        if len(raw_bytes) > _MAX_CASE_SPEC_BYTES:
            raise ShadowCasePreparationError("case spec exceeds the safe bound")
        return json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON is invalid")
            ),
        )
    except ShadowCasePreparationError:
        raise
    except OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError:
        raise ShadowCasePreparationError(
            "case spec input is unavailable or invalid"
        ) from None


def prepare_shadow_evaluation_cases_v0(
    *,
    manifest: ShadowGateManifestV0,
    case_spec: object,
    output_dir: str | Path,
) -> ShadowCasePreparationResultV0:
    if type(manifest) is not ShadowGateManifestV0:
        raise TypeError("case preparation requires an exact gate manifest")
    if manifest.approval_state != "PENDING":
        raise ShadowCasePreparationError("case preparation requires a proposal")
    if type(case_spec) is not dict or set(case_spec) != _ROOT_FIELDS:
        raise ShadowCasePreparationError("case spec shape is invalid")
    if case_spec["schema_version"] != "decision-board-shadow-case-spec.v0":
        raise ShadowCasePreparationError("case spec schema is invalid")
    if case_spec["gate_version"] != manifest.gate_version:
        raise ShadowCasePreparationError("case spec gate version does not match")
    raw_snapshots = case_spec["snapshots"]
    if type(raw_snapshots) is not list or not raw_snapshots:
        raise ShadowCasePreparationError("case spec snapshots are invalid")

    snapshot_files: dict[str, bytes] = {}
    case_rows: list[dict[str, object]] = []
    case_ids: set[str] = set()
    covered_run_kinds: set[str] = set()
    for raw_snapshot_spec in raw_snapshots:
        if (
            type(raw_snapshot_spec) is not dict
            or set(raw_snapshot_spec) != _SNAPSHOT_SPEC_FIELDS
        ):
            raise ShadowCasePreparationError("case spec snapshot is invalid")
        try:
            snapshot_bytes = canonical_json_bytes(raw_snapshot_spec["snapshot"])
            snapshot = decode_sealed_request_snapshot_v0(snapshot_bytes)
            run_kind = snapshot["run_kind"]
            if type(run_kind) is not str:
                raise ValueError
            items = parse_sealed_request_snapshot_items_v0(snapshot)
            typed_items = cast(
                tuple[EntryCompilerItemV0 | HoldingCompilerItemV0, ...], items
            )
            raw_items = snapshot["items"]
            if type(raw_items) is not list or len(raw_items) != len(typed_items):
                raise ValueError
            for raw_item, typed_item in zip(raw_items, typed_items, strict=True):
                if (
                    type(raw_item) is not dict
                    or raw_item.get("instrument")
                    != typed_item.instrument.to_public_dict()
                ):
                    raise ValueError
            metadata = snapshot["metadata"]
            if type(metadata) is not dict or "gate_manifest_sha256" in metadata:
                raise ValueError
            lane = RunKindV0(run_kind)
            selection = (
                None
                if lane is RunKindV0.ENTRY
                else select_holding_research_v0(
                    cast(tuple[HoldingCompilerItemV0, ...], items)
                )
            )
            create_decision_run_request_v0(
                run_kind=lane,
                run_id="shadow-case-validation",
                idempotency_key="sha256:" + "0" * 64,
                created_at=datetime(2000, 1, 1, tzinfo=UTC),
                sealed_input_hash=decision_payload_hash(snapshot),
                items=items,
                selection=selection,
                upload_mode=UploadModeV0.DISABLED,
                metadata=metadata,
            )
        except TypeError, ValueError:
            raise ShadowCasePreparationError(
                "case spec sealed snapshot is invalid"
            ) from None
        sealed_hash = decision_payload_hash(snapshot)
        if sealed_hash in snapshot_files:
            raise ShadowCasePreparationError("case spec snapshots are not unique")
        snapshot_files[sealed_hash] = snapshot_bytes
        covered_run_kinds.add(run_kind)
        raw_cases = raw_snapshot_spec["cases"]
        if type(raw_cases) is not list or not raw_cases:
            raise ShadowCasePreparationError("case spec cases are invalid")
        item_ids = {item.item_id for item in typed_items}
        covered_item_ids: set[str] = set()
        for raw_case in raw_cases:
            if type(raw_case) is not dict or set(raw_case) != _CASE_FIELDS:
                raise ShadowCasePreparationError("case spec case is invalid")
            case_id = raw_case["case_id"]
            item_id = raw_case["item_id"]
            actions = raw_case["expected_action_set"]
            if (
                type(case_id) is not str
                or _CASE_ID_PATTERN.fullmatch(case_id) is None
                or case_id in case_ids
                or type(item_id) is not str
                or item_id not in item_ids
                or item_id in covered_item_ids
                or type(actions) is not list
                or not actions
                or any(type(action) is not str for action in actions)
                or len(actions) != len(set(actions))
                or any(action not in _LANE_ACTIONS[run_kind] for action in actions)
            ):
                raise ShadowCasePreparationError("case spec case is invalid")
            case_ids.add(case_id)
            covered_item_ids.add(item_id)
            case_rows.append(
                {
                    "case_id": case_id,
                    "run_kind": run_kind,
                    "sealed_input_hash": sealed_hash,
                    "item_id": item_id,
                    "expected_action_set": sorted(
                        actions, key=_ACTION_ORDER.__getitem__
                    ),
                }
            )
        if covered_item_ids != item_ids:
            raise ShadowCasePreparationError(
                "case spec cases do not cover the snapshot"
            )

    if covered_run_kinds != set(_LANE_ACTIONS):
        raise ShadowCasePreparationError("case spec must cover every gate lane")

    case_plan = {
        "schema_version": "decision-board-shadow-case-plan.v0",
        "gate_version": manifest.gate_version,
        "cases": sorted(case_rows, key=lambda row: str(row["case_id"])),
    }
    case_plan_bytes = canonical_json_bytes(case_plan)
    destination = _require_new_output_directory(output_dir)
    snapshots_dir = destination / "snapshots"
    written: list[Path] = []
    try:
        snapshots_dir.mkdir(mode=0o700)
        snapshots_dir.chmod(0o700)
        case_plan_path = destination / _CASE_PLAN_BASENAME
        _write_private_file(case_plan_path, case_plan_bytes)
        written.append(case_plan_path)
        for sealed_hash, payload in sorted(snapshot_files.items()):
            target = snapshots_dir / f"{sealed_hash.removeprefix('sha256:')}.json"
            _write_private_file(target, payload)
            written.append(target)
    except Exception:
        for path in reversed(written):
            with suppress(OSError):
                path.unlink()
        with suppress(OSError):
            snapshots_dir.rmdir()
        with suppress(OSError):
            destination.rmdir()
        raise ShadowCasePreparationError(
            "prepared shadow cases could not be written"
        ) from None

    files = [
        ShadowPreparedCaseFileV0(
            basename=_CASE_PLAN_BASENAME,
            sha256=f"sha256:{hashlib.sha256(case_plan_bytes).hexdigest()}",
        )
    ]
    files.extend(
        ShadowPreparedCaseFileV0(
            basename=f"snapshots/{sealed_hash.removeprefix('sha256:')}.json",
            sha256=sealed_hash,
        )
        for sealed_hash in sorted(snapshot_files)
    )
    return ShadowCasePreparationResultV0(
        gate_version=manifest.gate_version,
        snapshot_count=len(snapshot_files),
        case_count=len(case_rows),
        files=tuple(files),
    )


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
        raise ShadowCasePreparationError(
            "case spec output directory is unavailable"
        ) from None
    if not stat.S_ISDIR(identity.st_mode) or destination.is_symlink():
        raise ShadowCasePreparationError("case spec output directory is unavailable")
    return destination


def _write_private_file(path: Path, payload: bytes) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(payload)
        path.chmod(0o600)
    except Exception:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(OSError):
            path.unlink()
        raise


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, field_value in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = field_value
    return value


__all__ = [
    "ShadowCasePreparationError",
    "ShadowCasePreparationResultV0",
    "ShadowPreparedCaseFileV0",
    "load_shadow_evaluation_case_spec_v0",
    "prepare_shadow_evaluation_cases_v0",
]
