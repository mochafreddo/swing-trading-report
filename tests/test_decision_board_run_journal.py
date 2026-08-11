from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
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


@pytest.mark.parametrize("stage", ["anchor", "lock", "temp"])
def test_post_effect_open_baseexception_closes_fd_and_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    class SyntheticInterrupt(BaseException):
        pass

    real_open = run_journal.os.open
    interrupted = False

    def open_then_interrupt(*args: object, **kwargs: object) -> int:
        nonlocal interrupted
        fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
        target_arg = args[0]
        flags_arg = args[1]
        assert isinstance(target_arg, (str, Path))
        assert type(flags_arg) is int
        target = os.fspath(target_arg)
        flags = flags_arg
        matches = {
            "anchor": target == "/",
            "lock": target == ".run-journal-v0.lock" and not flags & os.O_CREAT,
            "temp": target.endswith(".tmp"),
        }[stage]
        if matches and not interrupted:
            interrupted = True
            raise SyntheticInterrupt
        return fd

    before_fds = set(os.listdir("/dev/fd"))
    monkeypatch.setattr(run_journal.os, "open", open_then_interrupt)
    with pytest.raises(SyntheticInterrupt):
        _started(RunJournalStoreV0(tmp_path), run_id=f"post-open-{stage}")
    assert interrupted
    assert set(os.listdir("/dev/fd")) == before_fds
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob("*.json")) == []


def test_post_effect_cleanup_baseexception_returns_durable_committed_record(
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
    committed = _started(RunJournalStoreV0(tmp_path), run_id="cleanup-post-effect")
    assert interrupted
    assert committed.status is RunJournalStatusV0.STARTED
    assert len(list(tmp_path.glob("*.json"))) == 1
    for path in (tmp_path / ".run-journal-v0.lock", Path("/")):
        probe_fd = os.open(path, os.O_RDONLY)
        try:
            run_journal.fcntl.flock(
                probe_fd,
                run_journal.fcntl.LOCK_EX | run_journal.fcntl.LOCK_NB,
            )
            run_journal.fcntl.flock(probe_fd, run_journal.fcntl.LOCK_UN)
        finally:
            os.close(probe_fd)


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
