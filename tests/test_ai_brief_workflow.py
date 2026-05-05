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
    steps = workflow["jobs"]["ai_brief"]["steps"]
    if not isinstance(steps, list):
        raise AssertionError("ai_brief steps must be a list")
    return steps


def _find_step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"Step not found: {name}")


def test_ai_brief_workflow_is_manual_only() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")

    triggers = _workflow_triggers(workflow)

    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers


def test_ai_brief_workflow_runs_scan_entry_then_ai_brief() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)
    step_names = [str(step.get("name") or "") for step in steps]

    run_scan_idx = step_names.index("Run scan")
    run_entry_idx = step_names.index("Run entry")
    run_ai_brief_idx = step_names.index("Run AI brief")

    assert run_scan_idx < run_entry_idx < run_ai_brief_idx
    assert "uv run -m sab scan" in str(steps[run_scan_idx].get("run") or "")
    assert "uv run -m sab entry" in str(steps[run_entry_idx].get("run") or "")
    assert "uv run -m sab ai-brief" in str(steps[run_ai_brief_idx].get("run") or "")
    assert "buy_report_path" in str(steps[run_scan_idx].get("run") or "")
    assert "entry_report_path" in str(steps[run_entry_idx].get("run") or "")
    assert "ai_brief_report_path" in str(steps[run_ai_brief_idx].get("run") or "")


def test_ai_brief_workflow_uploads_artifacts_without_delivery() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    upload_step = _find_step_by_name(steps, "Upload generated AI brief artifacts")
    upload_path = str((upload_step.get("with") or {}).get("path") or "")

    assert "steps.run_scan.outputs.buy_report_path" in upload_path
    assert "steps.run_entry.outputs.entry_report_path" in upload_path
    assert "steps.run_ai_brief.outputs.ai_brief_report_path" in upload_path
    assert not any("Send Telegram" in str(step.get("name") or "") for step in steps)
    assert not any("Send Slack" in str(step.get("name") or "") for step in steps)


def test_ai_brief_workflow_keeps_freeform_inputs_out_of_shell_templates() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    params_step = _find_step_by_name(steps, "Resolve workflow inputs")
    params_script = str(params_step.get("run") or "")
    params_env = params_step.get("env") or {}

    assert "${{ github.event.inputs.model_name }}" not in params_script
    assert "${{ github.event.inputs.source_report_path }}" not in params_script
    assert params_env.get("RAW_MODEL_NAME") == "${{ github.event.inputs.model_name }}"
    assert (
        params_env.get("RAW_SOURCE_REPORT_PATH")
        == "${{ github.event.inputs.source_report_path }}"
    )
    assert "model_name must be a single-line value" in params_script
    assert "model_timeout_seconds must be a single-line value" in params_script
    assert "source_report_path must be a single-line value" in params_script

    ai_brief_step = _find_step_by_name(steps, "Run AI brief")
    ai_brief_script = str(ai_brief_step.get("run") or "")
    ai_brief_env = ai_brief_step.get("env") or {}

    assert "${{ steps.params.outputs.model_name }}" not in ai_brief_script
    assert "${{ steps.params.outputs.source_report_path }}" not in ai_brief_script
    assert (
        ai_brief_env.get("PARAM_MODEL_NAME") == "${{ steps.params.outputs.model_name }}"
    )
    assert (
        ai_brief_env.get("PARAM_SOURCE_REPORT_PATH")
        == "${{ steps.params.outputs.source_report_path }}"
    )
