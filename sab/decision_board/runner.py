"""Authority-bound request contract for the local Decision Board V0 runner."""

from __future__ import annotations

import json
import re
import stat
import tempfile
import weakref
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

from sab.report.decision_board import (
    DecisionBoardIdempotencyConflictError,
    DecisionBoardStorageError,
    build_decision_board_storage_key,
    parse_decision_board_storage_key,
    write_decision_board_report,
)

from .compiler import (
    ApprovalStateV0,
    DecisionCompilerV0,
    EntryCompilerItemV0,
    EntrySignalStateV0,
    HoldingCompilerItemV0,
    ResearchStateV0,
)
from .contracts import (
    canonical_json_bytes,
    decision_payload_hash,
    validate_decision_board_report,
    validate_decision_payload,
)
from .instruments import InstrumentRefV0, copy_trusted_instrument_ref_v0
from .policy import HoldingResearchSelectionV0
from .results import (
    DecisionRunIssueCodeV0,
    DecisionRunResultV0,
    create_decision_run_blocked_v0,
    create_decision_run_failed_v0,
    create_decision_run_published_v0,
)

_HASH_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PRIVATE_VERSION_SEGMENTS = frozenset(
    {
        "account",
        "credential",
        "password",
        "private",
        "secret",
        "token",
    }
)
_METADATA_FIELDS = frozenset(
    {
        "eligible_count",
        "gate_manifest_sha256",
        "policy_version",
        "registry_version",
        "researcher_version",
        "selected_count",
        "verifier_version",
    }
)
_COUNT_METADATA_FIELDS = frozenset({"eligible_count", "selected_count"})
_MISSING = object()


class RunKindV0(StrEnum):
    ENTRY = "ENTRY"
    HOLDING = "HOLDING"


class UploadModeV0(StrEnum):
    DISABLED = "DISABLED"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"


class DecisionItemEnrichmentOperationalError(RuntimeError):
    """Expected one-item research/provider failure with no private error text."""

    def __init__(self, research_state: ResearchStateV0) -> None:
        if type(self) is not DecisionItemEnrichmentOperationalError:
            raise TypeError("operational enrichment errors must use the exact type")
        if type(research_state) is not ResearchStateV0 or research_state not in {
            ResearchStateV0.TIMEOUT,
            ResearchStateV0.FAILED,
            ResearchStateV0.COVERAGE_GAP,
            ResearchStateV0.STALE,
            ResearchStateV0.CONFLICTED,
        }:
            raise ValueError("operational enrichment failure requires a REVIEW state")
        super().__init__("Decision Board item enrichment failed safely")
        self.research_state = research_state
        _register_operational_error(self, research_state)


class _DecisionItemEnrichmentInvariantError(RuntimeError):
    pass


_OPERATIONAL_ERRORS: dict[
    int,
    tuple[
        weakref.ReferenceType[DecisionItemEnrichmentOperationalError], ResearchStateV0
    ],
] = {}


def _register_operational_error(
    value: DecisionItemEnrichmentOperationalError,
    research_state: ResearchStateV0,
) -> None:
    value_id = id(value)

    def discard(
        reference: weakref.ReferenceType[DecisionItemEnrichmentOperationalError],
    ) -> None:
        current = _OPERATIONAL_ERRORS.get(value_id)
        if current is not None and current[0] is reference:
            _OPERATIONAL_ERRORS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _OPERATIONAL_ERRORS[value_id] = reference, research_state


def _issued_operational_state(
    value: DecisionItemEnrichmentOperationalError,
) -> ResearchStateV0 | None:
    if type(value) is not DecisionItemEnrichmentOperationalError:
        return None
    record = _OPERATIONAL_ERRORS.get(id(value))
    if record is None or record[0]() is not value:
        return None
    issued_state = record[1]
    if type(value.research_state) is not ResearchStateV0:
        return None
    if value.research_state is not issued_state:
        return None
    return issued_state


