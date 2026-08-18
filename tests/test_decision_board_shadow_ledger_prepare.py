from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO, Self

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sab.decision_board.shadow_gate import load_shadow_gate_manifest_v0
from sab.decision_board.shadow_ledger_prepare import (
    ShadowLedgerPreparationError,
    load_shadow_evaluation_case_plan_v0,
    prepare_shadow_evaluation_ledgers_v0,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision-board-shadow-gate.proposed.json"
CASE_PLAN_SCHEMA = ROOT / "schemas" / "decision-board-shadow-case-plan.v0.schema.json"
_PYTHON_314T_PANDAS_GIL_WARNING = (
    ": RuntimeWarning: The global interpreter lock (GIL) has been enabled to "
    "load module 'pandas._libs.pandas_parser', which has not declared that it "
    "can run safely without the GIL. To override this behavior and keep the GIL "
    "disabled (at your own risk), run with PYTHON_GIL=0 or -Xgil=0."
)


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


def _first_case(plan: dict[str, object]) -> dict[str, object]:
    cases = plan["cases"]
    assert type(cases) is list
    case = cases[0]
    assert type(case) is dict
    return case


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


def _without_known_python_runtime_warning(stderr: str) -> str:
    return "".join(
        line
        for line in stderr.splitlines(keepends=True)
        if not (
            line.rstrip("\r\n").startswith("<frozen importlib._bootstrap>:")
            and line.rstrip("\r\n").endswith(_PYTHON_314T_PANDAS_GIL_WARNING)
        )
    )


def _assert_sanitized_failure(
    completed: subprocess.CompletedProcess[str],
    *,
    output_dir: Path,
) -> None:
    assert completed.returncode == 2
    assert completed.stdout == ""
    sanitized_stderr = _without_known_python_runtime_warning(completed.stderr)
    assert json.loads(sanitized_stderr) == {
        "exit_code": 2,
        "issue_code": "LEDGER_PREPARATION_INVALID",
        "status": "FAILED",
    }
    assert str(output_dir.parent) not in completed.stderr
    assert not output_dir.exists()


def test_cli_stderr_allows_only_python_314t_pandas_gil_warning() -> None:
    warning = (
        "<frozen importlib._bootstrap>:491: RuntimeWarning: The global interpreter "
        "lock (GIL) has been enabled to load module 'pandas._libs.pandas_parser', "
        "which has not declared that it can run safely without the GIL. To override "
        "this behavior and keep the GIL disabled (at your own risk), run with "
        "PYTHON_GIL=0 or -Xgil=0.\n"
    )

    assert _without_known_python_runtime_warning(warning) == ""
    assert _without_known_python_runtime_warning("unexpected failure\n") == (
        "unexpected failure\n"
    )


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
    assert _without_known_python_runtime_warning(completed.stderr) == ""
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
    _first_case(plan)["expected_action_set"] = [["BUY"]]
    case_plan = tmp_path / "malformed-plan.json"
    case_plan.write_text(json.dumps(plan), encoding="utf-8")
    case_plan.chmod(0o600)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_plan, output_dir),
        output_dir=output_dir,
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"{",
        b'{"value":NaN}',
        b'{"value":1,"value":2}',
    ],
)
def test_private_case_plan_loader_rejects_noncanonical_json(
    tmp_path: Path,
    payload: bytes,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(payload)
    path.chmod(0o600)

    with pytest.raises(ShadowLedgerPreparationError, match="unavailable or invalid"):
        load_shadow_evaluation_case_plan_v0(path)


def test_private_case_plan_loader_rejects_oversized_input(tmp_path: Path) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * 8_388_609)
    path.chmod(0o600)

    with pytest.raises(ShadowLedgerPreparationError, match="safe bound"):
        load_shadow_evaluation_case_plan_v0(path)


