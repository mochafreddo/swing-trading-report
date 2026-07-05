from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]


def _load_workflow(path: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Workflow payload must be mapping: {path}")
    return payload


def _step_index(steps: list[dict[str, Any]], name: str) -> int:
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index
    raise AssertionError(f"Step not found: {name}")


def _workflow_triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    raw_workflow = cast(dict[Any, Any], workflow)
    raw = raw_workflow.get("on", raw_workflow.get(True))
    if not isinstance(raw, dict):
        raise AssertionError("Workflow triggers must be a mapping")
    return raw


def test_scheduled_scan_checks_runtime_state_before_provider_execution() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    assert "${{ github.event_name }}" in workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] is True
    install_index = _step_index(steps, "Install dependencies")
    run_scan_index = _step_index(steps, "Run scan")

    assert "schedule" not in _workflow_triggers(workflow)
    assert install_index < run_scan_index
    assert all(
        step.get("name") != "Scheduled runtime_state preflight" for step in steps
    )
