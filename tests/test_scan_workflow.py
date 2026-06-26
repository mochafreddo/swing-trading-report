from __future__ import annotations

from pathlib import Path
from typing import Any

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


def test_scheduled_scan_checks_runtime_state_before_provider_execution() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    preflight_index = _step_index(steps, "Scheduled runtime_state preflight")
    install_index = _step_index(steps, "Install dependencies")
    run_scan_index = _step_index(steps, "Run scan")

    assert preflight_index < install_index < run_scan_index
