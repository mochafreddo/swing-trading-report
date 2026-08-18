from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sab.decision_board.run_journal_cli as run_journal_cli
from sab.__main__ import _build_parser, _dispatch_command
from sab.decision_board.run_journal import RunJournalStoreV0
from sab.decision_board.run_journal_cli import JournalShadowProcessConfigV0
from sab.decision_board.runner import RunKindV0
from sab.decision_board.shadow_gate import load_shadow_gate_manifest_v0

REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "scripts/launchd/sab-decision-board-shadow-wrapper.sh"
PLISTS = (
    REPO_ROOT
    / "scripts/launchd/com.mochafreddo.sab.decision-board.entry-shadow.plist.template",
    REPO_ROOT
    / "scripts/launchd/com.mochafreddo.sab.decision-board.holding-shadow.plist.template",
)
GATE_MANIFEST = REPO_ROOT / "config" / "decision-board-shadow-gate.proposed.json"


def _current_slot_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _t7_basename(run_kind: str, run_id: str, *, expected_at: str) -> str:
    return (
        f"{expected_at[:10]}.decision-board.{run_kind.lower()}.{run_id}.{'a' * 64}.json"
    )


def _run_terminal_script(
    tmp_path: Path,
    *,
    run_id: str,
    script: str,
) -> tuple[subprocess.CompletedProcess[str], RunJournalStoreV0]:
    journal_dir = tmp_path / run_id
    expected_at = _current_slot_text()
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            expected_at,
            "--run-id",
            run_id,
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "60",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            script,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, RunJournalStoreV0(journal_dir)


def test_status_and_reconcile_cli_are_bounded_typed_and_sanitized(
    capsys, tmp_path: Path
) -> None:
    store = RunJournalStoreV0(tmp_path)
    store.start(
        run_kind=RunKindV0.ENTRY,
        expected_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),
        run_id="entry-stale-001",
        started_at=datetime(2026, 8, 11, 1, 0, 1, tzinfo=UTC),
        grace_seconds=60,
        stale_seconds=60,
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
            "2026-08-11T01:00:00Z",
            "--run-id",
            "entry-stale-001",
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
    assert reconciled["count"] == 1
    assert [record["status"] for record in reconciled["records"]] == [
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
    expected_at = _current_slot_text()
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            expected_at,
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
        "expected_at": expected_at,
        "grace_seconds": 60,
        "run_id": "entry-shadow-001",
        "run_kind": "ENTRY",
        "runner_arg_count": 4,
        "stale_seconds": 300,
    }
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    assert not runner_marker.exists()
    assert not journal_dir.exists()


def test_shadow_wrapper_binds_manifest_hash_slot_and_runner_identity(
    tmp_path: Path,
) -> None:
    manifest = load_shadow_gate_manifest_v0(GATE_MANIFEST)
    runner = [
        sys.executable,
        "-c",
        "raise SystemExit(0)",
        "--gate-manifest-sha256",
        manifest.manifest_sha256,
    ]
    config = JournalShadowProcessConfigV0.from_strings(
        run_kind="ENTRY",
        expected_at="2026-08-24T12:30:00Z",
        run_id="entry-shadow-20260824",
        journal_dir=str(tmp_path / "journal"),
        grace_seconds="300",
        stale_seconds="1800",
        runner_args=runner,
        dry_run=True,
        gate_manifest=str(GATE_MANIFEST),
        gate_manifest_sha256=manifest.manifest_sha256,
    )

    assert run_journal_cli.execute_journal_shadow_process_v0(config) == 0
    assert config.dry_run_public_dict()["gate_manifest_sha256"] == (
        manifest.manifest_sha256
    )

    mismatched = JournalShadowProcessConfigV0.from_strings(
        run_kind="ENTRY",
        expected_at="2026-08-24T12:30:00Z",
        run_id="entry-shadow-20260824",
        journal_dir=str(tmp_path / "mismatch"),
        grace_seconds="300",
        stale_seconds="1800",
        runner_args=runner,
        dry_run=True,
        gate_manifest=str(GATE_MANIFEST),
        gate_manifest_sha256="sha256:" + "f" * 64,
    )
    with pytest.raises(ValueError, match="manifest hash"):
        run_journal_cli.execute_journal_shadow_process_v0(mismatched)
    assert not mismatched.journal_dir.exists()

    unbound_equals_form = JournalShadowProcessConfigV0.from_strings(
        run_kind="ENTRY",
        expected_at="2026-08-24T12:30:00Z",
        run_id="entry-shadow-20260824",
        journal_dir=str(tmp_path / "unbound-equals"),
        grace_seconds="300",
        stale_seconds="1800",
        runner_args=[
            sys.executable,
            f"--gate-manifest-sha256={manifest.manifest_sha256}",
        ],
        dry_run=True,
    )
    with pytest.raises(ValueError, match="unbound"):
        run_journal_cli.execute_journal_shadow_process_v0(unbound_equals_form)
    assert not unbound_equals_form.journal_dir.exists()