type CompilerItemV0 = EntryCompilerItemV0 | HoldingCompilerItemV0
type _RequestSnapshotV0 = tuple[object, ...]


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class DecisionRunRequestV0:
    run_kind: RunKindV0
    run_id: str
    idempotency_key: str
    created_at: datetime
    sealed_input_hash: str
    items: tuple[CompilerItemV0, ...]
    selection: HoldingResearchSelectionV0 | None
    upload_mode: UploadModeV0
    metadata: dict[str, str | int]

    def __new__(cls) -> DecisionRunRequestV0:
        del cls
        raise TypeError("Decision Board requests require the trusted factory")


_REQUESTS: dict[
    int, tuple[weakref.ReferenceType[DecisionRunRequestV0], _RequestSnapshotV0]
] = {}


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class RunPreparedV0:
    request: DecisionRunRequestV0

    def __new__(cls) -> RunPreparedV0:
        del cls
        raise TypeError("prepared results require the trusted factory")


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class RunSharedBlockedV0:
    issue_codes: tuple[DecisionRunIssueCodeV0, ...]

    def __new__(cls) -> RunSharedBlockedV0:
        del cls
        raise TypeError("shared blocked results require the trusted factory")


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class RunPreparationFailedV0:
    issue_code: DecisionRunIssueCodeV0

    def __new__(cls) -> RunPreparationFailedV0:
        del cls
        raise TypeError("preparation failures require the trusted factory")


type RunPreparationResultV0 = (
    RunPreparedV0 | RunSharedBlockedV0 | RunPreparationFailedV0
)


@dataclass(frozen=True, slots=True)
class DecisionItemEnrichmentRequestV0:
    run_kind: RunKindV0
    item_id: str
    instrument: InstrumentRefV0

    def to_public_dict(self) -> dict[str, object]:
        return {
            "run_kind": self.run_kind.value,
            "item_id": self.item_id,
            "instrument": self.instrument.to_public_dict(),
        }


class DecisionRunPreparerV0(Protocol):
    def prepare(self, request: DecisionRunRequestV0) -> object: ...


class DecisionItemEnricherV0(Protocol):
    def enrich(self, item: CompilerItemV0, *, request: object) -> object: ...


class DecisionReportUploaderV0(Protocol):
    def upload(self, *, local_path: Path, storage_key: str) -> str: ...


type _PreparationSnapshotV0 = tuple[type[object], object]
_PREPARATION_RESULTS: dict[
    int, tuple[weakref.ReferenceType[object], _PreparationSnapshotV0]
] = {}


def create_run_prepared_v0(request: object) -> RunPreparedV0:
    trusted = _require_request(request)
    value = object.__new__(RunPreparedV0)
    object.__setattr__(value, "request", trusted)
    _register_preparation_result(value)
    return value


def create_run_shared_blocked_v0(
    *issue_codes: DecisionRunIssueCodeV0,
) -> RunSharedBlockedV0:
    if not issue_codes or any(
        type(code) is not DecisionRunIssueCodeV0 for code in issue_codes
    ):
        raise TypeError("shared blocked results require exact nonempty issue codes")
    if any(
        code is not DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE
        for code in issue_codes
    ):
        raise ValueError("issue code is not a shared prerequisite blocker")
    value = object.__new__(RunSharedBlockedV0)
    object.__setattr__(value, "issue_codes", tuple(dict.fromkeys(issue_codes)))
    _register_preparation_result(value)
    return value


def create_run_preparation_failed_v0(
    issue_code: DecisionRunIssueCodeV0,
) -> RunPreparationFailedV0:
    if type(issue_code) is not DecisionRunIssueCodeV0 or issue_code not in {
        DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE,
        DecisionRunIssueCodeV0.PREPARATION_INVALID,
        DecisionRunIssueCodeV0.INTERNAL_ERROR,
    }:
        raise ValueError("issue code is not a preparation failure")
    value = object.__new__(RunPreparationFailedV0)
    object.__setattr__(value, "issue_code", issue_code)
    _register_preparation_result(value)
    return value


