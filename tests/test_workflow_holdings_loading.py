from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def _load_workflow(path: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Workflow payload must be mapping: {path}")
    return payload


def _find_step_by_name(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"Step not found: {name}")


def _has_step(steps: list[dict[str, Any]], name: str) -> bool:
    return any(step.get("name") == name for step in steps)


def test_scan_workflow_does_not_load_holdings_from_supabase() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    assert not _has_step(steps, "Load holdings from Supabase")
    run_scan_step = _find_step_by_name(steps, "Run scan")
    env = run_scan_step.get("env") or {}
    assert "HOLDINGS_FILE" not in env


def test_scan_workflow_ensures_watchlist_file_exists_before_run_scan() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    ensure_step = _find_step_by_name(steps, "Ensure watchlist file")
    run_script = str(ensure_step.get("run") or "")
    assert "watchlist.txt" in run_script
    assert ": > watchlist.txt" in run_script


def test_scan_workflow_sends_telegram_message_chunks() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    telegram_step = _find_step_by_name(
        steps, "Send Telegram notification (schedule only)"
    )
    run_script = str(telegram_step.get("run") or "")

    assert "split_telegram_message_text" in run_script
    assert "sendMessage" in run_script
    assert "for message_text in" in run_script


def test_sell_workflow_loads_holdings_from_supabase_before_run_sell() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]

    holdings_step = _find_step_by_name(steps, "Load holdings from Supabase")
    run_script = str(holdings_step.get("run") or "")
    assert "holdings.generated.yaml" in run_script
    assert (
        'echo "holdings_file=holdings.generated.yaml" >> "${GITHUB_OUTPUT}"'
        in run_script
    )

    run_sell_step = _find_step_by_name(steps, "Run sell")
    run_script = str(run_sell_step.get("run") or "")
    assert '--holdings "${{ steps.holdings.outputs.holdings_file }}"' in run_script
