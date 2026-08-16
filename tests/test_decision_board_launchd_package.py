from __future__ import annotations

import copy
import inspect
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest
import sab.decision_board.launchd_package as launchd_package
from sab.decision_board.launchd_package import (
    ShadowLaunchdPackageError,
    build_decision_board_launchd_dry_run_package_v0,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision-board-shadow-gate.proposed.json"


def _assert_no_unexpected_cli_stderr(stderr: str) -> None:
    known_warning = (
        ": RuntimeWarning: The global interpreter lock (GIL) has been enabled to "
        "load module 'pandas._libs.pandas_parser', which has not declared that it "
        "can run safely without the GIL. To override this behavior and keep the GIL "
        "disabled (at your own risk), run with PYTHON_GIL=0 or -Xgil=0."
    )
    unexpected = "".join(
        line
        for line in stderr.splitlines(keepends=True)
        if not (
            line.rstrip("\r\n").startswith("<frozen importlib._bootstrap>:")
            and line.rstrip("\r\n").endswith(known_warning)
        )
    )
    assert unexpected == ""


def test_launchd_cli_stderr_allows_only_python_314t_pandas_gil_warning() -> None:
    warning = (
        "<frozen importlib._bootstrap>:491: RuntimeWarning: The global interpreter "
        "lock (GIL) has been enabled to load module 'pandas._libs.pandas_parser', "
        "which has not declared that it can run safely without the GIL. To override "
        "this behavior and keep the GIL disabled (at your own risk), run with "
        "PYTHON_GIL=0 or -Xgil=0.\n"
    )

    _assert_no_unexpected_cli_stderr(warning)


def test_launchd_cli_stderr_rejects_operational_errors() -> None:
    with pytest.raises(AssertionError, match="provider token leaked"):
        _assert_no_unexpected_cli_stderr("provider token leaked\n")


def test_launchd_cli_stderr_rejects_unexplained_blank_lines() -> None:
    with pytest.raises(AssertionError):
        _assert_no_unexpected_cli_stderr("\n")


def test_launchd_package_builds_disabled_unscheduled_entry_and_holding_plists(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "package"
    journal_dir = tmp_path / "journal"

    result = build_decision_board_launchd_dry_run_package_v0(
        manifest_path=MANIFEST,
        session="2026-08-17",
        repo_root=ROOT,
        journal_dir=journal_dir,
        output_dir=output_dir,
    )

    public = result.to_public_dict()
    assert public["status"] == "PACKAGE_READY"
    assert public["mode"] == "DRY_RUN_ONLY"
    assert public["approval_state"] == "PENDING"
    assert public["session"] == "2026-08-17"
    assert public["lanes"] == ["ENTRY", "HOLDING"]
    assert public["disabled"] is True
    assert public["scheduled"] is False
    assert public["runner_execution"] is False
    assert str(output_dir) not in json.dumps(public)

    plists = sorted(output_dir.glob("*.plist"))
    assert len(plists) == 2
    for path in plists:
        payload = plistlib.loads(path.read_bytes())
        assert payload["Disabled"] is True
        assert "StartCalendarInterval" not in payload
        assert "RunAtLoad" not in payload
        assert "KeepAlive" not in payload
        assert payload["WorkingDirectory"] == str(ROOT)
        args = payload["ProgramArguments"]
        assert args[0] == str(
            ROOT / "scripts" / "launchd" / "sab-decision-board-shadow-wrapper.sh"
        )
        assert "--dry-run" in args
        assert args.index("--dry-run") < args.index("--")
        runner = args[args.index("--") + 1 :]
        assert runner[:5] == ["uv", "run", "python", "-m", "sab"]
        assert "decision-board" in runner
        assert runner[runner.index("--upload-mode") + 1] == "disabled"


def test_generated_launchd_program_arguments_execute_only_wrapper_dry_run(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "package"
    journal_dir = tmp_path / "journal"
    report_dir = tmp_path / "reports"
    build_decision_board_launchd_dry_run_package_v0(
        manifest_path=MANIFEST,
        session="2026-08-17",
        repo_root=ROOT,
        journal_dir=journal_dir,
        output_dir=output_dir,
        report_dir=report_dir,
    )

    for path in sorted(output_dir.glob("*.plist")):
        payload = plistlib.loads(path.read_bytes())
        completed = subprocess.run(
            payload["ProgramArguments"],
            cwd=payload["WorkingDirectory"],
            env={"PATH": os.environ["PATH"], "UV_CACHE_DIR": str(ROOT / ".uv-cache")},
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert completed.returncode == 0
        _assert_no_unexpected_cli_stderr(completed.stderr)
        dry_run = json.loads(completed.stdout)
        assert dry_run["dry_run"] is True
        assert dry_run["runner_arg_count"] > 0

    assert not journal_dir.exists()
    assert not report_dir.exists()


def test_launchd_package_implementation_has_no_activation_or_live_capability() -> None:
    source = inspect.getsource(launchd_package).casefold()
    for forbidden in (
        "launchctl",
        "create_order",
        "modify_order",
        "cancel_order",
        "openai",
        "toss",
        "supabase",
    ):
        assert forbidden not in source


def test_launchd_package_cli_is_sanitized_and_refuses_existing_output(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "package"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts"
                / "launchd"
                / "build_decision_board_shadow_dry_run_package.py"
            ),
            "--session",
            "2026-08-17",
            "--journal-dir",
            str(tmp_path / "journal"),
            "--output-dir",
            str(output_dir),
            "--report-dir",
            str(tmp_path / "reports"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0
    _assert_no_unexpected_cli_stderr(completed.stderr)
    public = json.loads(completed.stdout)
    assert public["status"] == "PACKAGE_READY"
    assert str(tmp_path) not in completed.stdout

    with pytest.raises(ShadowLaunchdPackageError, match="output directory"):
        build_decision_board_launchd_dry_run_package_v0(
            manifest_path=MANIFEST,
            session="2026-08-17",
            repo_root=ROOT,
            journal_dir=tmp_path / "journal",
            output_dir=output_dir,
        )
    assert len(list(output_dir.glob("*.plist"))) == 2


def test_launchd_package_normalizes_valid_manifest_slot_order(tmp_path: Path) -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reordered = copy.deepcopy(raw)
    slots = reordered["expected_slots"]
    assert type(slots) is list
    slots[0], slots[1] = slots[1], slots[0]
    manifest = tmp_path / "reordered.json"
    manifest.write_text(json.dumps(reordered), encoding="utf-8")
    output_dir = tmp_path / "package"

    result = build_decision_board_launchd_dry_run_package_v0(
        manifest_path=manifest,
        session="2026-08-17",
        repo_root=ROOT,
        journal_dir=tmp_path / "journal",
        output_dir=output_dir,
    )

    assert [file.run_kind.value for file in result.files] == ["ENTRY", "HOLDING"]
    assert len(list(output_dir.glob("*.plist"))) == 2
