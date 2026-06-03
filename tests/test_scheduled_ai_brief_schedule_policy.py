from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from sab.scheduler.schedule_policy import (
    dispatch_for_github_cron,
    github_schedule_crons,
    launchd_schedule_map,
    launchd_start_calendar_intervals,
    role_window,
    role_window_end_grace,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_workflow(path: str) -> dict[Any, Any]:
    payload = yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Workflow payload must be mapping: {path}")
    return payload


def _workflow_triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    raw = workflow.get("on", workflow.get(True))
    if not isinstance(raw, dict):
        raise AssertionError("Workflow triggers must be a mapping")
    return raw


def _job_steps(workflow: dict[Any, Any], job_name: str) -> list[dict[str, Any]]:
    steps = workflow["jobs"][job_name]["steps"]
    if not isinstance(steps, list):
        raise AssertionError(f"{job_name} steps must be a list")
    return steps


def _find_step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"Step not found: {name}")


def _arg_after(arguments: list[str], flag: str) -> str:
    try:
        return arguments[arguments.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise AssertionError(f"Missing launchd argument: {flag}") from exc


def test_workflow_scheduled_crons_match_shared_schedule_policy() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    schedules = _workflow_triggers(workflow)["schedule"]
    schedule_crons = tuple(item["cron"] for item in schedules)

    assert schedule_crons == github_schedule_crons()
    for cron in schedule_crons:
        dispatch = dispatch_for_github_cron(cron)
        assert dispatch.market == "US"
        assert dispatch.scheduled_tick in {"0830", "0855", "0929"}


def test_schedule_policy_imports_without_optional_runtime_dependencies() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            (
                "from sab.scheduler.schedule_policy import github_schedule_crons; "
                "print(github_schedule_crons())"
            ),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "55 12 * * 1-5" in result.stdout


def test_workflow_resolve_context_imports_shared_schedule_policy() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    resolve_steps = _job_steps(workflow, "resolve_context")
    resolve_step = _find_step_by_name(resolve_steps, "Resolve schedule context")
    resolve_script = str(resolve_step.get("run") or "")

    assert "from sab.scheduler.schedule_policy import" in resolve_script
    assert "dispatch_for_github_cron" in resolve_script
    assert "is_within_role_window" in resolve_script
    assert "schedule_map = {" not in resolve_script
    assert "role_windows = {" not in resolve_script
    assert "role_window_end_grace = {" not in resolve_script


def test_launchd_plists_match_shared_schedule_policy() -> None:
    for plist_path, dispatch in launchd_schedule_map().items():
        payload = plistlib.loads(Path(plist_path).read_bytes())
        arguments = payload["ProgramArguments"]
        intervals = payload["StartCalendarInterval"]
        if not isinstance(arguments, list):
            raise AssertionError(f"{plist_path} ProgramArguments must be a list")
        if not isinstance(intervals, list):
            raise AssertionError(f"{plist_path} StartCalendarInterval must be a list")

        assert _arg_after(arguments, "--market") == dispatch.market
        assert _arg_after(arguments, "--schedule-role") == dispatch.schedule_role
        assert _arg_after(arguments, "--runner-role") == dispatch.runner_role
        assert _arg_after(arguments, "--scheduled-tick") == dispatch.scheduled_tick

        actual = sorted(
            (
                {
                    "Weekday": int(item["Weekday"]),
                    "Hour": int(item["Hour"]),
                    "Minute": int(item["Minute"]),
                }
                for item in intervals
            ),
            key=lambda item: (item["Weekday"], item["Hour"], item["Minute"]),
        )
        expected = sorted(
            launchd_start_calendar_intervals(dispatch),
            key=lambda item: (item["Weekday"], item["Hour"], item["Minute"]),
        )
        assert actual == expected


def test_us_cutoff_alert_starts_at_fallback_grace_boundary() -> None:
    fallback = role_window("US", "github-fallback")
    cutoff = role_window("US", "cutoff-alert")

    assert fallback is not None
    assert cutoff is not None
    fallback_grace_minutes = int(
        role_window_end_grace("US", "github-fallback").total_seconds() // 60
    )

    assert fallback.end.hour == 9
    assert fallback.end.minute + fallback_grace_minutes == cutoff.start.minute
    assert cutoff.start.hour == 9
