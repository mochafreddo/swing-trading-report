from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sab.__main__ import _build_parser, main
from sab.decision_board.contracts import canonical_json_bytes, decision_payload_hash
from sab.decision_board.run_journal import (
    RunJournalStatusV0,
    RunJournalStoreV0,
)
from sab.decision_board.runner import RunKindV0
from sab.decision_board.shadow_dashboard import build_shadow_dashboard_artifact_v0
from sab.decision_board.shadow_evaluation import (
    evaluate_shadow_gate_v0,
    write_private_json_output_v0,
)
from sab.decision_board.shadow_gate import (
    load_shadow_gate_manifest_v0,
    shadow_gate_approval_signature_v0,
)
from sab.report.decision_board import build_decision_board_storage_key

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "config" / "decision-board-shadow-gate.proposed.json"


def _approved_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    raw = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    snapshot = {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "ENTRY",
        "metadata": {},
        "items": [
            {
                "item_id": "entry-AAPL.NAS",
                "instrument": {
                    "market": "US",
                    "canonical_ticker": "AAPL.NAS",
                    "exchange": "NASDAQ",
                    "company_name": "Apple",
                    "identity_source": "test",
                    "identity_version": "test-v0",
                },
                "item_state": "APPROVED",
                "identity_state": "APPROVED",
                "signal_state": "READY_ENTER",
                "mandate_state": "CURRENT",
                "price_state": "CURRENT",
                "exposure_state": "MISSING",
            }
        ],
    }
    snapshot_bytes = canonical_json_bytes(snapshot)
    sealed_hash = decision_payload_hash(snapshot)
    holding_snapshot = {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "HOLDING",
        "metadata": {},
        "items": [
            {
                "item_id": "holding-MSFT.NAS",
                "instrument": {
                    "market": "US",
                    "canonical_ticker": "MSFT.NAS",
                    "exchange": "NASDAQ",
                    "company_name": "Microsoft",
                    "identity_source": "test",
                    "identity_version": "test-v0",
                },
                "item_state": "APPROVED",
                "identity_state": "APPROVED",
                "hard_exit_state": "NONE",
                "broker_state": "CURRENT",
                "candle_state": "CURRENT",
                "rule_state": "CURRENT",
                "research_priority": 10,
                "research_order": "000010-MSFT.NAS",
            }
        ],
    }
    holding_snapshot_bytes = canonical_json_bytes(holding_snapshot)
    holding_sealed_hash = decision_payload_hash(holding_snapshot)
    input_ledger = {
        "schema_version": "decision-board-shadow-input-ledger.v0",
        "gate_version": raw["gate_version"],
        "cases": [
            {
                "case_id": "case-entry-aapl",
                "run_kind": "ENTRY",
                "sealed_input_hash": sealed_hash,
                "item_id": "entry-AAPL.NAS",
            },
            {
                "case_id": "case-holding-msft",
                "run_kind": "HOLDING",
                "sealed_input_hash": holding_sealed_hash,
                "item_id": "holding-MSFT.NAS",
            },
        ],
    }
    expected_ledger = {
        "schema_version": "decision-board-shadow-expected-action-ledger.v0",
        "gate_version": raw["gate_version"],
        "cases": [
            {
                "case_id": "case-entry-aapl",
                "expected_action_set": ["REVIEW"],
            },
            {
                "case_id": "case-holding-msft",
                "expected_action_set": ["HOLD"],
            },
        ],
    }
    raw["evaluation_ledger"] = {
        "input_ledger_sha256": decision_payload_hash(input_ledger),
        "expected_action_ledger_sha256": decision_payload_hash(expected_ledger),
        "case_count": 2,
    }
    raw["approval"] = {
        "state": "APPROVED",
        "approved_by": "user",
        "approved_at": "2026-08-21T00:00:00Z",
        "approval_signature_sha256": "sha256:" + "0" * 64,
    }
    runtime = raw["runtime_contract"]
    runtime["code_revision"] = "git:" + "1" * 40
    for name in runtime["artifact_digests"]:
        runtime["artifact_digests"][name] = "sha256:" + "2" * 64
    raw["approval"]["approval_signature_sha256"] = shadow_gate_approval_signature_v0(
        raw
    )

    manifest_path = tmp_path / "approved.json"
    input_path = tmp_path / "input.json"
    expected_path = tmp_path / "expected.json"
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir(mode=0o700)
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    input_path.write_bytes(canonical_json_bytes(input_ledger))
    expected_path.write_bytes(canonical_json_bytes(expected_ledger))
    snapshot_path = snapshot_dir / f"{sealed_hash.removeprefix('sha256:')}.json"
    snapshot_path.write_bytes(snapshot_bytes)
    holding_snapshot_path = (
        snapshot_dir / f"{holding_sealed_hash.removeprefix('sha256:')}.json"
    )
    holding_snapshot_path.write_bytes(holding_snapshot_bytes)
    for path in (input_path, expected_path, snapshot_path, holding_snapshot_path):
        path.chmod(0o600)
    return manifest_path, input_path, expected_path, snapshot_dir


