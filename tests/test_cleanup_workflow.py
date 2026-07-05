from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def _load_workflow(path: str) -> dict[Any, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Workflow payload must be mapping: {path}")
    return payload


def _workflow_triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    raw = workflow.get("on", workflow.get(True))
    if not isinstance(raw, dict):
        raise AssertionError("Workflow triggers must be a mapping")
    return raw


def _steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    steps = workflow["jobs"]["cleanup"]["steps"]
    if not isinstance(steps, list):
        raise AssertionError("cleanup steps must be a list")
    return steps


def _find_step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"Step not found: {name}")


def test_cleanup_workflow_sanitizes_manual_inputs_before_shell_use() -> None:
    workflow = _load_workflow(".github/workflows/cleanup.yml")
    triggers = _workflow_triggers(workflow)
    dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    bucket_input = dispatch_inputs["bucket"]

    assert bucket_input["type"] == "choice"
    assert bucket_input["options"] == ["reports"]

    params_step = _find_step_by_name(_steps(workflow), "Resolve cleanup inputs")
    params_script = str(params_step.get("run") or "")
    params_env = params_step.get("env") or {}

    assert "${{ github.event.inputs." not in params_script
    assert "${{ github.event_name }}" not in params_script
    assert params_env.get("EVENT_NAME") == "${{ github.event_name }}"
    assert params_env.get("RAW_DRY_RUN") == "${{ github.event.inputs.dry_run }}"
    assert (
        params_env.get("RAW_RETENTION_DAYS")
        == "${{ github.event.inputs.retention_days }}"
    )
    assert params_env.get("RAW_BUCKET") == "${{ github.event.inputs.bucket }}"
    assert "must be a single-line value" in params_script
    assert 'require_single_line "dry_run" "${dry_run}"' in params_script
    assert 'require_single_line "retention_days" "${retention_days}"' in params_script
    assert 'require_single_line "bucket" "${bucket}"' in params_script
    assert "Unsupported cleanup bucket" in params_script


def test_cleanup_workflow_accepts_service_role_key_fallback() -> None:
    workflow = _load_workflow(".github/workflows/cleanup.yml")
    env = workflow["jobs"]["cleanup"].get("env") or {}
    cleanup_step = _find_step_by_name(
        _steps(workflow), "Cleanup expired report objects"
    )
    run_script = str(cleanup_step.get("run") or "")

    assert env.get("SUPABASE_SECRET_KEY") == "${{ secrets.SUPABASE_SECRET_KEY }}"
    assert (
        env.get("SUPABASE_SERVICE_ROLE_KEY")
        == "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
    )
    assert 'os.environ.get("SUPABASE_SECRET_KEY")' in run_script
    assert 'os.environ.get("SUPABASE_SERVICE_ROLE_KEY")' in run_script
    assert "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY must be set" in run_script