def _register_preparation_result(value: object) -> None:
    snapshot = _preparation_snapshot(value)
    assert snapshot is not None
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[object]) -> None:
        current = _PREPARATION_RESULTS.get(value_id)
        if current is not None and current[0] is reference:
            _PREPARATION_RESULTS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _PREPARATION_RESULTS[value_id] = reference, snapshot


def _preparation_snapshot(value: object) -> _PreparationSnapshotV0 | None:
    if type(value) is RunPreparedV0:
        return RunPreparedV0, id(value.request)
    if type(value) is RunSharedBlockedV0:
        if type(value.issue_codes) is not tuple or any(
            type(code) is not DecisionRunIssueCodeV0 for code in value.issue_codes
        ):
            return None
        return RunSharedBlockedV0, value.issue_codes
    if type(value) is RunPreparationFailedV0:
        if type(value.issue_code) is not DecisionRunIssueCodeV0:
            return None
        return RunPreparationFailedV0, value.issue_code
    return None


def _is_issued_preparation_result(value: object) -> bool:
    try:
        record = _PREPARATION_RESULTS.get(id(value))
        return (
            record is not None
            and record[0]() is value
            and _preparation_snapshot(value) == record[1]
        )
    except Exception:
        return False


class DecisionBoardRunnerV0:
    """Aggregate one exact run into one local, notification-free terminal result."""

    def __init__(
        self,
        *,
        preparer: DecisionRunPreparerV0,
        enricher: DecisionItemEnricherV0,
        report_dir: str | Path,
        uploader: DecisionReportUploaderV0 | None = None,
        local_writer: Any = write_decision_board_report,
    ) -> None:
        self._preparer = preparer
        self._enricher = enricher
        self._report_dir = Path(report_dir)
        self._uploader = uploader
        self._local_writer = local_writer

    def run(self, request: object) -> DecisionRunResultV0:
        try:
            trusted_request = _require_request(request)
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
            )
        try:
            preparation = self._preparer.prepare(trusted_request)
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.INTERNAL_ERROR
            )
        try:
            trusted_request = _require_request(trusted_request)
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
            )
        if not _is_issued_preparation_result(preparation):
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
            )
        if type(preparation) is RunPreparationFailedV0:
            return create_decision_run_failed_v0(issue_code=preparation.issue_code)
        if type(preparation) is RunSharedBlockedV0:
            return self._persist_terminal(
                trusted_request,
                envelope=_blocked_envelope(trusted_request, preparation.issue_codes),
            )
        if (
            type(preparation) is not RunPreparedV0
            or preparation.request is not trusted_request
        ):
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.PREPARATION_INVALID
            )
        try:
            enriched_items = self._enrich_items(trusted_request)
            trusted_request = _require_request(trusted_request)
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.ITEM_ENRICHMENT_INVALID
            )
        try:
            if trusted_request.run_kind is RunKindV0.ENTRY:
                entry_items = cast(tuple[EntryCompilerItemV0, ...], enriched_items)
                payload = DecisionCompilerV0.compile_entry(
                    entry_items,
                    sealed_input_hash=trusted_request.sealed_input_hash,
                )
            else:
                holding_items = cast(tuple[HoldingCompilerItemV0, ...], enriched_items)
                payload = DecisionCompilerV0.compile_holding(
                    holding_items,
                    selection=trusted_request.selection,
                    sealed_input_hash=trusted_request.sealed_input_hash,
                )
            trusted_payload = validate_decision_payload(
                json.loads(canonical_json_bytes(payload))
            )
            if (
                trusted_payload["run_kind"] != trusted_request.run_kind.value
                or trusted_payload["sealed_input_hash"]
                != trusted_request.sealed_input_hash
            ):
                raise ValueError("compiler payload identity does not match the request")
            _validate_compiler_universe(trusted_request, trusted_payload)
            trusted_request = _require_request(trusted_request)
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.COMPILER_CONTRACT_INVALID
            )
        return self._persist_terminal(
            trusted_request,
            envelope=_published_envelope(trusted_request, trusted_payload),
        )

    def _enrich_items(
        self, request: DecisionRunRequestV0
    ) -> tuple[CompilerItemV0, ...]:
        selected = (
            {item.item_id for item in request.items}
            if request.run_kind is RunKindV0.ENTRY
            else set(request.selection.selected_item_ids if request.selection else ())
        )
        output: list[CompilerItemV0] = []
        for item in request.items:
            if item.item_id not in selected:
                output.append(item)
                continue
            instrument = copy_trusted_instrument_ref_v0(item.instrument)
            if instrument is None:
                raise TypeError("item instrument authority is invalid")
            enrichment_request = DecisionItemEnrichmentRequestV0(
                run_kind=request.run_kind,
                item_id=item.item_id,
                instrument=instrument,
            )
            try:
                enriched = self._enricher.enrich(item, request=enrichment_request)
            except DecisionItemEnrichmentOperationalError as exc:
                research_state = _issued_operational_state(exc)
                if research_state is None:
                    raise _DecisionItemEnrichmentInvariantError(
                        "operational enrichment error authority is invalid"
                    ) from None
                enriched = _item_with_research_state(item, research_state)
            if enriched is item or not _same_deterministic_item(item, enriched):
                raise _DecisionItemEnrichmentInvariantError(
                    "item enrichment did not preserve exact deterministic facts"
                )
            output.append(cast(CompilerItemV0, enriched))
        return tuple(output)

    def _persist_terminal(
        self,
        request: DecisionRunRequestV0,
        *,
        envelope: object,
    ) -> DecisionRunResultV0:
        try:
            detached = validate_decision_board_report(
                json.loads(canonical_json_bytes(envelope))
            )
            expected_bytes = canonical_json_bytes(detached)
            expected_key = build_decision_board_storage_key(detached)
            parsed = parse_decision_board_storage_key(expected_key, report=detached)
            assert parsed is not None
            self._report_dir.mkdir(parents=True, exist_ok=True)
            directory_identity = _report_directory_identity(self._report_dir)
            returned_path = Path(
                self._local_writer(
                    json.loads(expected_bytes),
                    report_dir=self._report_dir,
                )
            )
            if _report_directory_identity(self._report_dir) != directory_identity:
                raise DecisionBoardStorageError(
                    "report directory identity changed during persistence"
                )
            expected_local_path = self._report_dir / parsed.basename
            if returned_path != expected_local_path:
                raise DecisionBoardStorageError(
                    "local path does not match report identity"
                )
            if returned_path.read_bytes() != expected_bytes:
                raise DecisionBoardStorageError(
                    "local report bytes changed after persistence"
                )
            detached = validate_decision_board_report(json.loads(expected_bytes))
            request = _require_request(request)
        except DecisionBoardIdempotencyConflictError:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.IDEMPOTENCY_CONFLICT
            )
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.LOCAL_PERSISTENCE_FAILED
            )

        storage_key: str | None = None
        upload_issue: DecisionRunIssueCodeV0 | None = None
        upload_mode = request.upload_mode
        if upload_mode is not UploadModeV0.DISABLED:
            if self._uploader is None:
                upload_failed = True
            else:
                try:
                    with tempfile.TemporaryDirectory(
                        prefix="sab-decision-board-upload-"
                    ) as upload_directory:
                        upload_path = Path(upload_directory) / returned_path.name
                        upload_path.write_bytes(expected_bytes)
                        returned_key = self._uploader.upload(
                            local_path=upload_path,
                            storage_key=expected_key,
                        )
                    upload_failed = (
                        type(returned_key) is not str or returned_key != expected_key
                    )
                    if not upload_failed:
                        storage_key = returned_key
                except Exception:
                    upload_failed = True
            try:
                if _report_directory_identity(self._report_dir) != directory_identity:
                    raise DecisionBoardStorageError(
                        "report directory identity changed during upload"
                    )
            except Exception:
                return create_decision_run_failed_v0(
                    issue_code=DecisionRunIssueCodeV0.LOCAL_PERSISTENCE_FAILED
                )
            if upload_failed and upload_mode is UploadModeV0.REQUIRED:
                try:
                    return create_decision_run_failed_v0(
                        issue_code=DecisionRunIssueCodeV0.UPLOAD_FAILED,
                        local_path=returned_path,
                        retained_envelope=detached,
                    )
                except Exception:
                    return create_decision_run_failed_v0(
                        issue_code=DecisionRunIssueCodeV0.LOCAL_PERSISTENCE_FAILED
                    )
            try:
                request = _require_request(request)
            except Exception:
                return create_decision_run_failed_v0(
                    issue_code=DecisionRunIssueCodeV0.LOCAL_PERSISTENCE_FAILED
                )
            if upload_failed:
                upload_issue = DecisionRunIssueCodeV0.UPLOAD_FAILED

        try:
            if detached["status"] == "PUBLISHED":
                return create_decision_run_published_v0(
                    envelope=detached,
                    local_path=returned_path,
                    storage_key=storage_key,
                    upload_issue=upload_issue,
                )
            return create_decision_run_blocked_v0(
                envelope=detached,
                local_path=returned_path,
                storage_key=storage_key,
                upload_issue=upload_issue,
            )
        except Exception:
            return create_decision_run_failed_v0(
                issue_code=DecisionRunIssueCodeV0.LOCAL_PERSISTENCE_FAILED
            )


