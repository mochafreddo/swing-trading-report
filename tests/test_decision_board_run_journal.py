from __future__ import annotations

import json
import logging
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from contextlib import suppress
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
    RunJournalCommittedCleanupError,
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
GRACE_SECONDS = 60
STALE_SECONDS = 300


def _started(
    store: RunJournalStoreV0,
    *,
    run_id: str = "entry-slot-001",
    grace_seconds: int = GRACE_SECONDS,
    stale_seconds: int = STALE_SECONDS,
):
    return store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id=run_id,
        started_at=STARTED_AT,
        grace_seconds=grace_seconds,
        stale_seconds=stale_seconds,
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
        grace_seconds=GRACE_SECONDS,
        stale_seconds=STALE_SECONDS,
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
        "grace_seconds": GRACE_SECONDS,
        "stale_seconds": STALE_SECONDS,
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
        "grace_seconds": GRACE_SECONDS,
        "stale_seconds": STALE_SECONDS,
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
        grace_seconds=GRACE_SECONDS,
        stale_seconds=STALE_SECONDS,
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
            grace_seconds=GRACE_SECONDS,
            stale_seconds=STALE_SECONDS,
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


def test_schema_reuses_absolute_end_report_file_contract_for_every_file_branch(
    tmp_path: Path,
) -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas/decision-board.v0.schema.json"
        ).read_text(encoding="utf-8")
    )
    report_schema = schema["$defs"]["RunJournalReportFileV0"]
    assert report_schema == {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$(?![\\s\\S])",
    }
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
    failed_upload = {
        **published,
        "status": "FAILED",
        "issues": [
            {
                "code": "UPLOAD_FAILED",
                "message": "Run reported sanitized issue code UPLOAD_FAILED.",
            }
        ],
    }
    for record in (published, failed_upload):
        mutated = {**record, "report_file": f"{record['report_file']}\n"}
        assert list(validator.iter_errors(mutated)), mutated
        with pytest.raises(ValueError, match="report_file"):
            parse_run_journal_v0(mutated)


def test_schema_matches_runtime_run_journal_contract(tmp_path: Path) -> None:
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
    valid = started.to_public_dict()
    validator.validate(valid)

    invalid_records: list[dict[str, object]] = []
    missing_report_file = dict(valid)
    del missing_report_file["report_file"]
    invalid_records.append(missing_report_file)
    invalid_records.extend(
        [
            {**valid, "run_id": "../private"},
            {**valid, "run_id": "abc\n"},
            {**valid, "expected_at": "2026-08-11T10:00:00+09:00"},
            {**valid, "expected_at": "2026-08-11T01:00:00.1Z"},
            {**valid, "expected_at": None},
            {**valid, "terminal_at": "2026-08-11T01:00:02Z"},
            {
                **valid,
                "issues": [
                    {
                        "code": "MISSED_EXPECTED",
                        "message": "Expected run did not start before its grace deadline.",
                        "metadata": {"private": True},
                    }
                ],
            },
            {
                **valid,
                "status": "MISSED_EXPECTED",
                "started_at": None,
                "terminal_at": "2026-08-11T01:00:02Z",
                "issues": [
                    {
                        "code": "MISSED_EXPECTED",
                        "message": "wrong message",
                    }
                ],
            },
            {
                **valid,
                "status": "FAILED",
                "terminal_at": "2026-08-11T01:00:02Z",
                "issues": [],
            },
            {
                **valid,
                "status": "PUBLISHED",
                "terminal_at": "2026-08-11T01:00:02Z",
                "report_file": None,
            },
        ]
    )
    for invalid in invalid_records:
        assert list(validator.iter_errors(invalid)), invalid

    chronology = {**valid, "started_at": "2026-08-11T00:59:59Z"}
    assert list(validator.iter_errors(chronology)) == []
    with pytest.raises(ValueError, match="precede"):
        parse_run_journal_v0(chronology)
    assert "parse_run_journal_v0" in schema["$defs"]["RunJournalV0"]["$comment"]


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
            grace_seconds=GRACE_SECONDS,
            stale_seconds=STALE_SECONDS,
        ).to_public_dict()
        == started.to_public_dict()
    )

    with pytest.raises(RunJournalConflictError):
        store.start(
            run_kind=RunKindV0.ENTRY,
            expected_at=EXPECTED_AT,
            run_id="entry-slot-001",
            started_at=STARTED_AT + timedelta(seconds=1),
            grace_seconds=GRACE_SECONDS,
            stale_seconds=STALE_SECONDS,
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
            report_file="conflicting-published.json",
        )
    with pytest.raises(RunJournalConflictError):
        store.start(
            run_kind=RunKindV0.ENTRY,
            expected_at=EXPECTED_AT,
            run_id="entry-slot-001",
            started_at=STARTED_AT,
            grace_seconds=GRACE_SECONDS,
            stale_seconds=STALE_SECONDS,
        )


