"""Read-only progress and quality evaluation for an approved shadow gate."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sab.report.decision_board import build_decision_board_storage_key

from .contracts import canonical_json_bytes, validate_decision_board_report
from .policy import MAX_RESEARCH_ITEMS_V0
from .run_journal_public import PublicJournalReadError, read_public_journal_status_v0
from .shadow_gate import ShadowGateManifestError, load_shadow_gate_manifest_v0
from .shadow_ledger import (
    ShadowEvaluationLedgerError,
    load_shadow_evaluation_ledgers_v0,
)
from .supabase_request import (
    decode_sealed_request_snapshot_v0,
    parse_sealed_request_snapshot_items_v0,
)

_TERMINAL_STATUSES = {
    "PUBLISHED",
    "BLOCKED",
    "FAILED",
    "MISSED_EXPECTED",
    "STALE_INCOMPLETE",
}
_ALL_JOURNAL_STATUSES = _TERMINAL_STATUSES | {"STARTED"}
_MAX_REPORT_BYTES = 1024 * 1024
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
_MAX_MANIFEST_BYTES = 1024 * 1024


class ShadowEvaluationError(RuntimeError):
    """One sanitized evaluation input or contract failure."""


def _utc(value: object) -> datetime:
    if type(value) is not datetime:
        raise ShadowEvaluationError("evaluation timestamp is invalid")
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ShadowEvaluationError("evaluation timestamp must be UTC")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _record_time(value: object) -> datetime | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ShadowEvaluationError("shadow journal timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowEvaluationError("shadow journal timestamp is invalid") from exc
    return _utc(parsed)


def _record_as_of(
    record: dict[str, Any], *, observed_at: datetime
) -> dict[str, Any] | None:
    """Project one immutable journal record to the requested observation time."""

    started_at = _record_time(record.get("started_at"))
    terminal_at = _record_time(record.get("terminal_at"))
    if started_at is not None and started_at > observed_at:
        return None
    if terminal_at is None or terminal_at <= observed_at:
        return record
    if started_at is None:
        return None
    projected = dict(record)
    projected["status"] = "STARTED"
    projected["terminal_at"] = None
    projected["issues"] = []
    projected["report_file"] = None
    return projected


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _private_regular_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size < 2
            or info.st_size > maximum
        ):
            raise ShadowEvaluationError(f"{label} is unsafe")
        payload = path.read_bytes()
        after = path.lstat()
        if len(payload) != info.st_size or (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
            raise ShadowEvaluationError(f"{label} changed while reading")
        return payload
    except ShadowEvaluationError:
        raise
    except OSError as exc:
        raise ShadowEvaluationError(f"{label} is unavailable") from exc


def _load_report(path: Path) -> dict[str, Any]:
    payload = _private_regular_bytes(
        path, maximum=_MAX_REPORT_BYTES, label="shadow report"
    )
    try:
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        report = validate_decision_board_report(raw)
        if canonical_json_bytes(report) != payload:
            raise ShadowEvaluationError("shadow report is noncanonical")
        if Path(build_decision_board_storage_key(report)).name != path.name:
            raise ShadowEvaluationError("shadow report identity is invalid")
        return report
    except ShadowEvaluationError:
        raise
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ShadowEvaluationError("shadow report is invalid") from exc


def _load_snapshot(snapshot_dir: Path, sealed_hash: str) -> dict[str, object]:
    digest = sealed_hash.removeprefix("sha256:")
    path = snapshot_dir / f"{digest}.json"
    payload = _private_regular_bytes(
        path, maximum=_MAX_SNAPSHOT_BYTES, label="sealed snapshot"
    )
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ShadowEvaluationError("sealed snapshot hash is invalid")
    try:
        snapshot = decode_sealed_request_snapshot_v0(payload)
        parse_sealed_request_snapshot_items_v0(snapshot)
        if canonical_json_bytes(snapshot) != payload:
            raise ShadowEvaluationError("sealed snapshot is noncanonical")
        return snapshot
    except ShadowEvaluationError:
        raise
    except (TypeError, ValueError) as exc:
        raise ShadowEvaluationError("sealed snapshot is invalid") from exc


def _load_quality_thresholds(
    manifest_path: str | Path, *, expected_hash: str
) -> dict[str, float]:
    try:
        payload = Path(manifest_path).read_bytes()
        if len(payload) < 2 or len(payload) > _MAX_MANIFEST_BYTES:
            raise ShadowEvaluationError("shadow manifest changed while reading")
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON")
            ),
        )
        if (
            f"sha256:{hashlib.sha256(canonical_json_bytes(raw)).hexdigest()}"
            != expected_hash
        ):
            raise ShadowEvaluationError("shadow manifest changed while reading")
        quality = raw["approved_thresholds"]["quality"]
        if type(quality) is not dict:
            raise ShadowEvaluationError("shadow manifest thresholds are invalid")
        values = {
            "provider_failure_rate_max": quality["provider_failure_rate_max"],
            "research_coverage_rate_min": quality["research_coverage_rate_min"],
            "fresh_source_rate_min": quality["fresh_source_rate_min"],
        }
        if any(type(value) is not float for value in values.values()):
            raise ShadowEvaluationError("shadow manifest thresholds are invalid")
        return values
    except ShadowEvaluationError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise ShadowEvaluationError("shadow manifest thresholds are invalid") from exc


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _threshold_status(
    value: float | None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> str:
    if value is None:
        return "NOT_APPLICABLE"
    if minimum is not None and value < minimum:
        return "BELOW_THRESHOLD"
    if maximum is not None and value > maximum:
        return "ABOVE_THRESHOLD"
    return "MEETS_THRESHOLD"


def _report_case_rows(
    *,
    report: dict[str, Any],
    snapshot: dict[str, object],
    expected_cases: dict[str, tuple[tuple[str, ...], str]],
) -> tuple[list[dict[str, object]], int, int]:
    raw_items = snapshot["items"]
    assert type(raw_items) is list
    report_items = (
        report["decision_payload"]["items"] if report["status"] == "PUBLISHED" else []
    )
    actual_by_identity: dict[bytes, dict[str, Any]] = {}
    for actual_item in report_items:
        identity = canonical_json_bytes(actual_item["instrument"])
        if identity in actual_by_identity:
            raise ShadowEvaluationError("shadow report contains a duplicate instrument")
        actual_by_identity[identity] = actual_item
    rows: list[dict[str, object]] = []
    covered = 0
    fresh_sources = 0
    snapshot_item_ids: set[str] = set()
    snapshot_identities: set[bytes] = set()
    for item in raw_items:
        assert type(item) is dict
        item_id = item["item_id"]
        instrument = item["instrument"]
        assert type(item_id) is str and type(instrument) is dict
        identity = canonical_json_bytes(instrument)
        if item_id in snapshot_item_ids or identity in snapshot_identities:
            raise ShadowEvaluationError("sealed snapshot contains a duplicate item")
        snapshot_item_ids.add(item_id)
        snapshot_identities.add(identity)
        ticker = instrument["canonical_ticker"]
        assert type(ticker) is str
        expected = expected_cases.get(item_id)
        if expected is None:
            raise ShadowEvaluationError("sealed snapshot is not covered by the ledger")
        expected_actions, case_id = expected
        actual_item = actual_by_identity.pop(identity, None)
        if actual_item is None:
            actual_action = "OMITTED"
            issue_codes: list[str] = []
            evidence_count = 0
        else:
            actual_action = (
                actual_item["action"]
                if actual_item["status"] == "DECIDED"
                else "REVIEW"
            )
            issue_codes = [issue["code"] for issue in actual_item["issues"]]
            evidence = actual_item["evidence"]
            evidence_count = len(evidence)
            if evidence_count > 0:
                covered += 1
            fresh_sources += sum(
                reference["freshness"] == "WITHIN_POLICY" for reference in evidence
            )
        rows.append(
            {
                "case_id": case_id,
                "ticker": ticker,
                "actual_action": actual_action,
                "expected_actions": list(expected_actions),
                "expectation": (
                    "MATCH" if actual_action in expected_actions else "MISMATCH"
                ),
                "diff_reason": (
                    None if actual_action in expected_actions else "UNEXPLAINED"
                ),
                "issue_codes": issue_codes,
                "verified_evidence_count": evidence_count,
            }
        )
    if set(expected_cases) != snapshot_item_ids:
        raise ShadowEvaluationError("shadow ledger contains an unknown snapshot item")
    if actual_by_identity:
        raise ShadowEvaluationError("shadow report contains an unknown instrument")
    return rows, covered, fresh_sources


def evaluate_shadow_gate_v0(
    *,
    manifest_path: str | Path,
    input_ledger_path: str | Path,
    expected_action_ledger_path: str | Path,
    snapshot_dir: str | Path,
    journal_dir: str | Path,
    report_dir: str | Path,
    as_of: datetime,
) -> dict[str, object]:
    """Build one reproducible, read-only evaluation snapshot."""

    observed_at = _utc(as_of)
    try:
        manifest = load_shadow_gate_manifest_v0(
            manifest_path,
            require_approved=True,
            input_ledger_path=input_ledger_path,
            expected_action_ledger_path=expected_action_ledger_path,
        )
        ledger = load_shadow_evaluation_ledgers_v0(
            manifest,
            input_ledger_path=input_ledger_path,
            expected_action_ledger_path=expected_action_ledger_path,
        )
        journal = read_public_journal_status_v0(
            str(journal_dir),
            limit=1000,
            statuses=_ALL_JOURNAL_STATUSES,
            scan_limit=1000,
            max_record_bytes=64 * 1024,
            max_output_bytes=1024 * 1024,
        )
    except (
        ShadowGateManifestError,
        ShadowEvaluationLedgerError,
        PublicJournalReadError,
    ) as exc:
        raise ShadowEvaluationError("shadow evaluation inputs are invalid") from exc

    quality_thresholds = _load_quality_thresholds(
        manifest_path, expected_hash=manifest.manifest_sha256
    )
    source_records = journal["records"]
    assert type(source_records) is list
    records = [
        projected
        for record in source_records
        if (projected := _record_as_of(record, observed_at=observed_at)) is not None
    ]
    by_identity = {
        (record["run_kind"], record["expected_at"], record["run_id"]): record
        for record in records
    }
    if len(by_identity) != len(records):
        raise ShadowEvaluationError("shadow journal identities are not unique")

    expected_by_lane_hash: dict[
        tuple[str, str], dict[str, tuple[tuple[str, ...], str]]
    ] = defaultdict(dict)
    for case in ledger.cases:
        expected_by_lane_hash[(case.run_kind.value, case.sealed_input_hash)][
            case.item_id
        ] = (case.expected_action_set, case.case_id)

    report_root = Path(report_dir)
    snapshots = Path(snapshot_dir)
    slot_rows: list[dict[str, object]] = []
    case_rows: list[dict[str, object]] = []
    journal_statuses: Counter[str] = Counter()
    invalid_publications = 0
    unexplained_diffs = 0
    provider_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    lane_quality_counts: dict[str, Counter[str]] = defaultdict(Counter)
    lane_coverage_unavailable: set[str] = set()
    eligible_items = 0
    covered_items = 0
    verified_sources = 0
    fresh_sources = 0
    research_coverage_unavailable = False

    for slot in manifest.slots:
        expected_at = _timestamp(slot.expected_at)
        identity = (slot.run_kind.value, expected_at, slot.run_id)
        record = by_identity.get(identity)
        deadline = slot.expected_at + timedelta(seconds=manifest.grace_seconds)
        if record is None:
            slot_state = "DUE_MISSING" if observed_at >= deadline else "SCHEDULED"
            diff_reason = "UNEXPLAINED" if slot_state == "DUE_MISSING" else None
            if diff_reason is not None:
                unexplained_diffs += 1
            slot_rows.append(
                {
                    "session": slot.session.isoformat(),
                    "lane": slot.run_kind.value,
                    "run_id": slot.run_id,
                    "expected_at": expected_at,
                    "slot_state": slot_state,
                    "journal_status": None,
                    "issue_codes": [],
                    "report_basename": None,
                    "report_status": None,
                    "publication_contract": "NOT_APPLICABLE",
                    "expectation": "NOT_EVALUATED",
                    "diff_reason": diff_reason,
                    "sealed_input_hash": None,
                    "decision_payload_hash": None,
                    "eligible_count": None,
                    "research_attempted_count": None,
                    "research_succeeded_count": None,
                    "research_timed_out_count": None,
                    "published_item_count": None,
                    "published_action_counts": {},
                    "provider_counts": {},
                    "verified_evidence_count": None,
                    "fresh_verified_source_count": None,
                }
            )
            continue

        status = record["status"]
        assert type(status) is str
        journal_statuses[status] += 1
        slot_state = "TERMINAL" if status in _TERMINAL_STATUSES else "STARTED"
        if status == "STARTED" and observed_at >= slot.expected_at + timedelta(
            seconds=manifest.stale_seconds
        ):
            slot_state = "STALE_STARTED_UNRECONCILED"
        row: dict[str, object] = {
            "session": slot.session.isoformat(),
            "lane": slot.run_kind.value,
            "run_id": slot.run_id,
            "expected_at": expected_at,
            "slot_state": slot_state,
            "journal_status": status,
            "issue_codes": [issue["code"] for issue in record["issues"]],
            "report_basename": record["report_file"],
            "report_status": None,
            "publication_contract": "NOT_APPLICABLE",
            "expectation": "NOT_EVALUATED",
            "diff_reason": (
                "UNEXPLAINED"
                if status
                in {"BLOCKED", "FAILED", "MISSED_EXPECTED", "STALE_INCOMPLETE"}
                else None
            ),
            "sealed_input_hash": None,
            "decision_payload_hash": None,
            "eligible_count": None,
            "research_attempted_count": None,
            "research_succeeded_count": None,
            "research_timed_out_count": None,
            "published_item_count": None,
            "published_action_counts": {},
            "provider_counts": {},
            "verified_evidence_count": None,
            "fresh_verified_source_count": None,
        }
        if row["diff_reason"] is not None:
            unexplained_diffs += 1
        report_basename = record["report_file"]
        if status in {"PUBLISHED", "BLOCKED"} and report_basename is None:
            invalid_publications += 1
            row["publication_contract"] = "INVALID"
        if report_basename is not None:
            try:
                report = _load_report(report_root / report_basename)
                journal_issue_codes = {str(issue["code"]) for issue in record["issues"]}
                retained_upload_failure = (
                    status == "FAILED" and journal_issue_codes == {"UPLOAD_FAILED"}
                )
                if (
                    report["run_id"] != slot.run_id
                    or report["run_kind"] != slot.run_kind.value
                    or report["created_at"] != expected_at
                    or (not retained_upload_failure and report["status"] != status)
                    or report.get("metadata", {}).get("gate_manifest_sha256")
                    != manifest.manifest_sha256
                ):
                    raise ShadowEvaluationError("shadow report provenance is invalid")
                metadata = report.get("metadata", {})
                eligible = metadata.get("eligible_count")
                if type(eligible) is not int or eligible < 0:
                    raise ShadowEvaluationError(
                        "shadow report eligible count is invalid"
                    )
                selected = metadata.get("selected_count")
                if type(selected) is not int or not 0 <= selected <= eligible:
                    raise ShadowEvaluationError(
                        "shadow report selected count is invalid"
                    )
                row["report_status"] = report["status"]
                row["published_item_count"] = 0
                row["verified_evidence_count"] = 0
                row["fresh_verified_source_count"] = 0
                row["issue_codes"] = sorted(
                    journal_issue_codes
                    | {str(issue["code"]) for issue in report["issues"]}
                )
                local_provider_counts: dict[str, Counter[str]] = {}
                for provider in manifest.source_provider_chain:
                    prefix = f"provider_{provider.replace('-', '_')}"
                    counts: Counter[str] = Counter()
                    for field in ("attempts", "failures", "timeouts"):
                        value = metadata.get(f"{prefix}_{field}", 0)
                        if type(value) is not int or value < 0:
                            raise ShadowEvaluationError(
                                "shadow report provider metadata is invalid"
                            )
                        counts[field] += value
                    local_provider_counts[provider] = counts
                local_cases: list[dict[str, object]] = []
                local_eligible = 0
                local_covered = 0
                local_verified_sources = 0
                local_fresh_sources = 0
                local_mismatches = 0
                if report["status"] == "PUBLISHED":
                    payload = report["decision_payload"]
                    sealed_hash = payload["sealed_input_hash"]
                    row["sealed_input_hash"] = sealed_hash
                    row["decision_payload_hash"] = report["decision_payload_hash"]
                    report_items = payload["items"]
                    row["published_item_count"] = len(report_items)
                    row["published_action_counts"] = dict(
                        sorted(
                            Counter(
                                item["action"]
                                if item["status"] == "DECIDED"
                                else "REVIEW"
                                for item in report_items
                            ).items()
                        )
                    )
                    snapshot = _load_snapshot(snapshots, sealed_hash)
                    if snapshot["run_kind"] != slot.run_kind.value:
                        raise ShadowEvaluationError("sealed snapshot lane is invalid")
                    snapshot_items = snapshot["items"]
                    assert type(snapshot_items) is list
                    if eligible != len(snapshot_items):
                        raise ShadowEvaluationError(
                            "shadow report eligible count does not match the snapshot"
                        )
                    expected_selected = (
                        eligible
                        if slot.run_kind.value == "ENTRY"
                        else min(eligible, MAX_RESEARCH_ITEMS_V0)
                    )
                    if selected != expected_selected:
                        raise ShadowEvaluationError(
                            "shadow report selected count does not match the snapshot"
                        )
                    row["eligible_count"] = eligible
                    row["research_attempted_count"] = selected
                    row["research_succeeded_count"] = "NOT_EVALUATED"
                    row["research_timed_out_count"] = "NOT_EVALUATED"
                    local_eligible = eligible
                    expected_cases = expected_by_lane_hash.get(
                        (slot.run_kind.value, sealed_hash)
                    )
                    if expected_cases is None:
                        raise ShadowEvaluationError(
                            "shadow report is not covered by the ledger"
                        )
                    report_cases, covered, fresh = _report_case_rows(
                        report=report,
                        snapshot=snapshot,
                        expected_cases=expected_cases,
                    )
                    for report_case in report_cases:
                        local_cases.append(
                            {
                                "session": slot.session.isoformat(),
                                "lane": slot.run_kind.value,
                                "run_id": slot.run_id,
                                **report_case,
                            }
                        )
                    local_mismatches = sum(
                        report_case["expectation"] == "MISMATCH"
                        for report_case in report_cases
                    )
                    row["expectation"] = (
                        "MATCH" if local_mismatches == 0 else "UNCLASSIFIED_MISMATCH"
                    )
                    if local_mismatches > 0 and row["diff_reason"] is None:
                        row["diff_reason"] = "UNEXPLAINED"
                        unexplained_diffs += local_mismatches
                    local_covered = covered
                    for report_case in report_cases:
                        evidence_count = report_case["verified_evidence_count"]
                        if type(evidence_count) is not int:
                            raise ShadowEvaluationError(
                                "shadow report evidence count is invalid"
                            )
                        issue_codes = report_case["issue_codes"]
                        if type(issue_codes) is not list or any(
                            type(code) is not str for code in issue_codes
                        ):
                            raise ShadowEvaluationError(
                                "shadow report issue codes are invalid"
                            )
                        local_verified_sources += evidence_count
                    local_fresh_sources = fresh
                    row["verified_evidence_count"] = local_verified_sources
                    row["fresh_verified_source_count"] = local_fresh_sources
                elif row["diff_reason"] is None:
                    row["diff_reason"] = "UNEXPLAINED"
                    unexplained_diffs += 1
                if report["status"] == "BLOCKED":
                    research_coverage_unavailable = True
                    lane_coverage_unavailable.add(slot.run_kind.value)
                row["publication_contract"] = "VALID"
                row["provider_counts"] = {
                    provider: dict(sorted(counts.items()))
                    for provider, counts in sorted(local_provider_counts.items())
                }
                for provider, counts in local_provider_counts.items():
                    provider_counts[(slot.run_kind.value, provider)].update(counts)
                case_rows.extend(local_cases)
                eligible_items += local_eligible
                covered_items += local_covered
                verified_sources += local_verified_sources
                fresh_sources += local_fresh_sources
                lane_counts = lane_quality_counts[slot.run_kind.value]
                lane_counts["eligible"] += local_eligible
                lane_counts["covered"] += local_covered
                lane_counts["verified"] += local_verified_sources
                lane_counts["fresh"] += local_fresh_sources
            except ShadowEvaluationError:
                invalid_publications += 1
                row["publication_contract"] = "INVALID"
                row["expectation"] = "NOT_EVALUATED"
        slot_rows.append(row)

    terminal_slots = sum(row["slot_state"] == "TERMINAL" for row in slot_rows)
    due_slots = sum(
        observed_at
        >= datetime.fromisoformat(str(row["expected_at"]).replace("Z", "+00:00"))
        + timedelta(seconds=manifest.grace_seconds)
        for row in slot_rows
    )
    due_terminal_slots = sum(
        row["slot_state"] == "TERMINAL"
        and observed_at
        >= datetime.fromisoformat(str(row["expected_at"]).replace("Z", "+00:00"))
        + timedelta(seconds=manifest.grace_seconds)
        for row in slot_rows
    )
    session_status: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in slot_rows:
        session_status[str(row["session"])].append(row)
    completed_sessions = sum(
        len(rows) == len(manifest.lanes)
        and all(row["slot_state"] == "TERMINAL" for row in rows)
        for rows in session_status.values()
    )

    provider_rows: list[dict[str, object]] = []
    total_provider = Counter[str]()
    for lane in ("ENTRY", "HOLDING"):
        for provider in manifest.source_provider_chain:
            counts = provider_counts[(lane, provider)]
            total_provider.update(counts)
            failure_rate = _ratio(counts["failures"], counts["attempts"])
            provider_rows.append(
                {
                    "lane": lane,
                    "provider": provider,
                    "attempts": counts["attempts"],
                    "failures": counts["failures"],
                    "timeouts": counts["timeouts"],
                    "failure_rate": failure_rate,
                    "threshold_status": _threshold_status(
                        failure_rate,
                        maximum=quality_thresholds["provider_failure_rate_max"],
                    ),
                }
            )

    provider_failure_rate = _ratio(
        total_provider["failures"], total_provider["attempts"]
    )
    research_coverage_rate = (
        None if research_coverage_unavailable else _ratio(covered_items, eligible_items)
    )
    research_coverage_status = (
        "NOT_EVALUATED"
        if research_coverage_unavailable
        else _threshold_status(
            research_coverage_rate,
            minimum=quality_thresholds["research_coverage_rate_min"],
        )
    )
    fresh_source_rate = _ratio(fresh_sources, verified_sources)
    lane_quality_rows: list[dict[str, object]] = []
    for lane in ("ENTRY", "HOLDING"):
        counts = lane_quality_counts[lane]
        coverage_unavailable = lane in lane_coverage_unavailable
        lane_research_rate = (
            None
            if coverage_unavailable
            else _ratio(counts["covered"], counts["eligible"])
        )
        lane_research_status = (
            "NOT_EVALUATED"
            if coverage_unavailable
            else _threshold_status(
                lane_research_rate,
                minimum=quality_thresholds["research_coverage_rate_min"],
            )
        )
        lane_fresh_rate = _ratio(counts["fresh"], counts["verified"])
        lane_quality_rows.append(
            {
                "lane": lane,
                "research_coverage_numerator": (
                    None if coverage_unavailable else counts["covered"]
                ),
                "research_coverage_denominator": (
                    None if coverage_unavailable else counts["eligible"]
                ),
                "research_coverage_rate": lane_research_rate,
                "research_coverage_threshold_status": lane_research_status,
                "fresh_source_numerator": counts["fresh"],
                "fresh_source_denominator": counts["verified"],
                "fresh_source_rate": lane_fresh_rate,
                "fresh_source_threshold_status": _threshold_status(
                    lane_fresh_rate,
                    minimum=quality_thresholds["fresh_source_rate_min"],
                ),
            }
        )
    hard_metrics = {
        "unexplained": unexplained_diffs,
        "invalid_publications": invalid_publications,
        "privacy_leaks": "NOT_EVALUATED",
        "order_or_notification_accesses": "NOT_EVALUATED",
        "payload_replay_mismatches": "NOT_EVALUATED",
        "uncovered_eligible_holdings": "NOT_EVALUATED",
        "hard_sell_regressions": "NOT_EVALUATED",
        "existing_pipeline_impacts": "NOT_EVALUATED",
    }
    automatic_attention = any(
        (
            row["slot_state"] in {"DUE_MISSING", "STALE_STARTED_UNRECONCILED"}
            or row["publication_contract"] == "INVALID"
            or row["diff_reason"] == "UNEXPLAINED"
            or row["journal_status"]
            in {"FAILED", "MISSED_EXPECTED", "STALE_INCOMPLETE"}
        )
        for row in slot_rows
    )
    complete = completed_sessions >= len(manifest.sessions)
    quality_attention = complete and any(
        status in {"BELOW_THRESHOLD", "ABOVE_THRESHOLD", "NOT_EVALUATED"}
        for status in (
            _threshold_status(
                provider_failure_rate,
                maximum=quality_thresholds["provider_failure_rate_max"],
            ),
            research_coverage_status,
            _threshold_status(
                fresh_source_rate,
                minimum=quality_thresholds["fresh_source_rate_min"],
            ),
        )
    )
    lane_quality_attention = complete and any(
        row[status_field] in {"BELOW_THRESHOLD", "ABOVE_THRESHOLD", "NOT_EVALUATED"}
        for row in lane_quality_rows
        for status_field in (
            "research_coverage_threshold_status",
            "fresh_source_threshold_status",
        )
    )
    gate_state = "IN_PROGRESS"
    if automatic_attention or quality_attention or lane_quality_attention:
        gate_state = "ATTENTION_REQUIRED"
    elif complete:
        gate_state = "READY_FOR_MANUAL_GRADUATION_REVIEW"

    return {
        "schema_version": "decision-board-shadow-evaluation.v0",
        "generated_at": _timestamp(observed_at),
        "gate": {
            "gate_version": manifest.gate_version,
            "manifest_sha256": manifest.manifest_sha256,
            "start_session": manifest.start_session.isoformat(),
            "end_session": manifest.end_session.isoformat(),
            "minimum_sessions": len(manifest.sessions),
            "planned_slots": len(manifest.slots),
            "grace_seconds": manifest.grace_seconds,
        },
        "progress": {
            "completed_sessions": completed_sessions,
            "planned_sessions": len(manifest.sessions),
            "terminal_slots": terminal_slots,
            "planned_slots": len(manifest.slots),
            "due_slots": due_slots,
            "due_terminal_slots": due_terminal_slots,
            "planned_terminal_coverage": _ratio(terminal_slots, len(manifest.slots)),
            "due_terminal_coverage": _ratio(due_terminal_slots, due_slots),
            "gate_state": gate_state,
        },
        "journal_status_counts": dict(sorted(journal_statuses.items())),
        "diff_reason_counts": (
            {"UNEXPLAINED": unexplained_diffs} if unexplained_diffs else {}
        ),
        "quality": {
            "provider_failure_rate": {
                "numerator": total_provider["failures"],
                "denominator": total_provider["attempts"],
                "value": provider_failure_rate,
                "threshold": quality_thresholds["provider_failure_rate_max"],
                "threshold_status": _threshold_status(
                    provider_failure_rate,
                    maximum=quality_thresholds["provider_failure_rate_max"],
                ),
            },
            "research_coverage_rate": {
                "numerator": (None if research_coverage_unavailable else covered_items),
                "denominator": (
                    None if research_coverage_unavailable else eligible_items
                ),
                "value": research_coverage_rate,
                "threshold": quality_thresholds["research_coverage_rate_min"],
                "threshold_status": research_coverage_status,
            },
            "fresh_source_rate": {
                "numerator": fresh_sources,
                "denominator": verified_sources,
                "value": fresh_source_rate,
                "threshold": quality_thresholds["fresh_source_rate_min"],
                "threshold_status": _threshold_status(
                    fresh_source_rate,
                    minimum=quality_thresholds["fresh_source_rate_min"],
                ),
            },
        },
        "provider_metrics": provider_rows,
        "lane_quality": lane_quality_rows,
        "hard_metrics": hard_metrics,
        "slots": slot_rows,
        "cases": case_rows,
    }


def write_private_json_output_v0(path: str | Path, value: object) -> Path:
    """Atomically replace one owner-only evaluation or dashboard artifact."""

    requested = Path(path)
    if requested.name in {"", ".", ".."}:
        raise ShadowEvaluationError("shadow evaluation output path is invalid")
    try:
        parent = requested.parent.resolve(strict=True)
        if not parent.is_dir():
            raise ShadowEvaluationError("shadow evaluation output parent is invalid")
        target = parent / requested.name
        payload = canonical_json_bytes(value) + b"\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{requested.name}.", suffix=".tmp", dir=parent
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(
                parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target
    except ShadowEvaluationError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ShadowEvaluationError("shadow evaluation output failed") from exc


__all__ = [
    "ShadowEvaluationError",
    "evaluate_shadow_gate_v0",
    "write_private_json_output_v0",
]