def test_non_dry_journal_validates_approved_bundle_before_claiming_started(
    tmp_path: Path,
) -> None:
    manifest = load_shadow_gate_manifest_v0(GATE_MANIFEST)
    journal_dir = tmp_path / "must-not-start"
    config = JournalShadowProcessConfigV0.from_strings(
        run_kind="ENTRY",
        expected_at="2026-08-24T12:30:00Z",
        run_id="entry-shadow-20260824",
        journal_dir=str(journal_dir),
        grace_seconds="300",
        stale_seconds="1800",
        runner_args=[
            sys.executable,
            "-m",
            "sab",
            "decision-board-shadow-live",
            "--gate-manifest-sha256",
            manifest.manifest_sha256,
            "--input-ledger",
            str(tmp_path / "input-ledger.json"),
            "--expected-action-ledger",
            str(tmp_path / "expected-action-ledger.json"),
        ],
        dry_run=False,
        gate_manifest=str(GATE_MANIFEST),
        gate_manifest_sha256=manifest.manifest_sha256,
        input_ledger=str(tmp_path / "input-ledger.json"),
        expected_action_ledger=str(tmp_path / "expected-action-ledger.json"),
    )

    with pytest.raises(ValueError, match="approval"):
        run_journal_cli.execute_journal_shadow_process_v0(config)
    assert not journal_dir.exists()


def test_shadow_wrapper_records_terminal_result_and_crash_stays_started(
    tmp_path: Path,
) -> None:
    journal_dir = tmp_path / "journal"
    expected_at = _current_slot_text()
    failed = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            expected_at,
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
            expected_at,
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
    assert crashed.returncode == 2
    assert json.loads(crashed.stderr) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "JOURNAL_RUNNER_INVALID",
    }
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
    run_id = f"entry-shadow-{status.lower()}"
    expected_at = _current_slot_text()
    public = {
        "status": status,
        "exit_code": 0,
        "report_file": _t7_basename("ENTRY", run_id, expected_at=expected_at),
        "storage_key": None,
        "degraded": False,
    }
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            expected_at,
            "--run-id",
            run_id,
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
    expected_at = _current_slot_text()
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
            expected_at,
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
    expected_at = _current_slot_text()
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
            expected_at,
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
    assert result.returncode == 2
    assert json.loads(result.stderr) == {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "JOURNAL_RUNNER_INVALID",
    }
    record = RunJournalStoreV0(journal_dir).status(limit=1)[0]
    assert record.status.value == "STARTED"