def test_atomic_transition_failure_preserves_started_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = RunJournalStoreV0(tmp_path)
    started = _started(store)
    journal_path = next(tmp_path.glob("*.json"))
    before = journal_path.read_bytes()

    def fail_write(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("PRIVATE-SENTINEL synthetic write failure")

    monkeypatch.setattr(run_journal, "_atomic_replace_record", fail_write)
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


def test_root_component_creation_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "missing" / "journal"

    def fail_mkdir(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("PRIVATE-SENTINEL mkdir failure")

    monkeypatch.setattr(run_journal.os, "mkdir", fail_mkdir)
    with pytest.raises(run_journal.RunJournalStorageError) as exc_info:
        _started(RunJournalStoreV0(root), run_id="mkdir-sanitized")
    assert "PRIVATE-SENTINEL" not in str(exc_info.value)


def test_search_only_ancestor_allows_write_status_and_revalidation(
    tmp_path: Path,
) -> None:
    ancestor = tmp_path / "search-only"
    nested = ancestor / "nested"
    root = nested / "journal"
    nested.mkdir(parents=True)
    # The first ancestor proves 0111 traversal; the second grants only
    # write+search so the final root must be created through mkdirat/search FD.
    nested.chmod(0o333)
    ancestor.chmod(0o111)
    try:
        store = RunJournalStoreV0(root)
        started = _started(store, run_id="search-only-ancestor")
        assert store.status(limit=1)[0].to_public_dict() == started.to_public_dict()
    finally:
        ancestor.chmod(0o700)
        nested.chmod(0o700)


def test_store_rejects_root_replacement_without_split_brain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    moved = tmp_path.parent / f"{tmp_path.name}-moved"
    real_flock = run_journal.fcntl.flock
    original_root_info = tmp_path.stat()
    replaced = False

    def replace_root(fd: int, operation: int) -> None:
        nonlocal replaced
        real_flock(fd, operation)
        info = os.fstat(fd)
        if (
            operation == run_journal.fcntl.LOCK_EX
            and (info.st_dev, info.st_ino)
            == (original_root_info.st_dev, original_root_info.st_ino)
            and not replaced
        ):
            replaced = True
            tmp_path.rename(moved)
            tmp_path.mkdir()

    monkeypatch.setattr(run_journal.fcntl, "flock", replace_root)
    with pytest.raises(run_journal.RunJournalStorageError, match=r"path|root"):
        _started(RunJournalStoreV0(tmp_path))

    assert list(tmp_path.glob("*.json")) == []
    assert list(moved.glob("*.json")) == []

    monkeypatch.setattr(run_journal.fcntl, "flock", real_flock)
    second = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from datetime import UTC,datetime; "
                "from sab.decision_board.run_journal import RunJournalStoreV0; "
                "from sab.decision_board.runner import RunKindV0; "
                f"RunJournalStoreV0({str(tmp_path)!r}).start("
                "run_kind=RunKindV0.ENTRY,"
                "expected_at=datetime(2026,8,11,1,0,tzinfo=UTC),"
                "run_id='entry-slot-001',"
                "started_at=datetime(2026,8,11,1,0,2,tzinfo=UTC),"
                "grace_seconds=60,stale_seconds=300)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert list(moved.glob("*.json")) == []


def test_parent_replacement_and_second_process_cannot_split_same_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    parent = tmp_path / "authority"
    root = parent / "journal"
    root.mkdir(parents=True)
    moved_parent = tmp_path / "authority-moved"
    original_root_info = root.stat()
    real_flock = run_journal.fcntl.flock
    second: subprocess.Popen[str] | None = None

    def replace_parent_when_root_is_locked(fd: int, operation: int) -> None:
        nonlocal second
        real_flock(fd, operation)
        info = os.fstat(fd)
        if (
            operation == run_journal.fcntl.LOCK_EX
            and (info.st_dev, info.st_ino)
            == (original_root_info.st_dev, original_root_info.st_ino)
            and second is None
        ):
            parent.rename(moved_parent)
            root.mkdir(parents=True)
            second = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "from datetime import UTC,datetime; "
                        "from sab.decision_board.run_journal import RunJournalStoreV0; "
                        "from sab.decision_board.runner import RunKindV0; "
                        f"RunJournalStoreV0({str(root)!r}).start("
                        "run_kind=RunKindV0.ENTRY,"
                        "expected_at=datetime(2026,8,11,1,0,tzinfo=UTC),"
                        "run_id='parent-split-probe',"
                        "started_at=datetime(2026,8,11,1,0,1,tzinfo=UTC),"
                        "grace_seconds=60,stale_seconds=300)"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    monkeypatch.setattr(run_journal.fcntl, "flock", replace_parent_when_root_is_locked)
    with pytest.raises(run_journal.RunJournalStorageError, match=r"path|root"):
        _started(RunJournalStoreV0(root), run_id="parent-split-probe")
    assert second is not None
    stdout, stderr = second.communicate(timeout=10)
    assert second.returncode == 0, (stdout, stderr)
    assert len(list(root.glob("*.json"))) == 1
    assert list((moved_parent / "journal").glob("*.json")) == []


def test_last_path_check_swap_rolls_back_pinned_root_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    moved = tmp_path.parent / f"{tmp_path.name}-last-check-moved"
    real_assert = run_journal._assert_root_unchanged
    checks = 0

    def swap_on_context_exit(root: object) -> None:
        nonlocal checks
        checks += 1
        if checks == 5:
            tmp_path.rename(moved)
            tmp_path.mkdir()
        real_assert(root)  # type: ignore[arg-type]

    monkeypatch.setattr(run_journal, "_assert_root_unchanged", swap_on_context_exit)
    with pytest.raises(run_journal.RunJournalStorageError, match=r"path|root"):
        _started(RunJournalStoreV0(tmp_path), run_id="last-path-check")
    assert list(tmp_path.glob("*.json")) == []
    assert list(moved.glob("*.json")) == []


def test_store_rejects_replaced_lock_path_before_record_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_flock = run_journal.fcntl.flock
    lock_path = tmp_path / ".run-journal-v0.lock"
    replaced = False

    def replace_lock(fd: int, operation: int) -> None:
        nonlocal replaced
        real_flock(fd, operation)
        if (
            operation == run_journal.fcntl.LOCK_EX
            and lock_path.exists()
            and not replaced
        ):
            replaced = True
            lock_path.unlink()
            lock_path.write_text("replacement", encoding="utf-8")

    monkeypatch.setattr(run_journal.fcntl, "flock", replace_lock)
    with pytest.raises(run_journal.RunJournalStorageError, match="lock"):
        _started(RunJournalStoreV0(tmp_path))
    assert list(tmp_path.glob("*.json")) == []


def test_post_replace_directory_fsync_failure_rolls_back_new_and_existing_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = RunJournalStoreV0(tmp_path)
    real_fsync = run_journal.os.fsync

    def fail_on_directory_call(call_to_fail: int):
        directory_calls = 0

        def fail_directory_fsync(fd: int) -> None:
            nonlocal directory_calls
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directory_calls += 1
                if directory_calls == call_to_fail:
                    raise OSError("synthetic post-replace directory fsync failure")
            real_fsync(fd)

        return fail_directory_fsync

    monkeypatch.setattr(run_journal.os, "fsync", fail_on_directory_call(1))
    with pytest.raises(run_journal.RunJournalStorageError):
        _started(store, run_id="new-fsync-failure")
    assert list(tmp_path.glob("*.json")) == []

    monkeypatch.setattr(run_journal.os, "fsync", real_fsync)
    started = _started(store, run_id="existing-fsync-failure")
    path = next(tmp_path.glob("*.json"))
    before = path.read_bytes()
    # The first directory fsync durably records the rollback link. The second
    # follows os.replace(), so this specifically exercises post-replace rollback.
    monkeypatch.setattr(run_journal.os, "fsync", fail_on_directory_call(2))
    with pytest.raises(run_journal.RunJournalStorageError):
        store.finish(
            started,
            status=RunJournalStatusV0.FAILED,
            terminal_at=TERMINAL_AT,
            issue_codes=(DecisionRunIssueCodeV0.INTERNAL_ERROR.value,),
        )
    assert path.read_bytes() == before


def test_baseexception_during_replace_propagates_and_releases_lock_and_fds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticInterrupt(BaseException):
        pass

    def interrupt_replace(*args, **kwargs) -> None:
        del args, kwargs
        raise SyntheticInterrupt

    monkeypatch.setattr(run_journal.os, "replace", interrupt_replace)
    with pytest.raises(SyntheticInterrupt):
        _started(RunJournalStoreV0(tmp_path), run_id="baseexception-cleanup")
    assert list(tmp_path.glob("*.tmp")) == []
    lock_fd = os.open(tmp_path / ".run-journal-v0.lock", os.O_RDWR)
    try:
        run_journal.fcntl.flock(
            lock_fd,
            run_journal.fcntl.LOCK_EX | run_journal.fcntl.LOCK_NB,
        )
        run_journal.fcntl.flock(lock_fd, run_journal.fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


@pytest.mark.parametrize("existing", [False, True])
def test_post_effect_replace_baseexception_rolls_back_before_rethrow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, existing: bool
) -> None:
    class SyntheticInterrupt(BaseException):
        pass

    store = RunJournalStoreV0(tmp_path)
    started = _started(store, run_id="post-effect") if existing else None
    before = next(tmp_path.glob("*.json")).read_bytes() if existing else None
    real_replace = run_journal.os.replace

    def replace_then_interrupt(*args: object, **kwargs: object) -> None:
        real_replace(*args, **kwargs)  # type: ignore[arg-type]
        raise SyntheticInterrupt

    monkeypatch.setattr(run_journal.os, "replace", replace_then_interrupt)
    with pytest.raises(SyntheticInterrupt):
        if started is None:
            _started(store, run_id="post-effect")
        else:
            store.finish(
                started,
                status=RunJournalStatusV0.FAILED,
                terminal_at=TERMINAL_AT,
                issue_codes=(DecisionRunIssueCodeV0.INTERNAL_ERROR.value,),
            )

    paths = list(tmp_path.glob("*.json"))
    if before is None:
        assert paths == []
    else:
        assert len(paths) == 1
        assert paths[0].read_bytes() == before


def test_directory_and_temp_fstat_baseexception_close_owned_resources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticInterrupt(BaseException):
        pass

    before_fds = len(os.listdir("/dev/fd"))
    monkeypatch.setattr(
        run_journal.os, "fstat", lambda _fd: (_ for _ in ()).throw(SyntheticInterrupt)
    )
    with pytest.raises(SyntheticInterrupt):
        run_journal._open_journal_directory(tmp_path)
    assert len(os.listdir("/dev/fd")) == before_fds

    monkeypatch.undo()
    directory_fd = os.open(tmp_path, os.O_RDONLY)
    try:
        before_fds = len(os.listdir("/dev/fd"))
        monkeypatch.setattr(
            run_journal.os,
            "fstat",
            lambda _fd: (_ for _ in ()).throw(SyntheticInterrupt),
        )
        with pytest.raises(SyntheticInterrupt):
            run_journal._write_private_temp(directory_fd, "probe.json", b"{}\n")
        assert len(os.listdir("/dev/fd")) == before_fds
        assert list(tmp_path.glob("*.tmp")) == []
    finally:
        monkeypatch.undo()
        os.close(directory_fd)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGUSR1])
