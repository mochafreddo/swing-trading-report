from __future__ import annotations

import copy
import json
import multiprocessing
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from sab.report.decision_board import (
    DecisionBoardIdempotencyConflictError,
    DecisionBoardStoragePathError,
    build_decision_board_storage_key,
    parse_decision_board_storage_key,
    write_decision_board_report,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "decision_board"


def _report(name: str = "published-entry.json") -> dict[str, Any]:
    value = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _process_write(args: tuple[str, dict[str, Any]]) -> tuple[str, str]:
    directory, report = args
    try:
        path = write_decision_board_report(report, report_dir=Path(directory))
    except DecisionBoardIdempotencyConflictError:
        return ("conflict", "")
    return ("ok", path.name)


def _process_write_to_queue(
    directory: str,
    report: dict[str, Any],
    results: multiprocessing.Queue[tuple[str, str]],
) -> None:
    results.put(_process_write((directory, report)))


def _run_process_writes(
    directory: Path,
    reports: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    ctx = multiprocessing.get_context("spawn")
    results = ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_write_to_queue,
            args=(str(directory), report, results),
        )
        for report in reports
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=10)
            assert not process.is_alive(), "Decision Board writer process hung"
            assert process.exitcode == 0
        return [results.get(timeout=1) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
        results.close()
        results.join_thread()


@pytest.mark.parametrize(
    "fixture_name", ["published-entry.json", "published-holding.json"]
)
def test_decision_board_key_round_trips_full_identity(fixture_name: str) -> None:
    report = _report(fixture_name)
    key = build_decision_board_storage_key(report)
    parsed = parse_decision_board_storage_key(key)

    created = datetime.fromisoformat(report["created_at"].replace("Z", "+00:00"))
    assert key.startswith(f"{created:%Y/%m}/{created.date()}.decision-board.")
    assert report["run_id"] in key
    assert report["idempotency_key"].removeprefix("sha256:") in key
    assert parsed is not None
    assert parsed.run_kind == report["run_kind"]
    assert parsed.run_id == report["run_id"]
    assert parsed.idempotency_key == report["idempotency_key"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "../escape"),
        ("run_id", "entry/report"),
        ("run_id", "entry\\report"),
        ("run_id", "entry\u202ejson"),
        ("run_id", "ｅｎｔｒｙ"),
        ("run_id", "a" * 129),
        ("run_kind", "entry"),
        ("created_at", "2026-02-30T01:00:05Z"),
    ],
)
def test_decision_board_key_rejects_unsafe_or_malformed_identity(
    field: str, value: str
) -> None:
    report = _report()
    report[field] = value

    with pytest.raises(ValueError):
        build_decision_board_storage_key(report)


def test_parser_rejects_key_payload_mismatch_and_invalid_calendar_date() -> None:
    report = _report()
    key = build_decision_board_storage_key(report)
    wrong = copy.deepcopy(report)
    wrong["run_id"] = "different-run"

    assert parse_decision_board_storage_key(key, report=wrong) is None
    assert (
        parse_decision_board_storage_key(key.replace("2026-08-06", "2026-02-30"))
        is None
    )


def test_same_identity_equal_bytes_is_idempotent(tmp_path: Path) -> None:
    report = _report()
    first = write_decision_board_report(report, report_dir=tmp_path)
    second = write_decision_board_report(copy.deepcopy(report), report_dir=tmp_path)

    assert second == first
    assert first.read_bytes().startswith(b'{"created_at"')
    assert list(tmp_path.glob("*.tmp")) == []


def test_same_identity_different_bytes_conflicts_and_preserves_winner(
    tmp_path: Path,
) -> None:
    first_report = _report()
    second_report = copy.deepcopy(first_report)
    second_report["metadata"] = {"compiler_version": "different"}
    first = write_decision_board_report(first_report, report_dir=tmp_path)
    original = first.read_bytes()

    with pytest.raises(DecisionBoardIdempotencyConflictError):
        write_decision_board_report(second_report, report_dir=tmp_path)

    assert first.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


def test_thread_and_process_concurrency_converge_or_conflict(tmp_path: Path) -> None:
    equal = _report()
    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(
            executor.map(
                lambda _: write_decision_board_report(equal, report_dir=tmp_path),
                range(16),
            )
        )
    assert len(set(paths)) == 1

    conflict_dir = tmp_path / "process"
    conflict_dir.mkdir()
    changed = copy.deepcopy(equal)
    changed["metadata"] = {"compiler_version": "process-racer"}
    results = _run_process_writes(conflict_dir, [equal, changed] * 4)
    assert {status for status, _ in results} == {"ok", "conflict"}
    assert len(list(conflict_dir.glob("*.json"))) == 1