def test_shadow_wrapper_never_relays_raw_runner_output(tmp_path: Path) -> None:
    public = {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    result, store = _run_terminal_script(
        tmp_path,
        run_id="entry-raw-output",
        script=(
            "import json,sys; print('PRIVATE-SENTINEL raw stdout'); "
            f"print(json.dumps({public!r}), file=sys.stderr); raise SystemExit(2)"
        ),
    )
    assert result.returncode == 2
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    assert json.loads(result.stderr) == {
        "exit_code": 2,
        "issue_code": "JOURNAL_RUNNER_INVALID",
        "status": "FAILED",
    }
    assert store.status(limit=1)[0].status.value == "STARTED"


def test_shadow_wrapper_requires_exactly_one_terminal_result(tmp_path: Path) -> None:
    public = {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    result, store = _run_terminal_script(
        tmp_path,
        run_id="entry-multiple-terminal",
        script=(
            "import json,sys; value="
            f"{public!r}; print(json.dumps(value), file=sys.stderr); "
            "print(json.dumps(value), file=sys.stderr); raise SystemExit(2)"
        ),
    )
    assert result.returncode == 2
    assert json.loads(result.stderr)["issue_code"] == "JOURNAL_RUNNER_INVALID"
    assert store.status(limit=1)[0].status.value == "STARTED"


def test_shadow_wrapper_missing_terminal_is_sanitized_nonzero(tmp_path: Path) -> None:
    result, store = _run_terminal_script(
        tmp_path,
        run_id="entry-missing-terminal",
        script="raise SystemExit(0)",
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["issue_code"] == "JOURNAL_RUNNER_INVALID"
    assert store.status(limit=1)[0].status.value == "STARTED"


@pytest.mark.parametrize(
    "public",
    [
        {
            "status": "PUBLISHED",
            "exit_code": 0,
            "report_file": "2026-08-11.published.decision-board.json",
            "storage_key": None,
            "degraded": True,
        },
        {
            "status": "BLOCKED",
            "exit_code": 0,
            "report_file": "2026-08-11.blocked.decision-board.json",
            "storage_key": "PRIVATE-SENTINEL",
            "degraded": False,
        },
        {
            "status": "FAILED",
            "exit_code": 2,
            "issue_code": "CONFIG_UNAVAILABLE",
            "report_file": "unexpected.json",
        },
        {
            "status": "FAILED",
            "exit_code": 2,
            "issue_code": "UPLOAD_FAILED",
        },
    ],
)
def test_shadow_wrapper_rejects_inconsistent_terminal_truth(
    public: dict[str, object], tmp_path: Path
) -> None:
    exit_code = public["exit_code"]
    result, store = _run_terminal_script(
        tmp_path,
        run_id=f"entry-inconsistent-{len(json.dumps(public))}",
        script=(
            f"import json; print(json.dumps({public!r})); raise SystemExit({exit_code})"
        ),
    )
    assert result.returncode == 2
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    assert json.loads(result.stderr)["issue_code"] == "JOURNAL_RUNNER_INVALID"
    assert store.status(limit=1)[0].status.value == "STARTED"


def test_shadow_wrapper_reserializes_one_valid_terminal_result(tmp_path: Path) -> None:
    public = {
        "status": "FAILED",
        "exit_code": 2,
        "issue_code": "CONFIG_UNAVAILABLE",
    }
    result, store = _run_terminal_script(
        tmp_path,
        run_id="entry-one-valid-terminal",
        script=f"import json,sys; print(json.dumps({public!r}, indent=2), file=sys.stderr); raise SystemExit(2)",
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == json.dumps(public, sort_keys=True) + "\n"
    assert store.status(limit=1)[0].status.value == "FAILED"


@pytest.mark.parametrize("upload_failed", [False, True])
def test_shadow_wrapper_binds_t7_report_identity_to_config(
    tmp_path: Path, upload_failed: bool
) -> None:
    basename = f"2026-08-11.decision-board.holding.other-run.{'a' * 64}.json"
    if upload_failed:
        public = {
            "status": "FAILED",
            "exit_code": 2,
            "issue_code": "UPLOAD_FAILED",
            "report_file": basename,
        }
    else:
        public = {
            "status": "PUBLISHED",
            "exit_code": 0,
            "report_file": basename,
            "storage_key": f"2026/08/{basename}",
            "degraded": False,
        }
    result, store = _run_terminal_script(
        tmp_path,
        run_id="wrapper-slot",
        script=(
            f"import json,sys; print(json.dumps({public!r})); "
            f"raise SystemExit({public['exit_code']})"
        ),
    )
    assert result.returncode == 2
    assert json.loads(result.stderr)["issue_code"] == "JOURNAL_RUNNER_INVALID"
    assert store.status(limit=1)[0].status.value == "STARTED"


def test_shadow_wrapper_claims_expired_slot_without_running_child(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "runner-called"
    journal_dir = tmp_path / "journal"
    result = subprocess.run(
        [
            str(WRAPPER),
            "--run-kind",
            "ENTRY",
            "--expected-at",
            "2020-01-01T00:00:00Z",
            "--run-id",
            "expired-slot",
            "--journal-dir",
            str(journal_dir),
            "--grace-seconds",
            "1",
            "--stale-seconds",
            "300",
            "--",
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).touch()",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not marker.exists()
    record = RunJournalStoreV0(journal_dir).status(limit=1)[0]
    assert record.status.value == "MISSED_EXPECTED"
    assert record.grace_seconds == 1
    assert record.stale_seconds == 300


def test_shadow_process_baseexception_propagates_and_started_remains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SyntheticInterrupt(BaseException):
        pass

    def interrupt_run(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise SyntheticInterrupt

    config = JournalShadowProcessConfigV0.from_strings(
        run_kind="ENTRY",
        expected_at=_current_slot_text(),
        run_id="entry-subprocess-interrupt",
        journal_dir=str(tmp_path),
        grace_seconds="60",
        stale_seconds="300",
        runner_args=[sys.executable, "-c", "raise SystemExit(0)"],
        dry_run=False,
    )
    monkeypatch.setattr(run_journal_cli.subprocess, "run", interrupt_run)

    with pytest.raises(SyntheticInterrupt):
        run_journal_cli.execute_journal_shadow_process_v0(config)

    assert RunJournalStoreV0(tmp_path).status(limit=1)[0].status.value == "STARTED"


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