def test_signal_interrupted_open_closes_only_returned_fd_not_foreign_same_inode(
    monkeypatch: pytest.MonkeyPatch,
    signum: signal.Signals,
) -> None:
    class SyntheticInterrupt(BaseException):
        pass

    real_open = run_journal.os.open
    real_close = run_journal.os.close
    owned_fd: int | None = None
    foreign_fd: int | None = None

    def raise_interrupt(_signum: int, _frame: object) -> None:
        raise SyntheticInterrupt

    def open_then_signal(*args: object, **kwargs: object) -> int:
        nonlocal owned_fd, foreign_fd
        fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        owned_fd = fd
        foreign_fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        os.kill(os.getpid(), signum)
        return fd

    previous_handler = signal.signal(signum, raise_interrupt)
    monkeypatch.setattr(run_journal.os, "open", open_then_signal)
    try:
        with pytest.raises(SyntheticInterrupt):
            run_journal._owned_open("/dev/null", os.O_RDONLY)
        assert owned_fd is not None
        with pytest.raises(OSError) as closed_error:
            os.fstat(owned_fd)
        assert closed_error.value.errno == 9
        assert foreign_fd is not None
        os.fstat(foreign_fd)
    finally:
        signal.signal(signum, previous_handler)
        if owned_fd is not None:
            with suppress(OSError):
                real_close(owned_fd)
        if foreign_fd is not None:
            with suppress(OSError):
                real_close(foreign_fd)


