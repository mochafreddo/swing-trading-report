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


def test_scheduled_sell_checks_runtime_state_before_holdings_and_provider_execution() -> (
    None
):
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]

    assert "${{ github.event_name }}" in workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] is True

    preflight_index = _step_index(steps, "Scheduled runtime_state preflight")
    install_index = _step_index(steps, "Install dependencies")
    holdings_index = _step_index(steps, "Load holdings from Supabase")
    run_sell_index = _step_index(steps, "Run sell")

    assert preflight_index < install_index < holdings_index < run_sell_index

    preflight = steps[preflight_index]
    assert preflight["if"] == "github.event_name == 'schedule'"
    assert "env" not in preflight
    assert "marker-aware local upload is implemented" in preflight["run"]
    assert "exit 1" in preflight["run"]


def test_scheduled_sell_telegram_sender_keeps_token_out_of_shell_argv() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]
    telegram = steps[_step_index(steps, "Send Telegram notification (schedule only)")]
    run = telegram["run"]

    assert "curl" not in run
    assert "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}" not in run
    assert "urllib.request.Request" in run
    assert 'os.environ["TELEGRAM_BOT_TOKEN"]' in run


def test_sell_workflow_dispatch_exposes_sell_ai_brief_inputs() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")
    dispatch_inputs = _workflow_triggers(workflow)["workflow_dispatch"]["inputs"]

    assert dispatch_inputs["sell_ai_brief_model_provider"]["default"] == "openai"
    assert dispatch_inputs["sell_ai_brief_model_name"]["default"] == ""
    assert dispatch_inputs["sell_ai_brief_source_provider"]["default"] == ""
    assert dispatch_inputs["sell_ai_brief_article_reader"]["default"] == "none"
    assert dispatch_inputs["send_sell_ai_brief_notifications"]["default"] == "false"


def test_sell_workflow_runs_sell_ai_brief_after_sell_and_before_delivery() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]

    run_sell_index = _step_index(steps, "Run sell")
    run_brief_index = _step_index(steps, "Run Sell AI Brief")
    eval_index = _step_index(steps, "Evaluate Sell AI Brief quality")
    artifact_index = _step_index(steps, "Upload generated Sell AI Brief artifact")
    upload_index = _step_index(steps, "Upload Sell AI Brief to Supabase")
    build_notification_index = _step_index(
        steps, "Build Sell AI Brief notification preview"
    )
    send_index = _step_index(steps, "Send Sell AI Brief Telegram notification")

    assert run_sell_index < run_brief_index < eval_index < artifact_index
    assert artifact_index < upload_index
    assert upload_index < build_notification_index < send_index

    run_step = steps[run_brief_index]
    run_script = str(run_step["run"])
    assert "uv run -m sab sell-ai-brief" in run_script
    assert '--sell-report "${{ steps.run_sell.outputs.report_path }}"' in run_script
    assert "SAB_SUPPRESS_REPORT_UPLOADS" in run_step["env"]
    assert "SELL_AI_BRIEF_SOURCE_PROVIDER_CHAIN_US" in run_step["env"]
    assert "AI_BRIEF_SOURCE_PROVIDER_CHAIN" in run_step["env"]
    source_secret_envs = [
        "AI_BRIEF_SOURCE_API_TOKEN",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "MARKETAUX_API_TOKEN",
        "BENZINGA_API_TOKEN",
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
    ]
    assert all(
        "contains(" not in str(run_step["env"][name]) for name in source_secret_envs
    )
    assert "disable_unused_source_provider_secrets" in run_script
    assert "provider_enabled http-json" in run_script

    eval_script = str(steps[eval_index]["run"])
    assert "scripts/eval_sell_ai_brief.py" in eval_script
    assert eval_index < upload_index


def test_sell_ai_brief_telegram_sender_uses_html_chunks_and_safe_token_handling() -> (
    None
):
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]
    telegram = steps[_step_index(steps, "Send Sell AI Brief Telegram notification")]
    run = str(telegram["run"])

    assert "curl" not in run
    assert "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}" not in run
    assert "split_telegram_message_text" in run
    assert '"parse_mode": "HTML"' in run
    assert 'os.environ["TELEGRAM_BOT_TOKEN"]' in run
