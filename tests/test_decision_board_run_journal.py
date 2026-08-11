from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
import sab.decision_board.run_journal as run_journal
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    FormatChecker,
)
from sab.decision_board.results import (
    DecisionRunIssueCodeV0,
    create_decision_run_failed_v0,
)
from sab.decision_board.run_journal import (
    ExpectedRunV0,
    RunJournalConflictError,
    RunJournalStatusV0,
    RunJournalStoreV0,
    RunJournalV0,
    journal_decision_run_v0,
    parse_run_journal_v0,
    serialize_run_journal_v0,
)
from sab.decision_board.runner import RunKindV0

EXPECTED_AT = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
STARTED_AT = datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC)
TERMINAL_AT = datetime(2026, 8, 11, 1, 0, 2, tzinfo=UTC)


def _started(store: RunJournalStoreV0, *, run_id: str = "entry-slot-001"):
    return store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id=run_id,
        started_at=STARTED_AT,
    )


def test_started_and_terminal_records_are_canonical_private_safe_and_exact() -> None:
    store = RunJournalStoreV0(Path("journal"))
    del store
    issued = run_journal.create_run_journal_v0(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id="entry-slot-001",
        status=RunJournalStatusV0.STARTED,
        started_at=STARTED_AT,
        terminal_at=None,
    )
    public = serialize_run_journal_v0(issued)
    assert public == {
        "schema_version": "decision-board.v0",
        "run_id": "entry-slot-001",
        "run_kind": "ENTRY",
        "status": "STARTED",
        "expected_at": "2026-08-11T01:00:00Z",
        "started_at": "2026-08-11T01:00:01Z",
        "terminal_at": None,
        "issues": [],
        "report_file": None,
    }
    assert run_journal.canonical_run_journal_bytes_v0(issued) == (
        json.dumps(public, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")

    with pytest.raises(TypeError):
        RunJournalV0()  # type: ignore[call-arg]

    raw = object.__new__(RunJournalV0)
    with pytest.raises(TypeError, match="issued"):
        serialize_run_journal_v0(raw)

    class JournalSubclass(RunJournalV0):
        pass

    subclassed = object.__new__(JournalSubclass)
    with pytest.raises(TypeError, match="exact"):
        serialize_run_journal_v0(subclassed)

    object.__setattr__(issued, "run_id", "mutated")
    with pytest.raises(TypeError, match="unchanged"):
        serialize_run_journal_v0(issued)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "../PRIVATE-SENTINEL"),
        ("run_id", "non-ascii-한글"),
        ("expected_at", datetime(2026, 8, 11, 10, 0)),
        (
            "expected_at",
            datetime(2026, 8, 11, 10, 0, tzinfo=timezone(timedelta(hours=9))),
        ),
    ],
)
def test_factory_rejects_unsafe_identity_and_non_utc_timestamps(field, value) -> None:
    values = {
        "run_kind": RunKindV0.ENTRY,
        "expected_at": EXPECTED_AT,
        "run_id": "entry-slot-001",
        "status": RunJournalStatusV0.STARTED,
        "started_at": STARTED_AT,
        "terminal_at": None,
    }
    values[field] = value
    with pytest.raises((TypeError, ValueError)):
        run_journal.create_run_journal_v0(**values)  # type: ignore[arg-type]


def test_public_parser_rejects_raw_subclass_extra_fields_and_noncanonical_issue() -> (
    None
):
    record = run_journal.create_run_journal_v0(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id="entry-slot-001",
        status=RunJournalStatusV0.FAILED,
        started_at=STARTED_AT,
        terminal_at=TERMINAL_AT,
        issue_codes=(DecisionRunIssueCodeV0.INTERNAL_ERROR.value,),
    )
    public = record.to_public_dict()
    assert parse_run_journal_v0(public).to_public_dict() == public

    class DictSubclass(dict):
        pass

    with pytest.raises(ValueError, match="exact field"):
        parse_run_journal_v0({**public, "private_metadata": "PRIVATE-SENTINEL"})
    with pytest.raises(ValueError, match="exact field"):
        parse_run_journal_v0(DictSubclass(public))
    mutated = json.loads(json.dumps(public))
    mutated["issues"][0]["message"] = "PRIVATE-SENTINEL raw provider failure"
    with pytest.raises(ValueError, match="canonical"):
        parse_run_journal_v0(mutated)
    with pytest.raises(ValueError, match="sanitized"):
        run_journal.create_run_journal_v0(
            run_kind=RunKindV0.ENTRY,
            expected_at=EXPECTED_AT,
            run_id="entry-private-code",
            status=RunJournalStatusV0.FAILED,
            started_at=STARTED_AT,
            terminal_at=TERMINAL_AT,
            issue_codes=("PRIVATE_ACCOUNT_12345",),
        )