def test_owned_open_queries_mask_then_recovers_block_post_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticMaskInterrupt(BaseException):
        pass

    real_sigmask = signal.pthread_sigmask
    real_open = os.open
    original_mask = real_sigmask(signal.SIG_BLOCK, frozenset())
    calls: list[tuple[int, frozenset[int | signal.Signals]]] = []
    block_injected = False
    open_called = False

    def mask_then_interrupt(
        how: int,
        mask: set[int | signal.Signals] | frozenset[int | signal.Signals],
    ) -> set[int | signal.Signals]:
        nonlocal block_injected
        frozen = frozenset(mask)
        calls.append((how, frozen))
        result = real_sigmask(how, mask)
        if how == signal.SIG_BLOCK and frozen and not block_injected:
            block_injected = True
            raise SyntheticMaskInterrupt
        return result

    def observe_open(*args: object, **kwargs: object) -> int:
        nonlocal open_called
        open_called = True
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(run_journal.signal, "pthread_sigmask", mask_then_interrupt)
    monkeypatch.setattr(run_journal.os, "open", observe_open)
    try:
        with pytest.raises(SyntheticMaskInterrupt):
            run_journal._owned_open("/dev/null", os.O_RDONLY)
        assert calls[0] == (signal.SIG_BLOCK, frozenset())
        assert calls[1] == (
            signal.SIG_BLOCK,
            frozenset(signal.valid_signals() - {signal.SIGKILL, signal.SIGSTOP}),
        )
        assert real_sigmask(signal.SIG_BLOCK, frozenset()) == original_mask
        assert not open_called
    finally:
        real_sigmask(signal.SIG_SETMASK, original_mask)