def test_separate_process_equal_writes_converge_and_different_runs_stay_unique(
    tmp_path: Path,
) -> None:
    equal = _report()
    equal_results = _run_process_writes(tmp_path, [equal] * 6)

    assert {status for status, _ in equal_results} == {"ok"}
    assert len({name for _, name in equal_results}) == 1

    different_dir = tmp_path / "different"
    different_dir.mkdir()
    different_reports: list[dict[str, Any]] = []
    for index in range(6):
        report = _report()
        report["run_id"] = f"process-run-{index}"
        report["idempotency_key"] = f"sha256:{index:064x}"
        different_reports.append(report)

    different_results = _run_process_writes(different_dir, different_reports)
    assert {status for status, _ in different_results} == {"ok"}
    assert len({name for _, name in different_results}) == len(different_reports)


def test_different_run_identities_never_allocate_suffixes(tmp_path: Path) -> None:
    reports = []
    for index in range(8):
        report = _report()
        report["run_id"] = f"entry-run-{index}"
        report["idempotency_key"] = f"sha256:{index:064x}"
        reports.append(report)

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(
            executor.map(
                lambda report: write_decision_board_report(report, report_dir=tmp_path),
                reports,
            )
        )
    assert len(set(paths)) == len(reports)
    assert not any("-1.decision-board" in path.name for path in paths)


def test_symlink_or_non_regular_target_fails_closed(tmp_path: Path) -> None:
    report = _report()
    key = build_decision_board_storage_key(report)
    target = tmp_path / Path(key).name
    outside = tmp_path / "outside.json"
    outside.write_text("private", encoding="utf-8")
    target.symlink_to(outside)

    with pytest.raises(DecisionBoardStoragePathError):
        write_decision_board_report(report, report_dir=tmp_path)
    assert outside.read_text(encoding="utf-8") == "private"

    target.unlink()
    target.mkdir()
    with pytest.raises(DecisionBoardStoragePathError):
        write_decision_board_report(report, report_dir=tmp_path)


def test_serializer_failure_cleans_temp_and_writes_no_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sab.report.decision_board as storage

    report = _report()
    monkeypatch.setattr(
        storage,
        "canonical_json_bytes",
        lambda _value: (_ for _ in ()).throw(OSError("boom")),
    )

    with pytest.raises(OSError, match="boom"):
        write_decision_board_report(report, report_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_write_failure_cleans_hidden_temp_and_writes_no_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sab.report.decision_board as storage

    real_write = storage.os.write

    def failing_write(fd: int, payload: bytes | memoryview) -> int:
        if bytes(payload).startswith(b'{"created_at"'):
            raise OSError("write failed")
        return real_write(fd, payload)

    monkeypatch.setattr(storage.os, "write", failing_write)

    with pytest.raises(OSError, match="write failed"):
        write_decision_board_report(_report(), report_dir=tmp_path)

    assert list(tmp_path.glob("*.json")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_target_replacement_after_atomic_create_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sab.report.decision_board as storage

    real_link = storage.os.link

    def replacing_link(
        source: str,
        target: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        real_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        storage.os.unlink(target, dir_fd=dst_dir_fd)
        replacement = storage.os.open(
            target,
            storage.os.O_WRONLY | storage.os.O_CREAT | storage.os.O_EXCL,
            0o600,
            dir_fd=dst_dir_fd,
        )
        storage.os.write(replacement, b"replacement")
        storage.os.close(replacement)

    monkeypatch.setattr(storage.os, "link", replacing_link)

    with pytest.raises(DecisionBoardStoragePathError, match="changed"):
        write_decision_board_report(_report(), report_dir=tmp_path)


def test_directory_fsync_failure_removes_new_final_and_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sab.report.decision_board as storage

    real_fsync = storage.os.fsync

    def failing_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(storage.os.fstat(fd).st_mode):
            raise OSError("directory fsync failed")
        real_fsync(fd)

    monkeypatch.setattr(storage.os, "fsync", failing_directory_fsync)

    with pytest.raises(OSError, match="directory fsync failed"):
        write_decision_board_report(_report(), report_dir=tmp_path)

    assert list(tmp_path.glob("*.json")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_report_directory_symlink_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(DecisionBoardStoragePathError):
        write_decision_board_report(_report(), report_dir=linked)
    assert os.listdir(real) == []