def create_decision_run_request_v0(
    *,
    existing: object = _MISSING,
    run_kind: object = _MISSING,
    run_id: object = _MISSING,
    idempotency_key: object = _MISSING,
    created_at: object = _MISSING,
    sealed_input_hash: object = _MISSING,
    items: object = _MISSING,
    selection: object = _MISSING,
    upload_mode: object = _MISSING,
    metadata: object = _MISSING,
) -> DecisionRunRequestV0:
    """Issue a request or revalidate one exact unchanged issued request."""

    if existing is not _MISSING:
        value = _require_request(existing)
        if items is not _MISSING and (
            type(items) is not tuple
            or len(items) != len(value.items)
            or any(
                candidate is not expected
                for candidate, expected in zip(items, value.items, strict=True)
            )
        ):
            raise TypeError("request items are not the exact unchanged issued universe")
        supplied = {
            "run_kind": run_kind,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "created_at": created_at,
            "sealed_input_hash": sealed_input_hash,
            "selection": selection,
            "upload_mode": upload_mode,
            "metadata": metadata,
        }
        if any(field is not _MISSING for field in supplied.values()):
            raise TypeError(
                "existing request validation accepts only an exact item universe"
            )
        return value

    required = {
        "run_kind": run_kind,
        "run_id": run_id,
        "idempotency_key": idempotency_key,
        "created_at": created_at,
        "sealed_input_hash": sealed_input_hash,
        "items": items,
        "upload_mode": upload_mode,
        "metadata": metadata,
    }
    missing = [name for name, value in required.items() if value is _MISSING]
    if missing:
        raise TypeError(f"missing Decision Board request fields: {', '.join(missing)}")
    if type(run_kind) is not RunKindV0:
        raise TypeError("run_kind must be an exact RunKindV0")
    if type(upload_mode) is not UploadModeV0:
        raise TypeError("upload_mode must be an exact UploadModeV0")
    trusted_run_id = _required_run_id(run_id)
    trusted_idempotency = _required_hash(idempotency_key, "idempotency_key")
    trusted_sealed_hash = _required_hash(sealed_input_hash, "sealed_input_hash")
    trusted_created_at = _required_utc_datetime(created_at)
    if type(items) is not tuple:
        raise TypeError("items must be an exact tuple")
    trusted_items = items
    trusted_selection = None if selection is _MISSING else selection
    _validate_universe(
        run_kind=run_kind,
        items=trusted_items,
        selection=trusted_selection,
        sealed_input_hash=trusted_sealed_hash,
    )
    selected_count = (
        len(trusted_items)
        if run_kind is RunKindV0.ENTRY
        else len(cast(HoldingResearchSelectionV0, trusted_selection).selected_item_ids)
    )
    trusted_metadata = _required_metadata(
        metadata,
        eligible_count=len(trusted_items),
        selected_count=selected_count,
    )

    value = object.__new__(DecisionRunRequestV0)
    for name, field_value in (
        ("run_kind", run_kind),
        ("run_id", trusted_run_id),
        ("idempotency_key", trusted_idempotency),
        ("created_at", trusted_created_at),
        ("sealed_input_hash", trusted_sealed_hash),
        ("items", trusted_items),
        ("selection", trusted_selection),
        ("upload_mode", upload_mode),
        ("metadata", trusted_metadata),
    ):
        object.__setattr__(value, name, field_value)
    _register_request(value)
    return value