def test_owned_open_verifies_mask_after_restore_post_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticMaskInterrupt(BaseException):
        pass

    real_sigmask = signal.pthread_sigmask
    real_open = os.open
    original_mask = real_sigmask(signal.SIG_BLOCK, frozenset())
    query_count = 0
    restore_injected = False
    owned_fd: int | None = None

    def mask_then_interrupt(
        how: int,
        mask: set[int | signal.Signals] | frozenset[int | signal.Signals],
    ) -> set[int | signal.Signals]:
        nonlocal query_count, restore_injected
        frozen = frozenset(mask)
        result = real_sigmask(how, mask)
        if how == signal.SIG_BLOCK and not frozen:
            query_count += 1
        if how == signal.SIG_SETMASK and not restore_injected:
            restore_injected = True
            raise SyntheticMaskInterrupt
        return result

    def capture_open(*args: object, **kwargs: object) -> int:
        nonlocal owned_fd
        owned_fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        return owned_fd

    monkeypatch.setattr(run_journal.signal, "pthread_sigmask", mask_then_interrupt)
    monkeypatch.setattr(run_journal.os, "open", capture_open)
    try:
        with pytest.raises(SyntheticMaskInterrupt):
            run_journal._owned_open("/dev/null", os.O_RDONLY)
        assert query_count >= 2
        assert real_sigmask(signal.SIG_BLOCK, frozenset()) == original_mask
        assert owned_fd is not None
        with pytest.raises(OSError) as closed_error:
            os.fstat(owned_fd)
        assert closed_error.value.errno == 9
    finally:
        real_sigmask(signal.SIG_SETMASK, original_mask)
        if owned_fd is not None:
            with suppress(OSError):
                os.close(owned_fd)


def test_owned_open_resolves_path_callback_before_masking() -> None:
    original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, frozenset())
    callback_masks: list[set[int | signal.Signals]] = []

    class ObservedPath:
        def __fspath__(self) -> str:
            callback_masks.append(signal.pthread_sigmask(signal.SIG_BLOCK, frozenset()))
            return "/dev/null"

    fd = run_journal._owned_open(ObservedPath(), os.O_RDONLY)
    try:
        assert callback_masks == [original_mask]
    finally:
        os.close(fd)


def test_owned_open_rechecks_threads_after_path_callback_before_create(
    tmp_path: Path,
) -> None:
    target = tmp_path / "callback-created"
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait)
    before_fds = len(os.listdir("/dev/fd"))
    opened_fd: int | None = None

    class StartsWorkerPath:
        def __fspath__(self) -> str:
            worker.start()
            return str(target)

    try:
        with pytest.raises(run_journal.RunJournalStorageError, match="single-threaded"):
            opened_fd = run_journal._owned_open(
                StartsWorkerPath(),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        assert not target.exists()
        assert len(os.listdir("/dev/fd")) == before_fds
    finally:
        if opened_fd is not None:
            with suppress(OSError):
                os.close(opened_fd)
        stop.set()
        if worker.ident is not None:
            worker.join()


def test_pending_signal_starts_worker_before_mkdir_and_fails_without_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal_root = tmp_path / "signal-mkdir-target"
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait)
    real_open = run_journal.os.open
    injected = False
    before_fds = len(os.listdir("/dev/fd"))

    def start_worker(_signum: int, _frame: object) -> None:
        if worker.ident is None:
            worker.start()

    def open_with_pending_signal(*args: object, **kwargs: object) -> int:
        nonlocal injected
        if args and args[0] == journal_root.name and not injected:
            injected = True
            os.kill(os.getpid(), signal.SIGUSR1)
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    previous_handler = signal.signal(signal.SIGUSR1, start_worker)
    monkeypatch.setattr(run_journal.os, "open", open_with_pending_signal)
    try:
        with pytest.raises(run_journal.RunJournalStorageError, match="single-threaded"):
            RunJournalStoreV0(journal_root).status(limit=1)
        assert injected
        assert worker.ident is not None
        assert not journal_root.exists()
        assert len(os.listdir("/dev/fd")) == before_fds
    finally:
        signal.signal(signal.SIGUSR1, previous_handler)
        stop.set()
        if worker.ident is not None:
            worker.join()


def test_pending_signal_after_temp_create_keeps_cleanup_in_transaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticPreCommitFailure(BaseException):
        pass

    stop = threading.Event()
    worker = threading.Thread(target=stop.wait)
    real_open = run_journal.os.open
    real_write = run_journal.os.write
    signal_injected = False
    write_called = False
    before_fds = len(os.listdir("/dev/fd"))

    def start_worker(_signum: int, _frame: object) -> None:
        if worker.ident is None:
            worker.start()

    def open_temp_then_signal(*args: object, **kwargs: object) -> int:
        nonlocal signal_injected
        fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        path = args[0] if args else kwargs.get("path")
        if (
            type(path) is str
            and path.startswith(".")
            and path.endswith(".tmp")
            and not signal_injected
        ):
            signal_injected = True
            os.kill(os.getpid(), signal.SIGUSR1)
        return fd

    def fail_write(_fd: int, _payload: object) -> int:
        nonlocal write_called
        write_called = True
        raise SyntheticPreCommitFailure

    previous_handler = signal.signal(signal.SIGUSR1, start_worker)
    monkeypatch.setattr(run_journal.os, "open", open_temp_then_signal)
    monkeypatch.setattr(run_journal.os, "write", fail_write)
    try:
        with pytest.raises(SyntheticPreCommitFailure):
            _started(RunJournalStoreV0(tmp_path), run_id="signal-after-temp")
        assert signal_injected
        assert write_called
        assert worker.ident is not None
        assert list(tmp_path.glob(".*.tmp")) == []
        assert list(tmp_path.glob("*.json")) == []
        assert len(os.listdir("/dev/fd")) == before_fds
    finally:
        signal.signal(signal.SIGUSR1, previous_handler)
        monkeypatch.setattr(run_journal.os, "write", real_write)
        stop.set()
        if worker.ident is not None:
            worker.join()