def _published_entry(
    *,
    manifest_path: Path,
    input_path: Path,
    expected_path: Path,
    journal_dir: Path,
    report_dir: Path,
    journal_status: RunJournalStatusV0 = RunJournalStatusV0.PUBLISHED,
    issue_codes: tuple[str, ...] = (),
) -> datetime:
    manifest = load_shadow_gate_manifest_v0(
        manifest_path,
        require_approved=True,
        input_ledger_path=input_path,
        expected_action_ledger_path=expected_path,
    )
    slot = manifest.slots[0]
    payload = {
        "run_kind": "ENTRY",
        "sealed_input_hash": json.loads(input_path.read_text())["cases"][0][
            "sealed_input_hash"
        ],
        "items": [
            {
                "instrument": {
                    "market": "US",
                    "canonical_ticker": "AAPL.NAS",
                    "exchange": "NASDAQ",
                    "company_name": "Apple",
                    "identity_source": "test",
                    "identity_version": "test-v0",
                },
                "status": "REVIEW",
                "issues": [
                    {
                        "code": "REVIEW_EXPOSURE_MISSING",
                        "message": "A required typed input is not current.",
                    }
                ],
                "evidence": [],
            }
        ],
    }
    report = {
        "schema_version": "decision-board.v0",
        "run_id": slot.run_id,
        "created_at": slot.expected_at.isoformat().replace("+00:00", "Z"),
        "idempotency_key": "sha256:" + "4" * 64,
        "run_kind": "ENTRY",
        "status": "PUBLISHED",
        "issues": [],
        "metadata": {
            "gate_manifest_sha256": manifest.manifest_sha256,
            "eligible_count": 1,
            "selected_count": 1,
            "provider_finnhub_attempts": 1,
            "provider_finnhub_failures": 0,
            "provider_finnhub_timeouts": 0,
        },
        "decision_payload": payload,
        "decision_payload_hash": decision_payload_hash(payload),
    }
    basename = Path(build_decision_board_storage_key(report)).name
    report_path = report_dir / basename
    report_path.write_bytes(canonical_json_bytes(report))
    report_path.chmod(0o600)
    store = RunJournalStoreV0(journal_dir)
    started = store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=slot.expected_at,
        run_id=slot.run_id,
        started_at=slot.expected_at,
        grace_seconds=manifest.grace_seconds,
        stale_seconds=manifest.stale_seconds,
    )
    store.finish(
        started,
        status=journal_status,
        terminal_at=slot.expected_at + timedelta(seconds=1),
        issue_codes=issue_codes,
        report_file=basename,
    )
    return slot.expected_at