def test_schema_accepts_sanitized_report_basename_and_rejects_path(
    tmp_path: Path,
) -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/decision-board.v0.schema.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/RunJournalV0",
        },
        format_checker=FormatChecker(),
    )
    store = RunJournalStoreV0(tmp_path)
    started = _started(store)
    published = store.finish(
        started,
        status=RunJournalStatusV0.PUBLISHED,
        terminal_at=TERMINAL_AT,
        report_file="2026-08-11.entry.decision-board.json",
    ).to_public_dict()
    validator.validate(published)
    published["report_file"] = "/private/PRIVATE-SENTINEL.json"
    errors = list(validator.iter_errors(published))
    assert errors


def test_store_replay_is_exact_and_conflicting_or_regressive_transitions_fail(
    tmp_path: Path,
) -> None:
    store = RunJournalStoreV0(tmp_path)
    started = _started(store)
    assert (
        store.start(
            run_kind=RunKindV0.ENTRY,
            expected_at=EXPECTED_AT,
            run_id="entry-slot-001",
            started_at=STARTED_AT,
        ).to_public_dict()
        == started.to_public_dict()
    )

    with pytest.raises(RunJournalConflictError):
        store.start(
            run_kind=RunKindV0.ENTRY,
            expected_at=EXPECTED_AT,
            run_id="entry-slot-001",
            started_at=STARTED_AT + timedelta(seconds=1),
        )

    terminal = store.finish(
        started,
        status=RunJournalStatusV0.FAILED,
        terminal_at=TERMINAL_AT,
        issue_codes=(DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE.value,),
    )
    assert (
        store.finish(
            started,
            status=RunJournalStatusV0.FAILED,
            terminal_at=TERMINAL_AT,
            issue_codes=(DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE.value,),
        ).to_public_dict()
        == terminal.to_public_dict()
    )

    with pytest.raises(RunJournalConflictError):
        store.finish(
            started,
            status=RunJournalStatusV0.FAILED,
            terminal_at=TERMINAL_AT + timedelta(seconds=1),
            issue_codes=(DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE.value,),
        )
    with pytest.raises(RunJournalConflictError):
        store.finish(
            started,
            status=RunJournalStatusV0.PUBLISHED,
            terminal_at=TERMINAL_AT,
        )
    with pytest.raises(RunJournalConflictError):
        store.start(
            run_kind=RunKindV0.ENTRY,
            expected_at=EXPECTED_AT,
            run_id="entry-slot-001",
            started_at=STARTED_AT,
        )


def test_atomic_transition_failure_preserves_started_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = RunJournalStoreV0(tmp_path)
    started = _started(store)
    journal_path = next(tmp_path.glob("*.json"))
    before = journal_path.read_bytes()

    def fail_write(path: str, payload: bytes) -> None:
        del path, payload
        raise OSError("PRIVATE-SENTINEL synthetic write failure")

    monkeypatch.setattr(run_journal, "_atomic_write_bytes", fail_write)
    with pytest.raises(run_journal.RunJournalStorageError):
        store.finish(
            started,
            status=RunJournalStatusV0.FAILED,
            terminal_at=TERMINAL_AT,
            issue_codes=(DecisionRunIssueCodeV0.INTERNAL_ERROR.value,),
        )
    assert journal_path.read_bytes() == before
    assert store.status(limit=10)[0].status is RunJournalStatusV0.STARTED


def test_store_rejects_symlink_lock_without_creating_record(tmp_path: Path) -> None:
    target = tmp_path / "outside-lock"
    target.write_text("PRIVATE-SENTINEL", encoding="utf-8")
    (tmp_path / ".run-journal-v0.lock").symlink_to(target)
    store = RunJournalStoreV0(tmp_path)
    with pytest.raises(run_journal.RunJournalStorageError, match="lock"):
        _started(store)
    assert list(tmp_path.glob("*.json")) == []
    assert target.read_text(encoding="utf-8") == "PRIVATE-SENTINEL"