def test_pending_signal_after_replace_rolls_back_exact_original_before_handler(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticPreCommitFailure(BaseException):
        pass

    store = RunJournalStoreV0(tmp_path)
    started = _started(store, run_id="signal-after-replace")
    record_path = next(tmp_path.glob("*.json"))
    original = record_path.read_bytes()
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait)
    real_replace = run_journal.os.replace
    real_fsync = run_journal.os.fsync
    replaced = False
    post_replace_fsync_called = False
    before_fds = len(os.listdir("/dev/fd"))

    def start_worker(_signum: int, _frame: object) -> None:
        if worker.ident is None:
            worker.start()

    def replace_then_signal(*args: object, **kwargs: object) -> None:
        nonlocal replaced
        real_replace(*args, **kwargs)  # type: ignore[arg-type]
        target = args[1] if len(args) > 1 else kwargs.get("dst")
        if target == record_path.name and not replaced:
            replaced = True
            os.kill(os.getpid(), signal.SIGUSR1)

    def fail_post_replace_fsync(fd: int) -> None:
        nonlocal post_replace_fsync_called
        if replaced and not post_replace_fsync_called:
            post_replace_fsync_called = True
            raise SyntheticPreCommitFailure
        real_fsync(fd)

    previous_handler = signal.signal(signal.SIGUSR1, start_worker)
    monkeypatch.setattr(run_journal.os, "replace", replace_then_signal)
    monkeypatch.setattr(run_journal.os, "fsync", fail_post_replace_fsync)
    try:
        with pytest.raises(SyntheticPreCommitFailure):
            store.finish(
                started,
                status=RunJournalStatusV0.FAILED,
                terminal_at=TERMINAL_AT,
                issue_codes=(DecisionRunIssueCodeV0.INTERNAL_ERROR.value,),
            )
        assert replaced
        assert post_replace_fsync_called
        assert worker.ident is not None
        assert record_path.read_bytes() == original
        assert list(tmp_path.glob(".*.tmp")) == []
        assert list(tmp_path.glob(".*.backup")) == []
        assert len(os.listdir("/dev/fd")) == before_fds
    finally:
        signal.signal(signal.SIGUSR1, previous_handler)
        monkeypatch.setattr(run_journal.os, "fsync", real_fsync)
        stop.set()
        if worker.ident is not None:
            worker.join()


def test_owned_open_fails_closed_before_open_with_multiple_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait)
    worker.start()
    open_called = False
    real_open = run_journal.os.open

    def observe_open(*args: object, **kwargs: object) -> int:
        nonlocal open_called
        open_called = True
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(run_journal.os, "open", observe_open)
    try:
        with pytest.raises(run_journal.RunJournalStorageError, match="single-threaded"):
            run_journal._owned_open("/dev/null", os.O_RDONLY)
        assert not open_called
    finally:
        stop.set()
        worker.join()


def test_store_fails_closed_before_mutation_with_multiple_threads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    journal_root = tmp_path / "journal"
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait)
    worker.start()
    open_called = False
    real_open = run_journal.os.open

    def observe_open(*args: object, **kwargs: object) -> int:
        nonlocal open_called
        open_called = True
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(run_journal.os, "open", observe_open)
    try:
        with pytest.raises(run_journal.RunJournalStorageError, match="single-threaded"):
            _started(RunJournalStoreV0(journal_root), run_id="threaded")
        assert not open_called
        assert not journal_root.exists()
    finally:
        stop.set()
        worker.join()


@pytest.mark.parametrize("helper", ["ordinary", "cleanup"])
def test_close_never_retries_reused_fd_number(
    monkeypatch: pytest.MonkeyPatch, helper: str
) -> None:
    class SyntheticCloseInterrupt(BaseException):
        pass

    real_close = run_journal.os.close
    source_fd = os.open("/dev/null", os.O_RDONLY)
    target_fd = os.dup(source_fd)
    injected = False

    def close_then_reuse(fd: int) -> None:
        nonlocal injected
        if fd == target_fd and not injected:
            injected = True
            real_close(fd)
            os.dup2(source_fd, fd)
            raise SyntheticCloseInterrupt
        real_close(fd)

    monkeypatch.setattr(run_journal.os, "close", close_then_reuse)
    try:
        if helper == "ordinary":
            with pytest.raises(SyntheticCloseInterrupt):
                run_journal._close_fd(target_fd)
        else:
            error, closed = run_journal._cleanup_close_fd(target_fd)
            assert isinstance(error, SyntheticCloseInterrupt)
            assert closed is False
        os.fstat(target_fd)
    finally:
        monkeypatch.setattr(run_journal.os, "close", real_close)
        with suppress(OSError):
            real_close(target_fd)
        real_close(source_fd)


