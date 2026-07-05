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


def _script_index(script: str, needle: str) -> int:
    index = script.find(needle)
    assert index >= 0, f"Script fragment not found: {needle}"
    return index


def test_scan_workflow_does_not_load_holdings_from_supabase() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    assert not _has_step(steps, "Load holdings from Supabase")
    run_scan_step = _find_step_by_name(steps, "Run scan")
    env = run_scan_step.get("env") or {}
    assert "HOLDINGS_FILE" not in env


def test_scan_workflow_concurrency_matches_dispatch_lock_dimensions() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")

    group = str(workflow["concurrency"]["group"])
    assert "github.event.inputs.provider" in group
    assert "github.event.inputs.universe" in group


def test_sell_workflow_concurrency_matches_dispatch_lock_dimensions() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")

    group = str(workflow["concurrency"]["group"])
    assert "github.event.inputs.provider" in group


def test_cleanup_workflow_serializes_retention_deletes() -> None:
    workflow = _load_workflow(".github/workflows/cleanup.yml")

    concurrency = workflow.get("concurrency") or {}
    group = str(concurrency.get("group") or "")
    assert "github.workflow" in group
    assert "github.ref" not in group
    assert concurrency.get("cancel-in-progress") is False


def test_scan_workflow_ensures_watchlist_file_exists_before_run_scan() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    ensure_step = _find_step_by_name(steps, "Ensure watchlist file")
    run_script = str(ensure_step.get("run") or "")
    assert "watchlist.txt" in run_script
    assert ": > watchlist.txt" in run_script


def test_scan_workflow_allows_empty_scheduled_scan_only() -> None:
    workflow = _load_workflow(".github/workflows/scan.yml")
    steps = workflow["jobs"]["scan"]["steps"]

    run_scan_step = _find_step_by_name(steps, "Run scan")
    run_script = str(run_scan_step.get("run") or "")

    run_scan_index = _script_index(run_script, "uv run -m sab scan")
    scan_status_index = _script_index(run_script, "scan_status=${PIPESTATUS[0]}")
    report_lookup_index = _script_index(
        run_script,
        "report_path=\"$(sed -n 's/.*Buy report written to: //p' scan.log",
    )
    missing_report_check_index = _script_index(
        run_script,
        'if [[ -z "${report_path}" || ! -f "${report_path}" ]]; then',
    )
    empty_scan_default_index = _script_index(
        run_script,
        'allow_empty_scan="false"',
    )
    scheduled_guard_index = _script_index(
        run_script,
        'if [[ "${GITHUB_EVENT_NAME}" == "schedule" ]]; then',
    )
    no_tickers_match_index = _script_index(
        run_script,
        '"No tickers provided (watchlist empty or missing)"',
    )
    allow_empty_index = _script_index(run_script, 'allow_empty_scan="true"')
    failure_exit_index = _script_index(
        run_script,
        'if [[ "${scan_status}" -ne 0 && "${allow_empty_scan}" != "true" ]]; then',
    )
    output_index = _script_index(run_script, 'echo "report_path=${report_path}"')

    assert (
        run_scan_index
        < scan_status_index
        < report_lookup_index
        < missing_report_check_index
        < empty_scan_default_index
        < scheduled_guard_index
        < no_tickers_match_index
        < allow_empty_index
        < failure_exit_index
        < output_index
    )
    assert _script_index(run_script, 'exit "${scan_status}"') > failure_exit_index


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
    assert "entry_pattern" in run_script
    assert (
        "select=ticker,quantity,entry_price,entry_currency,entry_date,"
        "strategy,entry_pattern,notes,tags,stop_override,target_override" in run_script
    )
    assert '"entry_pattern",' in run_script
    assert 'key == "entry_pattern"' in run_script
    assert "Supabase holdings response omitted entry_pattern" in run_script
    assert (
        'echo "holdings_file=holdings.generated.yaml" >> "${GITHUB_OUTPUT}"'
        in run_script
    )

    run_sell_step = _find_step_by_name(steps, "Run sell")
    run_script = str(run_sell_step.get("run") or "")
    assert '--holdings "${{ steps.holdings.outputs.holdings_file }}"' in run_script


def test_sell_workflow_load_holdings_accepts_service_role_key_fallback() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]

    holdings_step = _find_step_by_name(steps, "Load holdings from Supabase")
    env = holdings_step.get("env") or {}
    run_script = str(holdings_step.get("run") or "")

    assert env.get("SUPABASE_SECRET_KEY") == "${{ secrets.SUPABASE_SECRET_KEY }}"
    assert (
        env.get("SUPABASE_SERVICE_ROLE_KEY")
        == "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
    )
    assert 'supabase_key="${SUPABASE_SECRET_KEY:-${SUPABASE_SERVICE_ROLE_KEY:-}}"' in (
        run_script
    )
    assert "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY must be set" in run_script


def test_ai_brief_workflow_manual_holdings_export_includes_entry_pattern() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = workflow["jobs"]["ai_brief"]["steps"]

    holdings_step = _find_step_by_name(steps, "Load holdings from Supabase")
    run_script = str(holdings_step.get("run") or "")

    assert "entry_pattern" in run_script
    assert (
        "select=ticker,quantity,entry_price,entry_currency,entry_date,"
        "strategy,entry_pattern,notes,tags,stop_override,target_override" in run_script
    )
    assert '"entry_pattern",' in run_script
    assert 'key == "entry_pattern"' in run_script
    assert "Supabase holdings response omitted entry_pattern" in run_script


def test_ai_brief_workflow_manual_holdings_export_accepts_service_role_key_fallback() -> (
    None
):
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = workflow["jobs"]["ai_brief"]["steps"]

    holdings_step = _find_step_by_name(steps, "Load holdings from Supabase")
    env = holdings_step.get("env") or {}
    run_script = str(holdings_step.get("run") or "")

    assert env.get("SUPABASE_SECRET_KEY") == "${{ secrets.SUPABASE_SECRET_KEY }}"
    assert (
        env.get("SUPABASE_SERVICE_ROLE_KEY")
        == "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
    )
    assert 'supabase_key="${SUPABASE_SECRET_KEY:-${SUPABASE_SERVICE_ROLE_KEY:-}}"' in (
        run_script
    )
    assert "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY must be set" in run_script