def test_case_plan_schema_accepts_the_documented_shape() -> None:
    schema = json.loads(CASE_PLAN_SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_case_plan(two_lanes=True))


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-root",
        "wrong-schema",
        "wrong-gate",
        "cases-not-list",
        "empty-cases",
        "extra-case-field",
        "invalid-case-id",
        "invalid-lane",
        "invalid-hash",
        "empty-actions",
        "unknown-action",
        "duplicate-action",
        "cross-lane-action",
        "duplicate-case-id",
        "duplicate-identity",
    ],
)
def test_local_preparation_rejects_invalid_case_plan_semantics(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan = _case_plan()
    case = _first_case(plan)
    cases = plan["cases"]
    assert type(cases) is list
    if mutation == "extra-root":
        plan["unexpected"] = True
    elif mutation == "wrong-schema":
        plan["schema_version"] = "decision-board-shadow-case-plan.v1"
    elif mutation == "wrong-gate":
        plan["gate_version"] = "different-gate"
    elif mutation == "cases-not-list":
        plan["cases"] = {}
    elif mutation == "empty-cases":
        cases.clear()
    elif mutation == "extra-case-field":
        case["unexpected"] = True
    elif mutation == "invalid-case-id":
        case["case_id"] = "not private"
    elif mutation == "invalid-lane":
        case["run_kind"] = "SELL"
    elif mutation == "invalid-hash":
        case["sealed_input_hash"] = "sha256:invalid"
    elif mutation == "empty-actions":
        case["expected_action_set"] = []
    elif mutation == "unknown-action":
        case["expected_action_set"] = ["STRONG_BUY"]
    elif mutation == "duplicate-action":
        case["expected_action_set"] = ["BUY", "BUY"]
    elif mutation == "cross-lane-action":
        case["expected_action_set"] = ["SELL"]
    elif mutation == "duplicate-case-id":
        duplicate = dict(case)
        duplicate["item_id"] = "entry-MSFT.NAS"
        duplicate["sealed_input_hash"] = "sha256:" + "4" * 64
        cases.append(duplicate)
    else:
        duplicate = dict(case)
        duplicate["case_id"] = "case-entry-duplicate"
        cases.append(duplicate)

    output_dir = tmp_path / "must-not-exist"
    with pytest.raises(ShadowLedgerPreparationError):
        prepare_shadow_evaluation_ledgers_v0(
            manifest=load_shadow_gate_manifest_v0(MANIFEST),
            case_plan=plan,
            output_dir=output_dir,
        )

    assert not output_dir.exists()


def test_local_preparation_requires_exact_pending_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "must-not-exist"
    with pytest.raises(TypeError, match="exact gate manifest"):
        prepare_shadow_evaluation_ledgers_v0(
            manifest=object(),  # type: ignore[arg-type]
            case_plan=_case_plan(),
            output_dir=output_dir,
        )

    manifest = load_shadow_gate_manifest_v0(MANIFEST)
    object.__setattr__(manifest, "approval_state", "APPROVED")
    with pytest.raises(ShadowLedgerPreparationError, match="requires a proposal"):
        prepare_shadow_evaluation_ledgers_v0(
            manifest=manifest,
            case_plan=_case_plan(),
            output_dir=output_dir,
        )

    assert not output_dir.exists()


@pytest.mark.parametrize("parent_kind", ["missing", "symlink"])
def test_local_cli_rejects_unavailable_output_parent(
    tmp_path: Path,
    parent_kind: str,
) -> None:
    case_plan = _write_case_plan(tmp_path / "private-plan.json")
    if parent_kind == "missing":
        parent = tmp_path / "missing"
    else:
        private_parent = tmp_path / "private-parent"
        private_parent.mkdir(mode=0o700)
        parent = tmp_path / "linked-parent"
        parent.symlink_to(private_parent, target_is_directory=True)
    output_dir = parent / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_plan, output_dir),
        output_dir=output_dir,
    )


def test_local_cli_refuses_to_overwrite_existing_output_directory(
    tmp_path: Path,
) -> None:
    case_plan = _write_case_plan(tmp_path / "private-plan.json")
    output_dir = tmp_path / "existing"
    output_dir.mkdir(mode=0o700)

    completed = _run_prepare(case_plan, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert json.loads(_without_known_python_runtime_warning(completed.stderr)) == {
        "exit_code": 2,
        "issue_code": "LEDGER_PREPARATION_INVALID",
        "status": "FAILED",
    }
    assert list(output_dir.iterdir()) == []


@pytest.mark.parametrize(
    "failing_basename",
    [
        "decision-board-shadow-input-ledger.json",
        "decision-board-shadow-expected-action-ledger.json",
    ],
)
def test_local_preparation_removes_partial_output_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_basename: str,
) -> None:
    class PartialWriteFailure:
        def __init__(self, stream: BinaryIO) -> None:
            self._stream = stream

        def __enter__(self) -> Self:
            self._stream.__enter__()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return self._stream.__exit__(exc_type, exc_value, traceback)

        def write(self, payload: bytes) -> int:
            self._stream.write(payload[:1])
            raise OSError("simulated partial write")

    output_dir = tmp_path / "must-be-removed"
    original_open = Path.open

    def fail_selected_ledger_write(path: Path, *args: Any, **kwargs: Any) -> Any:
        stream = original_open(path, *args, **kwargs)
        if path.parent == output_dir and path.name == failing_basename:
            return PartialWriteFailure(stream)
        return stream

    manifest = load_shadow_gate_manifest_v0(MANIFEST)
    monkeypatch.setattr(Path, "open", fail_selected_ledger_write)

    with pytest.raises(ShadowLedgerPreparationError, match="could not be written"):
        prepare_shadow_evaluation_ledgers_v0(
            manifest=manifest,
            case_plan=_case_plan(),
            output_dir=output_dir,
        )

    assert not output_dir.exists()