def test_cleanup_reused_fd_is_not_reclosed_and_reports_committed_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticCleanupInterrupt(BaseException):
        pass

    real_replace = run_journal.os.replace
    real_close = run_journal.os.close
    source_fd = os.open("/dev/null", os.O_RDONLY)
    reused_fd: int | None = None
    replaced = False
    interrupted = False

    def mark_replace(*args: object, **kwargs: object) -> None:
        nonlocal replaced
        real_replace(*args, **kwargs)  # type: ignore[arg-type]
        replaced = True

    def close_then_interrupt(fd: int) -> None:
        nonlocal interrupted, reused_fd
        real_close(fd)
        if replaced and not interrupted:
            interrupted = True
            os.dup2(source_fd, fd)
            reused_fd = fd
            raise SyntheticCleanupInterrupt

    monkeypatch.setattr(run_journal.os, "replace", mark_replace)
    monkeypatch.setattr(run_journal.os, "close", close_then_interrupt)
    try:
        with pytest.raises(RunJournalCommittedCleanupError) as exc_info:
            _started(RunJournalStoreV0(tmp_path), run_id="cleanup-reused-fd")
        assert interrupted
        assert exc_info.value.run_id == "cleanup-reused-fd"
        assert exc_info.value.status == "STARTED"
        assert exc_info.value.expected_at == "2026-08-11T01:00:00Z"
        assert reused_fd is not None
        os.fstat(reused_fd)
        assert len(list(tmp_path.glob("*.json"))) == 1
    finally:
        monkeypatch.setattr(run_journal.os, "close", real_close)
        if reused_fd is not None:
            with suppress(OSError):
                real_close(reused_fd)
        real_close(source_fd)


