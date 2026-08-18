from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision-board-shadow-gate.proposed.json"


def _case_plan(*, two_lanes: bool = False) -> dict[str, object]:
    cases = [
        {
            "case_id": "case-entry-aapl",
            "run_kind": "ENTRY",
            "sealed_input_hash": "sha256:" + "3" * 64,
            "item_id": "entry-AAPL.NAS",
            "expected_action_set": ["REVIEW", "BUY"] if two_lanes else ["BUY"],
        }
    ]
    if two_lanes:
        cases.insert(
            0,
            {
                "case_id": "case-holding-msft",
                "run_kind": "HOLDING",
                "sealed_input_hash": "sha256:" + "4" * 64,
                "item_id": "holding-MSFT.NAS",
                "expected_action_set": ["SELL", "HOLD"],
            },
        )
    return {
        "schema_version": "decision-board-shadow-case-plan.v0",
        "gate_version": "us-swing-shadow-v1-20260824",
        "cases": cases,
    }


def _write_case_plan(
    path: Path,
    *,
    mode: int = 0o600,
    two_lanes: bool = False,
) -> Path:
    path.write_text(json.dumps(_case_plan(two_lanes=two_lanes)), encoding="utf-8")
    path.chmod(mode)
    return path


def _run_prepare(
    case_plan: str | Path,
    output_dir: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sab",
            "decision-board-shadow-ledger-prepare",
            "--manifest",
            str(MANIFEST),
            "--case-plan",
            str(case_plan),
            "--output-dir",
            str(output_dir),
        ],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], "UV_CACHE_DIR": str(ROOT / ".uv-cache")},
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )


def _assert_sanitized_failure(
    completed: subprocess.CompletedProcess[str],
    *,
    output_dir: Path,
) -> None:
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(completed.stderr) == {
        "exit_code": 2,
        "issue_code": "LEDGER_PREPARATION_INVALID",
        "status": "FAILED",
    }
    assert str(output_dir.parent) not in completed.stderr
    assert not output_dir.exists()


def test_local_cli_prepares_canonical_ledgers_without_approval_or_live_access(
    tmp_path: Path,
) -> None:
    case_plan = _write_case_plan(
        tmp_path / "case-plan.json",
        two_lanes=True,
    )
    output_dir = tmp_path / "ledgers"

    completed = _run_prepare(case_plan, output_dir)

    assert completed.returncode == 0
    assert completed.stderr == ""
    public = json.loads(completed.stdout)
    assert public == {
        "approval_signature_created": False,
        "case_count": 2,
        "files": [
            {
                "basename": "decision-board-shadow-input-ledger.json",
                "sha256": (
                    "sha256:a549f3618e4449a69c337966e7f7c5f748a13aebf75b98ac2ad1099b8fa7f900"
                ),
            },
            {
                "basename": "decision-board-shadow-expected-action-ledger.json",
                "sha256": (
                    "sha256:124037fbd47d480aed3d917fa83aefb24a3c2b9b943b0dba124ea568ad905bfa"
                ),
            },
        ],
        "gate_version": "us-swing-shadow-v1-20260824",
        "network_access": False,
        "scheduled": False,
        "status": "LEDGERS_READY",
    }
    assert str(tmp_path) not in completed.stdout
    assert "case-entry-aapl" not in completed.stdout
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "decision-board-shadow-expected-action-ledger.json",
        "decision-board-shadow-input-ledger.json",
    ]
    input_ledger = json.loads(
        (output_dir / "decision-board-shadow-input-ledger.json").read_text(
            encoding="utf-8"
        )
    )
    expected_ledger = json.loads(
        (output_dir / "decision-board-shadow-expected-action-ledger.json").read_text(
            encoding="utf-8"
        )
    )
    assert [case["case_id"] for case in input_ledger["cases"]] == [
        "case-entry-aapl",
        "case-holding-msft",
    ]
    assert expected_ledger["cases"] == [
        {
            "case_id": "case-entry-aapl",
            "expected_action_set": ["BUY", "REVIEW"],
        },
        {
            "case_id": "case-holding-msft",
            "expected_action_set": ["HOLD", "SELL"],
        },
    ]
    assert not any("approved" in path.name for path in output_dir.iterdir())
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output_dir.iterdir()
    )


def test_local_cli_rejects_symlinked_private_case_plan_without_writing(
    tmp_path: Path,
) -> None:
    private_plan = _write_case_plan(tmp_path / "private-plan.json")
    linked_plan = tmp_path / "linked-plan.json"
    linked_plan.symlink_to(private_plan)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(linked_plan, output_dir),
        output_dir=output_dir,
    )


def test_local_cli_rejects_group_readable_private_case_plan(
    tmp_path: Path,
) -> None:
    case_plan = _write_case_plan(
        tmp_path / "group-readable-plan.json",
        mode=0o640,
    )
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_plan, output_dir),
        output_dir=output_dir,
    )


def test_local_cli_rejects_relative_private_case_plan(tmp_path: Path) -> None:
    case_plan = _write_case_plan(tmp_path / "private-plan.json")
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(os.path.relpath(case_plan, ROOT), output_dir),
        output_dir=output_dir,
    )


def test_local_cli_rejects_group_accessible_output_parent(tmp_path: Path) -> None:
    case_plan = _write_case_plan(tmp_path / "private-plan.json")
    shared_parent = tmp_path / "shared"
    shared_parent.mkdir(mode=0o755)
    shared_parent.chmod(0o755)
    output_dir = shared_parent / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_plan, output_dir),
        output_dir=output_dir,
    )


def test_local_cli_sanitizes_unhashable_expected_action(tmp_path: Path) -> None:
    plan = _case_plan()
    cases = plan["cases"]
    assert type(cases) is list
    case = cases[0]
    assert type(case) is dict
    case["expected_action_set"] = [["BUY"]]
    case_plan = tmp_path / "malformed-plan.json"
    case_plan.write_text(json.dumps(plan), encoding="utf-8")
    case_plan.chmod(0o600)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_plan, output_dir),
        output_dir=output_dir,
    )
