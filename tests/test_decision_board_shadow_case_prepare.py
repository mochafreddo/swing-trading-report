from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any, BinaryIO, Self, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sab.decision_board.contracts import canonical_json_bytes, decision_payload_hash
from sab.decision_board.shadow_case_prepare import (
    ShadowCasePreparationError,
    load_shadow_evaluation_case_spec_v0,
    prepare_shadow_evaluation_cases_v0,
)
from sab.decision_board.shadow_gate import load_shadow_gate_manifest_v0

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "decision-board-shadow-gate.proposed.json"
CASE_SPEC_SCHEMA = ROOT / "schemas" / "decision-board-shadow-case-spec.v0.schema.json"
_PYTHON_314T_PANDAS_GIL_WARNING = (
    ": RuntimeWarning: The global interpreter lock (GIL) has been enabled to "
    "load module 'pandas._libs.pandas_parser', which has not declared that it "
    "can run safely without the GIL. To override this behavior and keep the GIL "
    "disabled (at your own risk), run with PYTHON_GIL=0 or -Xgil=0."
)


def _entry_snapshot() -> dict[str, object]:
    return {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "ENTRY",
        "metadata": {
            "policy_version": "decision-policy.v0",
            "registry_version": "ticker-directory.v0",
            "researcher_version": "live-research.v0",
            "verifier_version": "openai-claim.v0",
        },
        "items": [
            {
                "item_id": "entry-AAPL.NAS",
                "instrument": {
                    "market": "US",
                    "canonical_ticker": "AAPL.NAS",
                    "exchange": "NASDAQ",
                    "company_name": "Apple Inc.",
                    "identity_source": "ticker-directory",
                    "identity_version": "fixture-2026-08-19",
                },
                "item_state": "APPROVED",
                "identity_state": "APPROVED",
                "signal_state": "READY_ENTER",
                "mandate_state": "CURRENT",
                "price_state": "CURRENT",
                "exposure_state": "PASS",
            }
        ],
    }


def _case_spec() -> dict[str, object]:
    return {
        "schema_version": "decision-board-shadow-case-spec.v0",
        "gate_version": "us-swing-shadow-v1-20260824",
        "snapshots": [
            {
                "snapshot": _entry_snapshot(),
                "cases": [
                    {
                        "case_id": "case-entry-aapl",
                        "item_id": "entry-AAPL.NAS",
                        "expected_action_set": ["BUY", "REVIEW"],
                    }
                ],
            },
            {
                "snapshot": _holding_snapshot(),
                "cases": [
                    {
                        "case_id": "case-holding-msft",
                        "item_id": "holding-MSFT.NAS",
                        "expected_action_set": ["HOLD", "SELL"],
                    }
                ],
            },
        ],
    }