def _report_directory_identity(path: Path) -> tuple[int, int]:
    identity = path.lstat()
    if not stat.S_ISDIR(identity.st_mode):
        raise DecisionBoardStorageError("report directory must be a real directory")
    return identity.st_dev, identity.st_ino


def _validate_universe(
    *,
    run_kind: RunKindV0,
    items: tuple[Any, ...],
    selection: object,
    sealed_input_hash: str,
) -> None:
    if run_kind is RunKindV0.ENTRY:
        if selection is not None:
            raise ValueError("ENTRY request selection must be absent")
        if not all(type(item) is EntryCompilerItemV0 for item in items):
            raise TypeError("ENTRY request requires exact entry compiler items")
        DecisionCompilerV0.compile_entry(items, sealed_input_hash=sealed_input_hash)
        return
    if type(selection) is not HoldingResearchSelectionV0:
        raise ValueError("HOLDING request requires an issued research selection")
    if not all(type(item) is HoldingCompilerItemV0 for item in items):
        raise TypeError("HOLDING request requires exact holding compiler items")
    DecisionCompilerV0.compile_holding(
        items,
        selection=selection,
        sealed_input_hash=sealed_input_hash,
    )


def _validate_compiler_universe(
    request: DecisionRunRequestV0,
    payload: dict[str, Any],
) -> None:
    expected_items = request.items
    if request.run_kind is RunKindV0.ENTRY:
        expected_items = tuple(
            item
            for item in request.items
            if not (
                cast(EntryCompilerItemV0, item).item_state is ApprovalStateV0.APPROVED
                and cast(EntryCompilerItemV0, item).identity_state
                is ApprovalStateV0.APPROVED
                and cast(EntryCompilerItemV0, item).signal_state
                in {
                    EntrySignalStateV0.ABSENT,
                    EntrySignalStateV0.NOT_READY_ENTER,
                }
            )
        )
    expected = {
        canonical_json_bytes(item.instrument.to_public_dict())
        for item in expected_items
    }
    rows = payload["items"]
    actual = [canonical_json_bytes(row["instrument"]) for row in rows]
    if len(actual) != len(set(actual)):
        raise ValueError("compiler payload contains a duplicate instrument")
    actual_set = set(actual)
    if request.run_kind is RunKindV0.ENTRY:
        if actual_set != expected or len(actual) != len(expected):
            raise ValueError(
                "ENTRY compiler payload must preserve every eligible instrument"
            )
        return
    if actual_set != expected or len(actual) != len(expected):
        raise ValueError("HOLDING compiler payload must preserve the full universe")