def test_cross_process_start_is_idempotent_only_for_exact_bytes(tmp_path: Path) -> None:
    script = """
import json, pathlib, sys, time
from datetime import UTC, datetime, timedelta
from sab.decision_board.run_journal import RunJournalConflictError, RunJournalStoreV0
from sab.decision_board.runner import RunKindV0
while not pathlib.Path(sys.argv[3]).exists():
    time.sleep(0.001)
store = RunJournalStoreV0(sys.argv[1])
try:
    record = store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        run_id="entry-slot-001",
        started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC) + timedelta(seconds=int(sys.argv[2])),
    )
except RunJournalConflictError:
    print("conflict")
else:
    print("ok " + json.dumps(record.to_public_dict(), sort_keys=True))
"""

    def run_group(root: Path, seconds: list[int]) -> list[str]:
        barrier = root.parent / f"barrier-{root.name}"
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(root), str(second), str(barrier)],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for second in seconds
        ]
        time.sleep(0.02)
        barrier.touch()
        outputs: list[str] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            outputs.append(stdout.strip())
        return outputs

    exact = run_group(tmp_path, [0] * 4)
    assert all(output.startswith("ok ") for output in exact)
    assert len(set(exact)) == 1

    other_root = tmp_path / "conflict"
    conflict = run_group(other_root, [0, 1])
    assert sorted(output.split(maxsplit=1)[0] for output in conflict) == [
        "conflict",
        "ok",
    ]
    assert len(list(other_root.glob("*.json"))) == 1


def test_reconcile_missed_stale_and_later_slot_recovery_are_deterministic(
    tmp_path: Path,
) -> None:
    store = RunJournalStoreV0(tmp_path)
    old_started = _started(store, run_id="entry-stale-001")
    next_expected = ExpectedRunV0.create(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT + timedelta(hours=1),
        run_id="entry-missed-002",
    )
    before_grace = store.reconcile(
        expected=(next_expected,),
        now=next_expected.expected_at + timedelta(seconds=29),
        grace_seconds=30,
        stale_seconds=7200,
        limit=10,
    )
    assert [record.status for record in before_grace] == [RunJournalStatusV0.STARTED]

    reconciled = store.reconcile(
        expected=(next_expected,),
        now=next_expected.expected_at + timedelta(seconds=31),
        grace_seconds=30,
        stale_seconds=60,
        limit=10,
    )
    assert [record.status for record in reconciled] == [
        RunJournalStatusV0.MISSED_EXPECTED,
        RunJournalStatusV0.STALE_INCOMPLETE,
    ]
    stale = next(record for record in reconciled if record.run_id == old_started.run_id)
    assert stale.started_at == STARTED_AT

    later = store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT + timedelta(hours=2),
        run_id="entry-recovery-003",
        started_at=EXPECTED_AT + timedelta(hours=2, seconds=1),
    )
    completed = store.finish(
        later,
        status=RunJournalStatusV0.PUBLISHED,
        terminal_at=EXPECTED_AT + timedelta(hours=2, seconds=2),
        report_file="2026-08-11.entry.decision-board.json",
    )
    statuses = store.status(limit=10)
    assert statuses[0].to_public_dict() == completed.to_public_dict()
    assert {record.status for record in statuses[1:]} == {
        RunJournalStatusV0.MISSED_EXPECTED,
        RunJournalStatusV0.STALE_INCOMPLETE,
    }


def test_runner_writes_started_before_call_maps_failed_and_leaves_crash_started(
    tmp_path: Path,
) -> None:
    store = RunJournalStoreV0(tmp_path)
    seen: list[RunJournalStatusV0] = []

    def failed_runner():
        seen.append(store.status(limit=1)[0].status)
        return create_decision_run_failed_v0(
            issue_code=DecisionRunIssueCodeV0.CONFIG_UNAVAILABLE
        )

    terminal, result = journal_decision_run_v0(
        store=store,
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id="entry-failed-001",
        started_at=STARTED_AT,
        terminal_at=lambda: TERMINAL_AT,
        run_once=failed_runner,
    )
    assert seen == [RunJournalStatusV0.STARTED]
    assert result.status == "FAILED"
    assert terminal.status is RunJournalStatusV0.FAILED
    assert terminal.issues[0].code == "CONFIG_UNAVAILABLE"

    class SyntheticCrash(BaseException):
        pass

    def crash():
        assert store.status(limit=1)[0].status is RunJournalStatusV0.STARTED
        raise SyntheticCrash("PRIVATE-SENTINEL")

    with pytest.raises(SyntheticCrash):
        journal_decision_run_v0(
            store=store,
            run_kind=RunKindV0.HOLDING,
            expected_at=EXPECTED_AT,
            run_id="holding-crash-001",
            started_at=STARTED_AT,
            terminal_at=lambda: TERMINAL_AT,
            run_once=crash,
        )
    crashed = next(
        record
        for record in store.status(limit=10)
        if record.run_id == "holding-crash-001"
    )
    assert crashed.status is RunJournalStatusV0.STARTED
    assert "PRIVATE-SENTINEL" not in json.dumps(crashed.to_public_dict())