def _publish_complete_gate(
    *,
    manifest_path: Path,
    input_path: Path,
    expected_path: Path,
    journal_dir: Path,
    report_dir: Path,
    mismatch_first_action: bool = False,
    provider_failures: int = 0,
    holding_without_evidence_count: int = 0,
) -> datetime:
    manifest = load_shadow_gate_manifest_v0(
        manifest_path,
        require_approved=True,
        input_ledger_path=input_path,
        expected_action_ledger_path=expected_path,
    )
    ledger = json.loads(input_path.read_text(encoding="utf-8"))
    sealed_by_lane = {
        case["run_kind"]: case["sealed_input_hash"] for case in ledger["cases"]
    }
    instruments = {
        "ENTRY": {
            "market": "US",
            "canonical_ticker": "AAPL.NAS",
            "exchange": "NASDAQ",
            "company_name": "Apple",
            "identity_source": "test",
            "identity_version": "test-v0",
        },
        "HOLDING": {
            "market": "US",
            "canonical_ticker": "MSFT.NAS",
            "exchange": "NASDAQ",
            "company_name": "Microsoft",
            "identity_source": "test",
            "identity_version": "test-v0",
        },
    }
    evidence = {
        "claim_id": "claim-test",
        "role": "SUPPORTING",
        "source_url": "https://evidence.example/test",
        "publisher": "Test Wire",
        "published_at": "2026-08-20T00:00:00Z",
        "article_content_hash": "sha256:" + "3" * 64,
        "supporting_span": "Verified public evidence.",
        "supporting_location": {"kind": "TEXT_OFFSETS", "start": 0, "end": 25},
        "entailment": "SUPPORTED",
        "freshness": "WITHIN_POLICY",
        "citation_label": "Test evidence",
    }
    store = RunJournalStoreV0(journal_dir)
    holding_seen = 0
    for index, slot in enumerate(manifest.slots):
        lane = slot.run_kind.value
        if lane == "ENTRY":
            item: dict[str, object] = {
                "instrument": instruments[lane],
                "status": "REVIEW",
                "issues": [
                    {
                        "code": "REVIEW_EXPOSURE_MISSING",
                        "message": "A required typed input is not current.",
                    }
                ],
                "evidence": [evidence],
            }
            if mismatch_first_action and index == 0:
                item = {
                    "instrument": instruments[lane],
                    "status": "DECIDED",
                    "action": "BUY",
                    "issues": [],
                    "evidence": [evidence],
                }
        else:
            holding_seen += 1
            item = {
                "instrument": instruments[lane],
                "status": "DECIDED",
                "action": "HOLD",
                "issues": [],
                "evidence": (
                    [] if holding_seen <= holding_without_evidence_count else [evidence]
                ),
            }
        payload = {
            "run_kind": lane,
            "sealed_input_hash": sealed_by_lane[lane],
            "items": [item],
        }
        report = {
            "schema_version": "decision-board.v0",
            "run_id": slot.run_id,
            "created_at": slot.expected_at.isoformat().replace("+00:00", "Z"),
            "idempotency_key": "sha256:" + f"{index + 1:064x}",
            "run_kind": lane,
            "status": "PUBLISHED",
            "issues": [],
            "metadata": {
                "gate_manifest_sha256": manifest.manifest_sha256,
                "eligible_count": 1,
                "selected_count": 1,
                "provider_finnhub_attempts": 1,
                "provider_finnhub_failures": provider_failures,
                "provider_finnhub_timeouts": 0,
            },
            "decision_payload": payload,
            "decision_payload_hash": decision_payload_hash(payload),
        }
        basename = Path(build_decision_board_storage_key(report)).name
        report_path = report_dir / basename
        report_path.write_bytes(canonical_json_bytes(report))
        report_path.chmod(0o600)
        started = store.start(
            run_kind=slot.run_kind,
            expected_at=slot.expected_at,
            run_id=slot.run_id,
            started_at=slot.expected_at,
            grace_seconds=manifest.grace_seconds,
            stale_seconds=manifest.stale_seconds,
        )
        store.finish(
            started,
            status=RunJournalStatusV0.PUBLISHED,
            terminal_at=slot.expected_at + timedelta(seconds=1),
            report_file=basename,
        )
    return manifest.slots[-1].expected_at