def test_cleanup_close_post_effect_ebadf_recovers_committed_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticCleanupInterrupt(BaseException):
        pass

    real_replace = run_journal.os.replace
    real_close = run_journal.os.close
    replaced = False
    interrupted = False

    def mark_replace(*args: object, **kwargs: object) -> None:
        nonlocal replaced
        real_replace(*args, **kwargs)  # type: ignore[arg-type]
        replaced = True

    def close_then_interrupt(fd: int) -> None:
        nonlocal interrupted
        real_close(fd)
        if replaced and not interrupted:
            interrupted = True
            raise SyntheticCleanupInterrupt

    monkeypatch.setattr(run_journal.os, "replace", mark_replace)
    monkeypatch.setattr(run_journal.os, "close", close_then_interrupt)

    record = _started(RunJournalStoreV0(tmp_path), run_id="cleanup-post-effect")

    assert interrupted
    assert record.run_id == "cleanup-post-effect"
    assert record.status is RunJournalStatusV0.STARTED
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_next_locked_operation_sweeps_and_observes_safe_orphan_backup(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    store = RunJournalStoreV0(tmp_path)
    _started(store, run_id="orphan-sweep")
    record_path = next(tmp_path.glob("*.json"))
    backup_path = tmp_path / f".{record_path.name}.{'a' * 24}.backup"
    os.link(record_path, backup_path)
    caplog.set_level(logging.INFO, logger=run_journal.__name__)

    assert store.status(limit=1)[0].run_id == "orphan-sweep"
    assert not backup_path.exists()
    assert "swept 1 orphan RunJournal backup(s)" in caplog.text


def test_unclosed_resource_after_commit_raises_safe_typed_cleanup_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real_replace = run_journal.os.replace
    real_close = run_journal.os.close
    replaced = False
    blocked_fds: set[int] = set()

    def mark_replace(*args: object, **kwargs: object) -> None:
        nonlocal replaced
        real_replace(*args, **kwargs)  # type: ignore[arg-type]
        replaced = True

    def fail_close(fd: int) -> None:
        if replaced:
            blocked_fds.add(fd)
            raise OSError("PRIVATE-SENTINEL committed cleanup failure")
        real_close(fd)

    monkeypatch.setattr(run_journal.os, "replace", mark_replace)
    monkeypatch.setattr(run_journal.os, "close", fail_close)
    try:
        with pytest.raises(run_journal.RunJournalStorageError) as exc_info:
            _started(RunJournalStoreV0(tmp_path), run_id="cleanup-unclosed")
        assert isinstance(exc_info.value, RunJournalCommittedCleanupError)
        assert exc_info.value.run_id == "cleanup-unclosed"
        assert exc_info.value.status == "STARTED"
        assert exc_info.value.expected_at == "2026-08-11T01:00:00Z"
        assert "PRIVATE-SENTINEL" not in str(exc_info.value)
        assert len(blocked_fds) >= 3
        assert len(list(tmp_path.glob("*.json"))) == 1
    finally:
        monkeypatch.setattr(run_journal.os, "close", real_close)
        for fd in blocked_fds:
            with suppress(OSError):
                run_journal.fcntl.flock(fd, run_journal.fcntl.LOCK_UN)
            with suppress(OSError):
                real_close(fd)


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
        grace_seconds=60,
        stale_seconds=300,
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
    old_started = _started(
        store,
        run_id="entry-stale-001",
        grace_seconds=30,
        stale_seconds=60,
    )
    next_expected = ExpectedRunV0.create(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT + timedelta(hours=1),
        run_id="entry-missed-002",
    )
    old_expected = ExpectedRunV0.create(
        run_kind=old_started.run_kind,
        expected_at=old_started.expected_at,
        run_id=old_started.run_id,
    )
    before_grace = store.reconcile(
        expected=(old_expected, next_expected),
        now=STARTED_AT + timedelta(seconds=59),
        grace_seconds=30,
        stale_seconds=60,
        limit=10,
    )
    assert [record.status for record in before_grace] == [RunJournalStatusV0.STARTED]

    reconciled = store.reconcile(
        expected=(old_expected, next_expected),
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
        grace_seconds=GRACE_SECONDS,
        stale_seconds=STALE_SECONDS,
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


def test_expected_slot_rejects_raw_subclass_and_mutation(tmp_path: Path) -> None:
    issued = ExpectedRunV0.create(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id="entry-issued-slot",
    )
    raw = object.__new__(ExpectedRunV0)
    for name in ("run_kind", "expected_at", "run_id"):
        object.__setattr__(raw, name, getattr(issued, name))

    class ExpectedSubclass(ExpectedRunV0):
        pass

    subclassed = object.__new__(ExpectedSubclass)
    for name in ("run_kind", "expected_at", "run_id"):
        object.__setattr__(subclassed, name, getattr(issued, name))

    store = RunJournalStoreV0(tmp_path)
    for invalid in (raw, subclassed):
        with pytest.raises(TypeError, match=r"issued|exact"):
            store.reconcile(
                expected=(invalid,),  # type: ignore[arg-type]
                now=EXPECTED_AT + timedelta(minutes=1),
                grace_seconds=30,
                stale_seconds=60,
                limit=10,
            )

    object.__setattr__(issued, "run_id", "mutated")
    with pytest.raises(TypeError, match="unchanged"):
        store.reconcile(
            expected=(issued,),
            now=EXPECTED_AT + timedelta(minutes=1),
            grace_seconds=30,
            stale_seconds=60,
            limit=10,
        )


def test_reconcile_stales_only_explicitly_supplied_identity(tmp_path: Path) -> None:
    store = RunJournalStoreV0(tmp_path)
    selected = _started(
        store,
        run_id="entry-selected-stale",
        grace_seconds=30,
        stale_seconds=60,
    )
    unrelated = _started(store, run_id="entry-unrelated-started")
    expected = ExpectedRunV0.create(
        run_kind=selected.run_kind,
        expected_at=selected.expected_at,
        run_id=selected.run_id,
    )
    store.reconcile(
        expected=(expected,),
        now=STARTED_AT + timedelta(seconds=61),
        grace_seconds=30,
        stale_seconds=60,
        limit=10,
    )
    states = {record.run_id: record.status for record in store.status(limit=10)}
    assert states[selected.run_id] is RunJournalStatusV0.STALE_INCOMPLETE
    assert states[unrelated.run_id] is RunJournalStatusV0.STARTED


def test_stale_policy_is_persisted_and_cannot_be_reinterpreted(tmp_path: Path) -> None:
    store = RunJournalStoreV0(tmp_path)
    started = store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=EXPECTED_AT,
        run_id="entry-policy-bound",
        started_at=STARTED_AT,
        grace_seconds=30,
        stale_seconds=300,
    )
    assert started.to_public_dict()["grace_seconds"] == 30
    assert started.to_public_dict()["stale_seconds"] == 300
    expected = ExpectedRunV0.create(
        run_kind=started.run_kind,
        expected_at=started.expected_at,
        run_id=started.run_id,
    )

    with pytest.raises(RunJournalConflictError, match="policy"):
        store.reconcile(
            expected=(expected,),
            now=STARTED_AT + timedelta(seconds=60),
            grace_seconds=30,
            stale_seconds=1,
            limit=10,
        )
    assert store.status(limit=1)[0].status is RunJournalStatusV0.STARTED


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
        grace_seconds=GRACE_SECONDS,
        stale_seconds=STALE_SECONDS,
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
            grace_seconds=GRACE_SECONDS,
            stale_seconds=STALE_SECONDS,
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