def _required_run_id(value: object) -> str:
    if type(value) is not str or _RUN_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("run_id must use the conservative public ASCII grammar")
    return value


def _required_hash(value: object, field: str) -> str:
    if type(value) is not str or _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be sha256 plus 64 lowercase hex characters")
    return value


def _required_utc_datetime(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at must be an aware UTC datetime")
    offset = value.utcoffset()
    assert offset is not None
    if offset.total_seconds() != 0:
        raise ValueError("created_at must be UTC")
    return value


def _required_metadata(
    value: object,
    *,
    eligible_count: int,
    selected_count: int,
) -> dict[str, str | int]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("metadata must be an exact public allowlisted mapping")
    unknown = set(value) - _METADATA_FIELDS
    if unknown:
        raise ValueError("metadata contains a non-public or unknown field")
    result: dict[str, str | int] = {}
    for key in sorted(value, key=str.encode):
        field = value[key]
        if key in _COUNT_METADATA_FIELDS:
            if type(field) is not int or field < 0:
                raise ValueError("metadata count values must be non-negative integers")
            expected = eligible_count if key == "eligible_count" else selected_count
            if field != expected:
                raise ValueError("metadata count does not match the issued request")
        elif key == "gate_manifest_sha256":
            if type(field) is not str or _HASH_PATTERN.fullmatch(field) is None:
                raise ValueError("metadata gate manifest hash is invalid")
        elif (
            type(field) is not str
            or _VERSION_PATTERN.fullmatch(field) is None
            or _PRIVATE_VERSION_SEGMENTS.intersection(
                segment.casefold() for segment in re.split(r"[._-]", field)
            )
        ):
            raise ValueError("metadata version uses an unsafe public grammar")
        result[key] = field
    result["eligible_count"] = eligible_count
    result["selected_count"] = selected_count
    return result


def _request_snapshot(value: DecisionRunRequestV0) -> _RequestSnapshotV0 | None:
    try:
        return (
            value.run_kind,
            value.run_id,
            value.idempotency_key,
            value.created_at,
            value.sealed_input_hash,
            tuple(id(item) for item in value.items),
            None if value.selection is None else id(value.selection),
            value.upload_mode,
            id(value.metadata),
            tuple(sorted(value.metadata.items(), key=lambda pair: pair[0].encode())),
        )
    except AttributeError, TypeError, ValueError:
        return None


def _register_request(value: DecisionRunRequestV0) -> None:
    snapshot = _request_snapshot(value)
    assert snapshot is not None
    value_id = id(value)

    def discard(reference: weakref.ReferenceType[DecisionRunRequestV0]) -> None:
        current = _REQUESTS.get(value_id)
        if current is not None and current[0] is reference:
            _REQUESTS.pop(value_id, None)

    reference = weakref.ref(value, discard)
    _REQUESTS[value_id] = reference, snapshot


def _require_request(value: object) -> DecisionRunRequestV0:
    if type(value) is not DecisionRunRequestV0:
        raise TypeError("Decision Board request is not an issued exact value")
    record = _REQUESTS.get(id(value))
    snapshot = _request_snapshot(value)
    if record is None or record[0]() is not value:
        raise TypeError("Decision Board request is not issued")
    if snapshot is None or snapshot != record[1]:
        raise TypeError("Decision Board request is not an unchanged issued value")
    if type(value.run_kind) is not RunKindV0:
        raise TypeError("run_kind must be an exact RunKindV0")
    if type(value.upload_mode) is not UploadModeV0:
        raise TypeError("upload_mode must be an exact UploadModeV0")
    _required_run_id(value.run_id)
    _required_hash(value.idempotency_key, "idempotency_key")
    _required_hash(value.sealed_input_hash, "sealed_input_hash")
    _required_utc_datetime(value.created_at)
    if type(value.items) is not tuple:
        raise TypeError("items must be an exact tuple")
    _validate_universe(
        run_kind=value.run_kind,
        items=value.items,
        selection=value.selection,
        sealed_input_hash=value.sealed_input_hash,
    )
    selected_count = (
        len(value.items)
        if value.run_kind is RunKindV0.ENTRY
        else len(cast(HoldingResearchSelectionV0, value.selection).selected_item_ids)
    )
    validated_metadata = _required_metadata(
        value.metadata,
        eligible_count=len(value.items),
        selected_count=selected_count,
    )
    if validated_metadata != value.metadata:
        raise TypeError("metadata is not the exact issued public mapping")
    return value


def _same_deterministic_item(base: object, enriched: object) -> bool:
    fields: tuple[str, ...]
    if type(base) is EntryCompilerItemV0:
        if type(enriched) is not EntryCompilerItemV0:
            return False
        fields = (
            "item_id",
            "instrument",
            "item_state",
            "identity_state",
            "signal_state",
            "mandate_state",
            "price_state",
            "exposure_state",
        )
    elif type(base) is HoldingCompilerItemV0:
        if type(enriched) is not HoldingCompilerItemV0:
            return False
        fields = (
            "item_id",
            "instrument",
            "item_state",
            "identity_state",
            "hard_exit_state",
            "broker_state",
            "candle_state",
            "rule_state",
            "research_priority",
            "research_order",
        )
    else:
        return False
    return all(getattr(base, field) == getattr(enriched, field) for field in fields)


def _item_with_research_state(
    item: CompilerItemV0,
    research_state: ResearchStateV0,
) -> CompilerItemV0:
    if type(item) is EntryCompilerItemV0:
        return EntryCompilerItemV0.create(
            item_id=item.item_id,
            instrument=item.instrument,
            item_state=item.item_state,
            identity_state=item.identity_state,
            signal_state=item.signal_state,
            mandate_state=item.mandate_state,
            price_state=item.price_state,
            exposure_state=item.exposure_state,
            research_state=research_state,
            evidence=(),
        )
    if type(item) is HoldingCompilerItemV0:
        return HoldingCompilerItemV0.create(
            item_id=item.item_id,
            instrument=item.instrument,
            item_state=item.item_state,
            identity_state=item.identity_state,
            hard_exit_state=item.hard_exit_state,
            broker_state=item.broker_state,
            candle_state=item.candle_state,
            rule_state=item.rule_state,
            research_state=research_state,
            research_priority=item.research_priority,
            research_order=item.research_order,
            evidence=(),
        )
    raise _DecisionItemEnrichmentInvariantError("item lane is invalid")


_ISSUE_MESSAGES = {
    DecisionRunIssueCodeV0.SHARED_PREFLIGHT_UNAVAILABLE: (
        "A shared Decision Board prerequisite is unavailable."
    ),
}


def _issue(code: DecisionRunIssueCodeV0) -> dict[str, str]:
    return {
        "code": code.value,
        "message": _ISSUE_MESSAGES.get(code, "Decision Board run failed safely."),
    }


def _created_at_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _base_envelope(request: DecisionRunRequestV0) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "decision-board.v0",
        "run_id": request.run_id,
        "created_at": _created_at_text(request.created_at),
        "idempotency_key": request.idempotency_key,
        "run_kind": request.run_kind.value,
    }
    if request.metadata:
        envelope["metadata"] = dict(request.metadata)
    return envelope


def _blocked_envelope(
    request: DecisionRunRequestV0,
    issue_codes: tuple[DecisionRunIssueCodeV0, ...],
) -> dict[str, Any]:
    return {
        **_base_envelope(request),
        "status": "BLOCKED",
        "issues": [_issue(code) for code in issue_codes],
    }


def _published_envelope(
    request: DecisionRunRequestV0,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_base_envelope(request),
        "status": "PUBLISHED",
        "issues": [],
        "decision_payload": payload,
        "decision_payload_hash": decision_payload_hash(payload),
    }


__all__ = [
    "CompilerItemV0",
    "DecisionBoardRunnerV0",
    "DecisionItemEnrichmentOperationalError",
    "DecisionItemEnrichmentRequestV0",
    "DecisionRunRequestV0",
    "RunKindV0",
    "RunPreparationFailedV0",
    "RunPreparationResultV0",
    "RunPreparedV0",
    "RunSharedBlockedV0",
    "UploadModeV0",
    "create_decision_run_request_v0",
    "create_run_preparation_failed_v0",
    "create_run_prepared_v0",
    "create_run_shared_blocked_v0",
]