def test_evaluation_reads_sources_without_mutating_and_reconciles_actions(
    tmp_path: Path,
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    expected_at = _published_entry(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
    )
    before = {path.name: path.read_bytes() for path in journal_dir.glob("*.json")}

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=expected_at.astimezone(UTC) + timedelta(minutes=5),
    )

    assert result["progress"]["terminal_slots"] == 1  # type: ignore[index]
    assert result["progress"]["due_terminal_coverage"] == 1.0  # type: ignore[index]
    assert result["quality"]["provider_failure_rate"]["value"] == 0.0  # type: ignore[index]
    assert result["quality"]["research_coverage_rate"]["value"] == 0.0  # type: ignore[index]
    assert result["slots"][0]["publication_contract"] == "VALID"  # type: ignore[index]
    assert result["slots"][0]["expectation"] == "MATCH"  # type: ignore[index]
    assert result["slots"][0]["diff_reason"] is None  # type: ignore[index]
    assert result["slots"][0]["sealed_input_hash"].startswith("sha256:")  # type: ignore[index,union-attr]
    assert result["slots"][0]["published_action_counts"] == {"REVIEW": 1}  # type: ignore[index]
    assert result["hard_metrics"]["unexplained"] == 0  # type: ignore[index]
    assert result["cases"][0]["actual_action"] == "REVIEW"  # type: ignore[index]
    artifact = build_shadow_dashboard_artifact_v0(result)
    assert artifact["surface"] == "dashboard"
    assert artifact["snapshot"]["datasets"]["summary"][0]["terminal_slots"] == 1  # type: ignore[index]
    assert type(artifact["snapshot"]["datasets"]["slots"][0]["provider_counts"]) is str  # type: ignore[index]
    assert artifact["manifest"]["blocks"][0]["type"] == "metric-strip"  # type: ignore[index]
    artifact_snapshot = artifact["snapshot"]
    assert type(artifact_snapshot) is dict
    datasets = artifact_snapshot["datasets"]
    assert type(datasets) is dict
    source_datasets = {
        "summary_source": "summary",
        "quality_source": "quality",
        "provider_source": "provider_metrics",
        "lane_quality_source": "lane_quality",
        "slots_source": "slots",
        "cases_source": "cases",
        "hard_metrics_source": "hard_metrics",
    }
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    sources = artifact["sources"]
    assert type(sources) is list
    for source in sources:
        assert type(source) is dict
        dataset = source_datasets[source["id"]]
        query = source["query"]
        assert type(query) is dict
        sql = query["sql"]
        assert type(sql) is str
        rows = [
            dict(row)
            for row in connection.execute(
                sql,
                {"evaluation_json": json.dumps(result)},
            )
        ]
        expected_rows = [
            {field: row[field] for field in rows[0]} if rows else {}
            for row in datasets[dataset]
        ]
        assert rows == expected_rows
    output = write_private_json_output_v0(tmp_path / "dashboard.json", artifact)
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["surface"] == "dashboard"
    assert before == {
        path.name: path.read_bytes() for path in journal_dir.glob("*.json")
    }


def test_due_missing_slot_is_unexplained_and_requires_attention(tmp_path: Path) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    loaded = load_shadow_gate_manifest_v0(
        manifest,
        require_approved=True,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
    )
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=loaded.slots[0].expected_at + timedelta(seconds=loaded.grace_seconds),
    )

    assert result["slots"][0]["slot_state"] == "DUE_MISSING"  # type: ignore[index]
    assert result["slots"][0]["diff_reason"] == "UNEXPLAINED"  # type: ignore[index]
    assert result["hard_metrics"]["unexplained"] == 1  # type: ignore[index]
    assert result["progress"]["gate_state"] == "ATTENTION_REQUIRED"  # type: ignore[index]


def test_started_slot_past_ttl_requires_attention_without_source_mutation(
    tmp_path: Path,
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    loaded = load_shadow_gate_manifest_v0(
        manifest,
        require_approved=True,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
    )
    slot = loaded.slots[0]
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    store = RunJournalStoreV0(journal_dir)
    store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=slot.expected_at,
        run_id=slot.run_id,
        started_at=slot.expected_at,
        grace_seconds=loaded.grace_seconds,
        stale_seconds=loaded.stale_seconds,
    )
    before = {path.name: path.read_bytes() for path in journal_dir.glob("*.json")}

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=slot.expected_at + timedelta(seconds=loaded.stale_seconds),
    )

    assert result["slots"][0]["slot_state"] == "STALE_STARTED_UNRECONCILED"  # type: ignore[index]
    assert result["progress"]["gate_state"] == "ATTENTION_REQUIRED"  # type: ignore[index]
    assert before == {
        path.name: path.read_bytes() for path in journal_dir.glob("*.json")
    }


