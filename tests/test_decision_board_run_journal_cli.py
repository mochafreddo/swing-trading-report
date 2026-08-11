from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.__main__ import _build_parser, _dispatch_command
from sab.decision_board.run_journal import RunJournalStoreV0
from sab.decision_board.runner import RunKindV0

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "scripts/launchd/sab-decision-board-shadow-wrapper.sh"
PLISTS = (
    REPO_ROOT
    / "scripts/launchd/com.mochafreddo.sab.decision-board.entry-shadow.plist.template",
    REPO_ROOT
    / "scripts/launchd/com.mochafreddo.sab.decision-board.holding-shadow.plist.template",
)


def test_status_and_reconcile_cli_are_bounded_typed_and_sanitized(
    capsys, tmp_path: Path
) -> None:
    store = RunJournalStoreV0(tmp_path)
    store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        run_id="entry-stale-001",
        started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC),
    )
    parser = _build_parser()
    reconcile = parser.parse_args(
        [
            "decision-board-journal-reconcile",
            "--journal-dir",
            str(tmp_path),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2026-08-11T02:00:00Z",
            "--run-id",
            "entry-missed-002",
            "--now",
            "2026-08-11T02:01:01Z",
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "60",
            "--limit",
            "2",
        ]
    )
    assert _dispatch_command(reconcile, parser) == 0
    reconciled = json.loads(capsys.readouterr().out)
    assert reconciled["count"] == 2
    assert [record["status"] for record in reconciled["records"]] == [
        "MISSED_EXPECTED",
        "STALE_INCOMPLETE",
    ]
    assert str(tmp_path) not in json.dumps(reconciled)

    status = parser.parse_args(
        [
            "decision-board-journal-status",
            "--journal-dir",
            str(tmp_path),
            "--status",
            "STALE_INCOMPLETE",
            "--limit",
            "1",
        ]
    )
    assert _dispatch_command(status, parser) == 0
    public = json.loads(capsys.readouterr().out)
    assert public["count"] == 1
    assert public["records"][0]["status"] == "STALE_INCOMPLETE"


def test_shadow_wrapper_dry_run_has_no_runner_or_journal_side_effect(
    tmp_path: Path,
) -> None:
    runner_marker = tmp_path / "PRIVATE-SENTINEL-runner-called"
    journal_dir = tmp_path / "journal"
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2026-08-11T01:00:00Z",
            "--run-id",
            "entry-shadow-001",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--dry-run",
            "--",
            str(tmp_path / "PRIVATE-SENTINEL-executable"),
            "-c",
            f"from pathlib import Path; Path({str(runner_marker)!r}).touch()",
            "PRIVATE-SENTINEL-RAW-ARG",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    public = json.loads(result.stdout)
    assert public == {
        "dry_run": True,
        "expected_at": "2026-08-11T01:00:00Z",
        "grace_seconds": 60,
        "run_id": "entry-shadow-001",
        "run_kind": "ENTRY",
        "runner_arg_count": 4,
        "stale_seconds": 300,
    }
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    assert not runner_marker.exists()
    assert not journal_dir.exists()


def test_shadow_wrapper_records_terminal_result_and_crash_stays_started(
    tmp_path: Path,
) -> None:
    journal_dir = tmp_path / "journal"
    failed = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2026-08-11T01:00:00Z",
            "--run-id",
            "entry-shadow-failed",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            (
                "import json,sys; "
                "print(json.dumps({'status':'FAILED','exit_code':2,"
                "'issue_code':'CONFIG_UNAVAILABLE'}), file=sys.stderr); "
                "raise SystemExit(2)"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 2
    status = RunJournalStoreV0(journal_dir).status(limit=10)
    assert status[0].status.value == "FAILED"
    assert status[0].issues[0].code == "CONFIG_UNAVAILABLE"

    crashed = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "HOLDING",
            "--expected-at",
            "2026-08-11T01:00:00Z",
            "--run-id",
            "holding-shadow-crashed",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(9)",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert crashed.returncode == 9
    states = {
        record.run_id: record.status.value
        for record in RunJournalStoreV0(journal_dir).status(limit=10)
    }
    assert states["holding-shadow-crashed"] == "STARTED"


@pytest.mark.parametrize("status", ["PUBLISHED", "BLOCKED"])
def test_shadow_wrapper_maps_stored_terminal_status(
    status: str, tmp_path: Path
) -> None:
    journal_dir = tmp_path / "journal"
    public = {
        "status": status,
        "exit_code": 0,
        "report_file": f"2026-08-11.{status.lower()}.decision-board.json",
        "storage_key": None,
        "degraded": False,
    }
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2026-08-11T01:00:00Z",
            "--run-id",
            f"entry-shadow-{status.lower()}",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            f"import json; print(json.dumps({public!r}))",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    record = RunJournalStoreV0(journal_dir).status(limit=1)[0]
    assert record.status.value == status
    assert record.report_file == public["report_file"]


def test_shadow_wrapper_rejects_raw_terminal_payload_and_leaves_started(
    tmp_path: Path,
) -> None:
    journal_dir = tmp_path / "journal"
    raw = {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
        "private_error": "PRIVATE-SENTINEL",
    }
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2026-08-11T01:00:00Z",
            "--run-id",
            "entry-shadow-raw",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            f"import json,sys; print(json.dumps({raw!r}), file=sys.stderr); raise SystemExit(2)",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    record = RunJournalStoreV0(journal_dir).status(limit=1)[0]
    assert record.status.value == "STARTED"
    assert "PRIVATE-SENTINEL" not in json.dumps(record.to_public_dict())


def test_shadow_wrapper_rejects_terminal_exit_code_mismatch(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    public = {
        "status": "PUBLISHED",
        "exit_code": 0,
        "report_file": "2026-08-11.published.decision-board.json",
        "storage_key": None,
        "degraded": False,
    }
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2026-08-11T01:00:00Z",
            "--run-id",
            "entry-shadow-exit-conflict",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            f"import json; print(json.dumps({public!r})); raise SystemExit(7)",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 7
    record = RunJournalStoreV0(journal_dir).status(limit=1)[0]
    assert record.status.value == "STARTED"


def test_wrapper_and_disabled_plists_are_local_notification_order_network_free() -> (
    None
):
    assert WRAPPER.is_file()
    assert os.access(WRAPPER, os.X_OK)
    assert "/logs/decision-board-journal/" in (REPO_ROOT / ".gitignore").read_text(
        encoding="utf-8"
    )
    sources = [WRAPPER.read_text(encoding="utf-8")]
    for path in PLISTS:
        payload = plistlib.loads(path.read_bytes())
        assert payload["Disabled"] is True
        assert "StartCalendarInterval" not in payload
        sources.append(path.read_text(encoding="utf-8"))
    joined = "\n".join(sources).lower()
    for forbidden in (
        "telegram",
        "slack",
        "notify",
        "curl",
        "http://",
        "https://",
        "github",
        "supabase",
        "toss",
        "create_order",
        "modify_order",
        "cancel_order",
        "broker",
    ):
        assert forbidden not in joined