def _holding_snapshot() -> dict[str, object]:
    return {
        "schema": "sab.decision_board.sealed_request.v0",
        "run_kind": "HOLDING",
        "metadata": {
            "policy_version": "decision-policy.v0",
            "registry_version": "ticker-directory.v0",
            "researcher_version": "live-research.v0",
            "verifier_version": "openai-claim.v0",
        },
        "items": [
            {
                "item_id": "holding-MSFT.NAS",
                "instrument": {
                    "market": "US",
                    "canonical_ticker": "MSFT.NAS",
                    "exchange": "NASDAQ",
                    "company_name": "Microsoft Corp.",
                    "identity_source": "ticker-directory",
                    "identity_version": "fixture-2026-08-19",
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


def _run_prepare(case_spec: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sab",
            "decision-board-shadow-case-prepare",
            "--manifest",
            str(MANIFEST),
            "--case-spec",
            str(case_spec),
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


def _write_case_spec(path: Path, value: object, *, mode: int = 0o600) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(mode)
    return path


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
    completed: subprocess.CompletedProcess[str], *, output_dir: Path
) -> None:
    assert completed.returncode == 2
    assert completed.stdout == ""
    sanitized_stderr = _without_known_python_runtime_warning(completed.stderr)
    assert json.loads(sanitized_stderr) == {
        "exit_code": 2,
        "issue_code": "CASE_PREPARATION_INVALID",
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


def test_local_cli_prepares_canonical_snapshots_and_private_case_plan(
    tmp_path: Path,
) -> None:
    case_spec = _write_case_spec(tmp_path / "case-spec.json", _case_spec())
    output_dir = tmp_path / "prepared-cases"

    completed = _run_prepare(case_spec, output_dir)

    assert completed.returncode == 0, completed.stderr
    assert _without_known_python_runtime_warning(completed.stderr) == ""
    entry_snapshot = _entry_snapshot()
    holding_snapshot = _holding_snapshot()
    entry_hash = decision_payload_hash(entry_snapshot)
    holding_hash = decision_payload_hash(holding_snapshot)
    case_plan = {
        "schema_version": "decision-board-shadow-case-plan.v0",
        "gate_version": "us-swing-shadow-v1-20260824",
        "cases": [
            {
                "case_id": "case-entry-aapl",
                "run_kind": "ENTRY",
                "sealed_input_hash": entry_hash,
                "item_id": "entry-AAPL.NAS",
                "expected_action_set": ["BUY", "REVIEW"],
            },
            {
                "case_id": "case-holding-msft",
                "run_kind": "HOLDING",
                "sealed_input_hash": holding_hash,
                "item_id": "holding-MSFT.NAS",
                "expected_action_set": ["HOLD", "SELL"],
            },
        ],
    }
    case_plan_bytes = canonical_json_bytes(case_plan)
    assert json.loads(completed.stdout) == {
        "approval_signature_created": False,
        "case_count": 2,
        "files": [
            {
                "basename": "decision-board-shadow-case-plan.json",
                "sha256": f"sha256:{hashlib.sha256(case_plan_bytes).hexdigest()}",
            },
            *[
                {
                    "basename": f"snapshots/{sealed_hash.removeprefix('sha256:')}.json",
                    "sha256": sealed_hash,
                }
                for sealed_hash in sorted((entry_hash, holding_hash))
            ],
        ],
        "gate_version": "us-swing-shadow-v1-20260824",
        "network_access": False,
        "scheduled": False,
        "snapshot_count": 2,
        "status": "SHADOW_CASES_READY",
        "uploaded": False,
    }
    assert (output_dir / "decision-board-shadow-case-plan.json").read_bytes() == (
        case_plan_bytes
    )
    for snapshot, sealed_hash in (
        (entry_snapshot, entry_hash),
        (holding_snapshot, holding_hash),
    ):
        snapshot_basename = f"snapshots/{sealed_hash.removeprefix('sha256:')}.json"
        assert (output_dir / snapshot_basename).read_bytes() == canonical_json_bytes(
            snapshot
        )
    assert stat.S_IMODE(output_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((output_dir / "snapshots").stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in output_dir.rglob("*.json")
    )
    assert str(tmp_path) not in completed.stdout
    assert "case-entry-aapl" not in completed.stdout


def test_local_cli_rejects_unknown_snapshot_metadata_without_writing(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    metadata = snapshot["metadata"]
    assert type(metadata) is dict
    metadata["account_number"] = "PRIVATE-ACCOUNT-SENTINEL"
    case_spec = _write_case_spec(tmp_path / "private-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    completed = _run_prepare(case_spec, output_dir)

    _assert_sanitized_failure(completed, output_dir=output_dir)
    assert "PRIVATE-ACCOUNT-SENTINEL" not in completed.stderr


def test_local_cli_rejects_manifest_hash_inside_sealed_snapshot(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    metadata = snapshot["metadata"]
    assert type(metadata) is dict
    metadata["gate_manifest_sha256"] = "sha256:" + "a" * 64
    case_spec = _write_case_spec(tmp_path / "circular-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_spec, output_dir), output_dir=output_dir
    )


def test_local_cli_rejects_private_case_identifier_without_writing(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    cases = snapshot_spec["cases"]
    assert type(cases) is list
    case = cases[0]
    assert type(case) is dict
    case["case_id"] = "private case id"
    case_spec = _write_case_spec(tmp_path / "private-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_spec, output_dir), output_dir=output_dir
    )


def test_local_cli_rejects_duplicate_case_id_across_snapshots(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    duplicate = copy.deepcopy(snapshots[0])
    assert type(duplicate) is dict
    snapshot = duplicate["snapshot"]
    assert type(snapshot) is dict
    metadata = snapshot["metadata"]
    assert type(metadata) is dict
    metadata["policy_version"] = "decision-policy.v1"
    snapshots.append(duplicate)
    case_spec = _write_case_spec(tmp_path / "duplicate-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_spec, output_dir), output_dir=output_dir
    )


def test_local_cli_rejects_empty_snapshot_item_universe(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    snapshot["items"] = []
    case_spec = _write_case_spec(tmp_path / "empty-item-universe.json", value)
    output_dir = tmp_path / "must-not-exist"

    completed = _run_prepare(case_spec, output_dir)

    _assert_sanitized_failure(completed, output_dir=output_dir)


def test_local_cli_rejects_two_cases_for_one_snapshot_item(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    cases = snapshot_spec["cases"]
    assert type(cases) is list
    duplicate = copy.deepcopy(cases[0])
    assert type(duplicate) is dict
    duplicate["case_id"] = "case-entry-aapl-second"
    cases.append(duplicate)
    case_spec = _write_case_spec(tmp_path / "duplicate-item-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    completed = _run_prepare(case_spec, output_dir)

    _assert_sanitized_failure(completed, output_dir=output_dir)


def test_local_cli_rejects_entry_only_case_spec_when_both_lanes_are_required(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    value["snapshots"] = [snapshots[0]]
    schema = json.loads(CASE_SPEC_SCHEMA.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(value))
    case_spec = _write_case_spec(tmp_path / "entry-only-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    completed = _run_prepare(case_spec, output_dir)

    _assert_sanitized_failure(completed, output_dir=output_dir)


def test_local_cli_rejects_holding_only_case_spec_when_both_lanes_are_required(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    value["snapshots"] = [
        {
            "snapshot": _holding_snapshot(),
            "cases": [
                {
                    "case_id": "case-holding-msft",
                    "item_id": "holding-MSFT.NAS",
                    "expected_action_set": ["HOLD", "SELL"],
                }
            ],
        }
    ]
    schema = json.loads(CASE_SPEC_SCHEMA.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(value))
    case_spec = _write_case_spec(tmp_path / "holding-only-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    completed = _run_prepare(case_spec, output_dir)

    _assert_sanitized_failure(completed, output_dir=output_dir)


def test_local_cli_requires_every_snapshot_item_to_have_one_case(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    items = snapshot["items"]
    assert type(items) is list
    second = copy.deepcopy(items[0])
    assert type(second) is dict
    second["item_id"] = "entry-MSFT.NAS"
    instrument = second["instrument"]
    assert type(instrument) is dict
    instrument.update(
        {
            "canonical_ticker": "MSFT.NAS",
            "company_name": "Microsoft Corp.",
        }
    )
    items.append(second)
    case_spec = _write_case_spec(tmp_path / "uncovered-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_spec, output_dir), output_dir=output_dir
    )


def test_local_cli_prepares_two_lanes_and_sorts_case_plan_canonically(
    tmp_path: Path,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshots.reverse()
    holding_spec = snapshots[0]
    assert type(holding_spec) is dict
    holding_cases = holding_spec["cases"]
    assert type(holding_cases) is list
    holding_case = holding_cases[0]
    assert type(holding_case) is dict
    holding_case["expected_action_set"] = ["SELL", "HOLD"]
    case_spec = _write_case_spec(tmp_path / "case-spec.json", value)
    output_dir = tmp_path / "prepared-cases"

    completed = _run_prepare(case_spec, output_dir)

    assert completed.returncode == 0, completed.stderr
    public = json.loads(completed.stdout)
    assert public["snapshot_count"] == 2
    assert public["case_count"] == 2
    case_plan = json.loads(
        (output_dir / "decision-board-shadow-case-plan.json").read_text(
            encoding="utf-8"
        )
    )
    assert [case["case_id"] for case in case_plan["cases"]] == [
        "case-entry-aapl",
        "case-holding-msft",
    ]
    assert case_plan["cases"][1]["expected_action_set"] == ["HOLD", "SELL"]
    assert len(list((output_dir / "snapshots").glob("*.json"))) == 2


def test_case_spec_schema_accepts_the_documented_two_lane_shape() -> None:
    schema = json.loads(CASE_SPEC_SCHEMA.read_text(encoding="utf-8"))
    value = _case_spec()

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(value)


def test_case_spec_schema_matches_runtime_version_and_item_id_boundaries(
    tmp_path: Path,
) -> None:
    schema = json.loads(CASE_SPEC_SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    private_version = _case_spec()
    snapshots = private_version["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    metadata = snapshot["metadata"]
    assert type(metadata) is dict
    metadata["policy_version"] = "PRIVATE-v1"

    assert list(validator.iter_errors(private_version))
    private_path = _write_case_spec(
        tmp_path / "private-version-case-spec.json", private_version
    )
    _assert_sanitized_failure(
        _run_prepare(private_path, tmp_path / "must-not-exist"),
        output_dir=tmp_path / "must-not-exist",
    )

    max_ticker = "A" * 122
    max_item_id = f"entry-{max_ticker}"
    boundary_value = _case_spec()
    snapshots = boundary_value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    items = snapshot["items"]
    assert type(items) is list
    item = items[0]
    assert type(item) is dict
    item["item_id"] = max_item_id
    instrument = item["instrument"]
    assert type(instrument) is dict
    instrument["canonical_ticker"] = max_ticker
    cases = snapshot_spec["cases"]
    assert type(cases) is list
    case = cases[0]
    assert type(case) is dict
    case["item_id"] = max_item_id

    validator.validate(boundary_value)
    boundary_path = _write_case_spec(
        tmp_path / "boundary-case-spec.json", boundary_value
    )
    completed = _run_prepare(boundary_path, tmp_path / "boundary-output")
    assert completed.returncode == 0, completed.stderr

    public_identity = _case_spec()
    snapshots = public_identity["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    items = snapshot["items"]
    assert type(items) is list
    item = items[0]
    assert type(item) is dict
    instrument = item["instrument"]
    assert type(instrument) is dict
    instrument["identity_version"] = "version-Å"

    validator.validate(public_identity)
    public_identity_path = _write_case_spec(
        tmp_path / "public-identity-case-spec.json", public_identity
    )
    completed = _run_prepare(public_identity_path, tmp_path / "public-identity-output")
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "extra-root",
        "wrong-schema",
        "wrong-gate",
        "snapshots-not-list",
        "empty-snapshots",
        "extra-snapshot-field",
        "duplicate-snapshot",
        "private-snapshot-root",
        "private-item-field",
        "noncanonical-instrument",
        "metadata-not-object",
        "empty-cases",
        "extra-case-field",
        "missing-item",
        "duplicate-action",
        "unknown-action",
        "cross-lane-action",
    ],
)
def test_local_cli_rejects_invalid_case_spec_semantics(
    tmp_path: Path,
    mutation: str,
) -> None:
    value = _case_spec()
    snapshots = value["snapshots"]
    assert type(snapshots) is list
    snapshot_spec = snapshots[0]
    assert type(snapshot_spec) is dict
    snapshot = snapshot_spec["snapshot"]
    assert type(snapshot) is dict
    items = snapshot["items"]
    assert type(items) is list
    item = items[0]
    assert type(item) is dict
    cases = snapshot_spec["cases"]
    assert type(cases) is list
    case = cases[0]
    assert type(case) is dict

    if mutation == "extra-root":
        value["unexpected"] = True
    elif mutation == "wrong-schema":
        value["schema_version"] = "decision-board-shadow-case-spec.v1"
    elif mutation == "wrong-gate":
        value["gate_version"] = "different-gate"
    elif mutation == "snapshots-not-list":
        value["snapshots"] = {}
    elif mutation == "empty-snapshots":
        snapshots.clear()
    elif mutation == "extra-snapshot-field":
        snapshot_spec["unexpected"] = True
    elif mutation == "duplicate-snapshot":
        snapshots.append(copy.deepcopy(snapshot_spec))
    elif mutation == "private-snapshot-root":
        snapshot["account_id"] = "PRIVATE-ACCOUNT-SENTINEL"
    elif mutation == "private-item-field":
        item["quantity"] = "PRIVATE-ACCOUNT-SENTINEL"
    elif mutation == "noncanonical-instrument":
        instrument = item["instrument"]
        assert type(instrument) is dict
        instrument["canonical_ticker"] = "aapl.nas"
        instrument["exchange"] = "NAS"
    elif mutation == "metadata-not-object":
        snapshot["metadata"] = []
    elif mutation == "empty-cases":
        cases.clear()
    elif mutation == "extra-case-field":
        case["unexpected"] = True
    elif mutation == "missing-item":
        case["item_id"] = "entry-MSFT.NAS"
    elif mutation == "duplicate-action":
        case["expected_action_set"] = ["BUY", "BUY"]
    elif mutation == "unknown-action":
        case["expected_action_set"] = ["STRONG_BUY"]
    else:
        case["expected_action_set"] = ["SELL"]

    case_spec = _write_case_spec(tmp_path / "invalid-case-spec.json", value)
    output_dir = tmp_path / "must-not-exist"

    completed = _run_prepare(case_spec, output_dir)

    _assert_sanitized_failure(completed, output_dir=output_dir)
    assert "PRIVATE-ACCOUNT-SENTINEL" not in completed.stderr


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"{",
        b'{"value":NaN}',
        b'{"value":1,"value":2}',
    ],
)
def test_private_case_spec_loader_rejects_noncanonical_json(
    tmp_path: Path,
    payload: bytes,
) -> None:
    path = tmp_path / "invalid.json"
    path.write_bytes(payload)
    path.chmod(0o600)

    with pytest.raises(ShadowCasePreparationError, match="unavailable or invalid"):
        load_shadow_evaluation_case_spec_v0(path)


def test_private_case_spec_loader_rejects_oversized_input(tmp_path: Path) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * 8_388_609)
    path.chmod(0o600)

    with pytest.raises(ShadowCasePreparationError, match="safe bound"):
        load_shadow_evaluation_case_spec_v0(path)


def test_private_case_spec_loader_rejects_wrong_owner_fstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_case_spec(tmp_path / "wrong-owner.json", _case_spec())
    original_fstat = os.fstat

    def report_wrong_owner(descriptor: int) -> object:
        identity = original_fstat(descriptor)
        return SimpleNamespace(st_mode=identity.st_mode, st_uid=os.getuid() + 1)

    monkeypatch.setattr(os, "fstat", report_wrong_owner)

    with pytest.raises(ShadowCasePreparationError, match="unavailable or invalid"):
        load_shadow_evaluation_case_spec_v0(path)


@pytest.mark.parametrize("source_kind", ["symlink", "group-readable", "relative"])
def test_local_cli_rejects_unsafe_private_case_spec(
    tmp_path: Path,
    source_kind: str,
) -> None:
    private_spec = _write_case_spec(tmp_path / "private-spec.json", _case_spec())
    if source_kind == "symlink":
        source = tmp_path / "linked-spec.json"
        source.symlink_to(private_spec)
    elif source_kind == "group-readable":
        private_spec.chmod(0o640)
        source = private_spec
    else:
        source = Path(os.path.relpath(private_spec, ROOT))
    output_dir = tmp_path / "must-not-exist"

    _assert_sanitized_failure(_run_prepare(source, output_dir), output_dir=output_dir)


@pytest.mark.parametrize("parent_kind", ["group-accessible", "missing", "symlink"])
def test_local_cli_rejects_unsafe_output_parent(
    tmp_path: Path,
    parent_kind: str,
) -> None:
    case_spec = _write_case_spec(tmp_path / "case-spec.json", _case_spec())
    if parent_kind == "group-accessible":
        parent = tmp_path / "shared"
        parent.mkdir(mode=0o755)
        parent.chmod(0o755)
    elif parent_kind == "missing":
        parent = tmp_path / "missing"
    else:
        private_parent = tmp_path / "private-parent"
        private_parent.mkdir(mode=0o700)
        parent = tmp_path / "linked-parent"
        parent.symlink_to(private_parent, target_is_directory=True)
    output_dir = parent / "must-not-exist"

    _assert_sanitized_failure(
        _run_prepare(case_spec, output_dir), output_dir=output_dir
    )


def test_local_preparation_rejects_wrong_owner_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "wrong-owner-parent"
    parent.mkdir(mode=0o700)
    parent.chmod(0o700)
    output_dir = parent / "must-not-exist"
    manifest = load_shadow_gate_manifest_v0(MANIFEST)
    original_lstat = Path.lstat

    def report_wrong_owner(path: Path) -> object:
        identity = original_lstat(path)
        if path == parent:
            return SimpleNamespace(st_mode=identity.st_mode, st_uid=os.getuid() + 1)
        return identity

    monkeypatch.setattr(Path, "lstat", report_wrong_owner)

    with pytest.raises(ShadowCasePreparationError, match="output directory"):
        prepare_shadow_evaluation_cases_v0(
            manifest=manifest,
            case_spec=_case_spec(),
            output_dir=output_dir,
        )

    assert not output_dir.exists()


def test_local_cli_refuses_to_overwrite_existing_output_directory(
    tmp_path: Path,
) -> None:
    case_spec = _write_case_spec(tmp_path / "case-spec.json", _case_spec())
    output_dir = tmp_path / "existing"
    output_dir.mkdir(mode=0o700)

    completed = _run_prepare(case_spec, output_dir)

    assert completed.returncode == 2
    sanitized_stderr = _without_known_python_runtime_warning(completed.stderr)
    assert json.loads(sanitized_stderr) == {
        "exit_code": 2,
        "issue_code": "CASE_PREPARATION_INVALID",
        "status": "FAILED",
    }
    assert list(output_dir.iterdir()) == []


def test_private_output_files_are_never_created_group_or_world_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_modes: list[int] = []
    output_dir = tmp_path / "prepared-cases"
    manifest = load_shadow_gate_manifest_v0(MANIFEST)
    original_fdopen = os.fdopen

    class ObserveModeOnWrite:
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
            observed_modes.append(stat.S_IMODE(os.fstat(self._stream.fileno()).st_mode))
            return self._stream.write(payload)

    def observe_private_write(
        descriptor: int, *args: Any, **kwargs: Any
    ) -> ObserveModeOnWrite:
        return ObserveModeOnWrite(original_fdopen(descriptor, *args, **kwargs))

    monkeypatch.setattr(os, "fdopen", observe_private_write)
    previous_umask = os.umask(0o022)
    try:
        prepare_shadow_evaluation_cases_v0(
            manifest=manifest,
            case_spec=_case_spec(),
            output_dir=output_dir,
        )
    finally:
        os.umask(previous_umask)

    assert observed_modes
    assert all(mode & 0o077 == 0 for mode in observed_modes)


def test_local_preparation_requires_exact_pending_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "must-not-exist"
    with pytest.raises(TypeError, match="exact gate manifest"):
        prepare_shadow_evaluation_cases_v0(
            manifest=object(),  # type: ignore[arg-type]
            case_spec=_case_spec(),
            output_dir=output_dir,
        )

    manifest = load_shadow_gate_manifest_v0(MANIFEST)
    object.__setattr__(manifest, "approval_state", "APPROVED")
    with pytest.raises(ShadowCasePreparationError, match="requires a proposal"):
        prepare_shadow_evaluation_cases_v0(
            manifest=manifest,
            case_spec=_case_spec(),
            output_dir=output_dir,
        )

    assert not output_dir.exists()


@pytest.mark.parametrize("failing_kind", ["case-plan", "snapshot"])
def test_local_preparation_removes_partial_output_after_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_kind: str,
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
    manifest = load_shadow_gate_manifest_v0(MANIFEST)
    opened_paths: dict[int, Path] = {}
    original_os_open = os.open
    original_fdopen = os.fdopen

    def track_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is None:
            descriptor = original_os_open(path, flags, mode)
        else:
            descriptor = original_os_open(path, flags, mode, dir_fd=dir_fd)
        opened_paths[descriptor] = Path(os.fsdecode(path))
        return descriptor

    def fail_selected_write(
        descriptor: int, *args: Any, **kwargs: Any
    ) -> BinaryIO | PartialWriteFailure:
        stream = cast(BinaryIO, original_fdopen(descriptor, *args, **kwargs))
        path = opened_paths[descriptor]
        is_case_plan = path.name == "decision-board-shadow-case-plan.json"
        if path.is_relative_to(output_dir) and (
            (failing_kind == "case-plan" and is_case_plan)
            or (failing_kind == "snapshot" and not is_case_plan)
        ):
            return PartialWriteFailure(stream)
        return stream

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "fdopen", fail_selected_write)

    with pytest.raises(ShadowCasePreparationError, match="could not be written"):
        prepare_shadow_evaluation_cases_v0(
            manifest=manifest,
            case_spec=_case_spec(),
            output_dir=output_dir,
        )

    assert not output_dir.exists()


@pytest.mark.parametrize("failing_operation", ["mkdir", "chmod"])
def test_local_preparation_removes_output_after_snapshots_dir_setup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_operation: str,
) -> None:
    output_dir = tmp_path / "must-be-removed"
    snapshots_dir = output_dir / "snapshots"
    manifest = load_shadow_gate_manifest_v0(MANIFEST)

    if failing_operation == "mkdir":
        original_mkdir = Path.mkdir

        def fail_snapshots_mkdir(
            path: Path,
            mode: int = 0o777,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            if path == snapshots_dir:
                raise OSError("simulated snapshots mkdir failure")
            original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

        monkeypatch.setattr(Path, "mkdir", fail_snapshots_mkdir)
    else:
        original_chmod = Path.chmod

        def fail_snapshots_chmod(path: Path, mode: int) -> None:
            if path == snapshots_dir:
                raise OSError("simulated snapshots chmod failure")
            original_chmod(path, mode)

        monkeypatch.setattr(Path, "chmod", fail_snapshots_chmod)

    with pytest.raises(ShadowCasePreparationError, match="could not be written"):
        prepare_shadow_evaluation_cases_v0(
            manifest=manifest,
            case_spec=_case_spec(),
            output_dir=output_dir,
        )

    assert not output_dir.exists()