def test_retained_upload_failure_report_remains_a_valid_publication(
    tmp_path: Path,
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    expected_at = _published_entry(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
        journal_status=RunJournalStatusV0.FAILED,
        issue_codes=("UPLOAD_FAILED",),
    )

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=expected_at + timedelta(minutes=5),
    )

    assert result["slots"][0]["journal_status"] == "FAILED"  # type: ignore[index]
    assert result["slots"][0]["report_status"] == "PUBLISHED"  # type: ignore[index]
    assert result["slots"][0]["publication_contract"] == "VALID"  # type: ignore[index]
    assert result["hard_metrics"]["invalid_publications"] == 0  # type: ignore[index]
    assert result["hard_metrics"]["unexplained"] == 1  # type: ignore[index]


def test_blocked_report_preserves_reason_and_counts_eligible_coverage(
    tmp_path: Path,
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    expected_at = _published_entry(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
        journal_status=RunJournalStatusV0.BLOCKED,
    )
    report_path = next(report_dir.glob("*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["status"] = "BLOCKED"
    report["issues"] = [
        {
            "code": "PREPARATION_INVALID",
            "message": "A required typed input is not current.",
        }
    ]
    del report["decision_payload"]
    del report["decision_payload_hash"]
    report_path.write_bytes(canonical_json_bytes(report))

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=expected_at + timedelta(minutes=5),
    )

    assert result["slots"][0]["publication_contract"] == "VALID"  # type: ignore[index]
    assert result["slots"][0]["issue_codes"] == ["PREPARATION_INVALID"]  # type: ignore[index]
    assert result["slots"][0]["diff_reason"] == "UNEXPLAINED"  # type: ignore[index]
    assert result["slots"][0]["eligible_count"] is None  # type: ignore[index]
    assert result["quality"]["research_coverage_rate"]["denominator"] is None  # type: ignore[index]
    assert result["quality"]["research_coverage_rate"]["value"] is None  # type: ignore[index]
    assert (
        result["quality"]["research_coverage_rate"][  # type: ignore[index]
            "threshold_status"
        ]
        == "NOT_EVALUATED"
    )


@pytest.mark.parametrize("mutation", ["duplicate", "identity"])
def test_duplicate_or_changed_report_instrument_is_an_invalid_publication(
    tmp_path: Path, mutation: str
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    expected_at = _published_entry(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
    )
    report_path = next(report_dir.glob("*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    payload = report["decision_payload"]
    if mutation == "duplicate":
        payload["items"].append(dict(payload["items"][0]))
    else:
        payload["items"][0]["instrument"]["company_name"] = "Changed identity"
    report["decision_payload_hash"] = decision_payload_hash(payload)
    report_path.write_bytes(canonical_json_bytes(report))

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=expected_at + timedelta(minutes=5),
    )

    assert result["slots"][0]["publication_contract"] == "INVALID"  # type: ignore[index]
    assert result["hard_metrics"]["invalid_publications"] == 1  # type: ignore[index]


def test_evaluation_projects_terminal_journal_state_to_as_of(tmp_path: Path) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    expected_at = _published_entry(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
    )

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=expected_at,
    )

    assert result["slots"][0]["slot_state"] == "STARTED"  # type: ignore[index]
    assert result["slots"][0]["journal_status"] == "STARTED"  # type: ignore[index]
    assert result["slots"][0]["publication_contract"] == "NOT_APPLICABLE"  # type: ignore[index]


def test_eligible_count_must_match_the_sealed_snapshot(tmp_path: Path) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    expected_at = _published_entry(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
    )
    report_path = next(report_dir.glob("*.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["metadata"]["eligible_count"] = 2
    report_path.write_bytes(canonical_json_bytes(report))

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=expected_at + timedelta(minutes=5),
    )

    assert result["slots"][0]["publication_contract"] == "INVALID"  # type: ignore[index]
    assert result["hard_metrics"]["invalid_publications"] == 1  # type: ignore[index]


@pytest.mark.parametrize(
    (
        "mismatch_first_action",
        "provider_failures",
        "holding_without_evidence_count",
        "expected_state",
    ),
    [
        (False, 0, 0, "READY_FOR_MANUAL_GRADUATION_REVIEW"),
        (True, 0, 0, "ATTENTION_REQUIRED"),
        (False, 1, 0, "ATTENTION_REQUIRED"),
        (False, 0, 4, "ATTENTION_REQUIRED"),
    ],
)
def test_complete_twenty_session_gate_transitions(
    tmp_path: Path,
    mismatch_first_action: bool,
    provider_failures: int,
    holding_without_evidence_count: int,
    expected_state: str,
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    final_expected_at = _publish_complete_gate(
        manifest_path=manifest,
        input_path=input_ledger,
        expected_path=expected_ledger,
        journal_dir=journal_dir,
        report_dir=report_dir,
        mismatch_first_action=mismatch_first_action,
        provider_failures=provider_failures,
        holding_without_evidence_count=holding_without_evidence_count,
    )

    result = evaluate_shadow_gate_v0(
        manifest_path=manifest,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
        snapshot_dir=snapshots,
        journal_dir=journal_dir,
        report_dir=report_dir,
        as_of=final_expected_at + timedelta(minutes=5),
    )

    assert result["progress"]["completed_sessions"] == 20  # type: ignore[index]
    assert result["progress"]["terminal_slots"] == 40  # type: ignore[index]
    assert result["progress"]["gate_state"] == expected_state  # type: ignore[index]
    assert result["slots"][0]["research_attempted_count"] == 1  # type: ignore[index]
    assert result["slots"][0]["research_succeeded_count"] == "NOT_EVALUATED"  # type: ignore[index]
    assert result["slots"][0]["research_timed_out_count"] == "NOT_EVALUATED"  # type: ignore[index]
    if mismatch_first_action:
        assert result["slots"][0]["expectation"] == "UNCLASSIFIED_MISMATCH"  # type: ignore[index]
        assert result["hard_metrics"]["unexplained"] == 1  # type: ignore[index]
    if provider_failures:
        assert (
            result["quality"]["provider_failure_rate"][  # type: ignore[index]
                "threshold_status"
            ]
            == "ABOVE_THRESHOLD"
        )
    if holding_without_evidence_count:
        assert result["quality"]["research_coverage_rate"]["value"] == 0.9  # type: ignore[index]
        lane_quality = result["lane_quality"]
        assert type(lane_quality) is list
        by_lane = {row["lane"]: row for row in lane_quality}
        assert by_lane["ENTRY"]["research_coverage_rate"] == 1.0
        assert by_lane["HOLDING"]["research_coverage_rate"] == 0.8
        assert (
            by_lane["HOLDING"]["research_coverage_threshold_status"]
            == "BELOW_THRESHOLD"
        )


def test_cli_writes_private_artifact_and_sanitizes_invalid_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, input_ledger, expected_ledger, snapshots = _approved_inputs(tmp_path)
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    journal_dir.mkdir(mode=0o700)
    report_dir.mkdir()
    loaded = load_shadow_gate_manifest_v0(
        manifest,
        require_approved=True,
        input_ledger_path=input_ledger,
        expected_action_ledger_path=expected_ledger,
    )
    output = tmp_path / "evaluation.json"
    args = [
        "decision-board-shadow-evaluate",
        "--manifest",
        str(manifest),
        "--input-ledger",
        str(input_ledger),
        "--expected-action-ledger",
        str(expected_ledger),
        "--snapshot-dir",
        str(snapshots),
        "--journal-dir",
        str(journal_dir),
        "--report-dir",
        str(report_dir),
        "--as-of",
        loaded.slots[0].expected_at.isoformat().replace("+00:00", "Z"),
        "--output",
        str(output),
    ]

    assert main(args) == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == (
        "decision-board-shadow-evaluation.v0"
    )
    args[args.index(str(manifest))] = str(tmp_path / "missing.json")
    assert main(args) == 2

    captured = capsys.readouterr()
    assert "SHADOW_EVALUATION_INVALID" in captured.err
    assert str(tmp_path) not in captured.err


def test_cli_parser_requires_reproducible_evaluation_inputs() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(
        [
            "decision-board-shadow-evaluate",
            "--manifest",
            "manifest.json",
            "--input-ledger",
            "input.json",
            "--expected-action-ledger",
            "expected.json",
            "--snapshot-dir",
            "snapshots",
            "--journal-dir",
            "journal",
            "--report-dir",
            "reports",
            "--as-of",
            "2026-08-24T12:35:00Z",
            "--format",
            "dashboard-artifact",
        ]
    )

    assert parsed.cmd == "decision-board-shadow-evaluate"
    assert parsed.as_of == "2026-08-24T12:35:00Z"
    assert parsed.format == "dashboard-artifact"
