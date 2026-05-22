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


def test_ai_brief_workflow_has_manual_and_scheduled_triggers() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")

    triggers = _workflow_triggers(workflow)
    dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    schedules = triggers["schedule"]
    schedule_crons = [item["cron"] for item in schedules]

    assert "workflow_dispatch" in triggers
    assert schedule_crons == ["30 22 * * 0-4", "30 12 * * 1-5"]
    assert dispatch_inputs["send_notifications"]["default"] == "false"
    assert dispatch_inputs["send_notifications"]["options"] == ["false", "true"]
    assert dispatch_inputs["source_provider"]["options"] == [
        "none",
        "local-json",
        "http-json",
        "finnhub",
        "polygon-news",
        "alpha-vantage-news",
        "marketaux-news",
        "benzinga-news",
        "naver-news",
    ]
    assert "source_api_url" in dispatch_inputs
    assert "source_timeout_seconds" in dispatch_inputs


def test_ai_brief_workflow_scheduled_runs_have_defaults_and_runtime_guard() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    params_step = _find_step_by_name(steps, "Resolve workflow inputs")
    params_script = str(params_step.get("run") or "")
    params_env = params_step.get("env") or {}

    assert params_env.get("EVENT_NAME") == "${{ github.event_name }}"
    assert params_env.get("EVENT_SCHEDULE") == "${{ github.event.schedule }}"
    assert (
        params_env.get("DEFAULT_SOURCE_PROVIDER")
        == "${{ vars.AI_BRIEF_SOURCE_PROVIDER }}"
    )
    assert (
        params_env.get("DEFAULT_SOURCE_PROVIDER_KR")
        == "${{ vars.AI_BRIEF_SOURCE_PROVIDER_KR }}"
    )
    assert (
        params_env.get("DEFAULT_SOURCE_PROVIDER_US")
        == "${{ vars.AI_BRIEF_SOURCE_PROVIDER_US }}"
    )
    assert (
        params_env.get("DEFAULT_SOURCE_API_URL")
        == "${{ vars.AI_BRIEF_SOURCE_API_URL }}"
    )
    assert (
        params_env.get("DEFAULT_SOURCE_API_URL_KR")
        == "${{ vars.AI_BRIEF_SOURCE_API_URL_KR }}"
    )
    assert (
        params_env.get("DEFAULT_SOURCE_API_URL_US")
        == "${{ vars.AI_BRIEF_SOURCE_API_URL_US }}"
    )
    assert '"30 22 * * 0-4") scheduled_market="KR"' in params_script
    assert '"30 12 * * 1-5") scheduled_market="US"' in params_script
    assert 'model_provider="openai"' in params_script
    assert 'send_notifications="true"' in params_script
    assert (
        'market_default_source_provider="${DEFAULT_SOURCE_PROVIDER_KR,,}"'
        in params_script
    )
    assert (
        'market_default_source_provider="${DEFAULT_SOURCE_PROVIDER_US,,}"'
        in params_script
    )
    assert (
        'market_default_source_api_url="${DEFAULT_SOURCE_API_URL_KR}"' in params_script
    )
    assert (
        'market_default_source_api_url="${DEFAULT_SOURCE_API_URL_US}"' in params_script
    )
    assert 'source_provider="${market_default_source_provider}"' in params_script
    assert 'default_source_provider="${DEFAULT_SOURCE_PROVIDER,,}"' in params_script
    assert 'source_provider="${default_source_provider}"' in params_script
    assert 'source_api_url="${market_default_source_api_url}"' in params_script
    assert 'echo "is_schedule=${is_schedule}"' in params_script
    assert 'echo "scheduled_market=${scheduled_market}"' in params_script

    guard_step = _find_step_by_name(steps, "Check scheduled runtime guard")
    guard_script = str(guard_step.get("run") or "")

    assert guard_step.get("if") == "github.event_name == 'schedule'"
    assert "is_trading_session" in guard_script
    assert "resolve_run_session_state_map" in guard_script
    assert "Skipping scheduled AI brief" in guard_script
    assert 'out.write(f"trading_session={str(trading_session).lower()}\\n")' in (
        guard_script
    )

    guarded_steps = [
        "Install dependencies",
        "Ensure watchlist file",
        "Validate pykrx watchlist",
        "Run scan",
        "Load holdings from Supabase",
        "Run entry",
        "Run AI brief",
        "Build notification preview",
        "Upload generated AI brief artifacts",
        "Send Telegram notification",
        "Send Slack notification",
    ]
    expected_guard = "steps.schedule_guard.outputs.should_run == 'true'"
    for name in guarded_steps:
        step = _find_step_by_name(steps, name)
        assert expected_guard in str(step.get("if") or ""), name


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
    ai_brief_script = str(steps[run_ai_brief_idx].get("run") or "")
    ai_brief_env = steps[run_ai_brief_idx].get("env") or {}
    assert "uv run -m sab ai-brief" in ai_brief_script
    assert "--upload" in ai_brief_script
    assert ai_brief_env.get("SUPABASE_URL") == "${{ secrets.SUPABASE_URL }}"
    assert (
        ai_brief_env.get("SUPABASE_SECRET_KEY") == "${{ secrets.SUPABASE_SECRET_KEY }}"
    )
    assert "buy_report_path" in str(steps[run_scan_idx].get("run") or "")
    assert "entry_report_path" in str(steps[run_entry_idx].get("run") or "")
    assert "ai_brief_report_path" in ai_brief_script


def test_ai_brief_workflow_allows_empty_scheduled_scan_only() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    run_scan_step = _find_step_by_name(steps, "Run scan")
    run_scan_script = str(run_scan_step.get("run") or "")

    assert "scan_status=${PIPESTATUS[0]}" in run_scan_script
    assert 'allow_empty_scan="false"' in run_scan_script
    assert 'if [[ "${GITHUB_EVENT_NAME}" == "schedule" ]]; then' in run_scan_script
    assert '"No tickers provided (watchlist empty or missing)"' in run_scan_script
    assert 'allow_empty_scan="true"' in run_scan_script
    assert (
        'if [[ "${scan_status}" -ne 0 && "${allow_empty_scan}" != "true" ]]; then'
        in run_scan_script
    )
    assert 'exit "${scan_status}"' in run_scan_script


def test_ai_brief_workflow_uploads_artifacts_and_delivery_is_opt_in() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    upload_step = _find_step_by_name(steps, "Upload generated AI brief artifacts")
    upload_path = str((upload_step.get("with") or {}).get("path") or "")

    assert "steps.run_scan.outputs.buy_report_path" in upload_path
    assert "steps.run_entry.outputs.entry_report_path" in upload_path
    assert "steps.run_ai_brief.outputs.ai_brief_report_path" in upload_path
    assert "ai-brief.slack.txt" in upload_path
    assert "ai-brief.telegram.txt" in upload_path

    telegram_step = _find_step_by_name(steps, "Send Telegram notification")
    slack_step = _find_step_by_name(steps, "Send Slack notification")
    expected_condition = "steps.params.outputs.send_notifications == 'true'"
    expected_guard = "steps.schedule_guard.outputs.should_run == 'true'"

    assert expected_condition in str(telegram_step.get("if") or "")
    assert expected_condition in str(slack_step.get("if") or "")
    assert expected_guard in str(telegram_step.get("if") or "")
    assert expected_guard in str(slack_step.get("if") or "")
    assert telegram_step.get("continue-on-error") is True
    assert slack_step.get("continue-on-error") is True
    assert "TELEGRAM_BOT_TOKEN" in str(telegram_step.get("env") or {})
    assert "SLACK_WEBHOOK_URL" in str(slack_step.get("env") or {})


def test_ai_brief_workflow_sends_skipped_message_when_schedule_guard_blocks() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    build_step = _find_step_by_name(steps, "Build skipped scheduled notification")
    send_step = _find_step_by_name(steps, "Send skipped Telegram notification")
    build_if = str(build_step.get("if") or "")
    send_if = str(send_step.get("if") or "")
    build_script = str(build_step.get("run") or "")
    build_env = build_step.get("env") or {}
    send_env = send_step.get("env") or {}

    assert "github.event_name == 'schedule'" in build_if
    assert "steps.schedule_guard.outputs.should_run != 'true'" in build_if
    assert "github.event_name == 'schedule'" in send_if
    assert "steps.schedule_guard.outputs.should_run != 'true'" in send_if
    assert "steps.params.outputs.send_notifications == 'true'" in send_if
    assert "build_ai_brief_skipped_telegram_text" in build_script
    assert "ai-brief.skipped.telegram.txt" in build_script
    assert "GITHUB_STEP_SUMMARY" in build_script
    assert build_env.get("SESSION_STATE") == (
        "${{ steps.schedule_guard.outputs.session_state }}"
    )
    assert build_env.get("SESSION_DATE") == (
        "${{ steps.schedule_guard.outputs.session_date }}"
    )
    assert build_env.get("TRADING_SESSION") == (
        "${{ steps.schedule_guard.outputs.trading_session }}"
    )
    assert send_step.get("continue-on-error") is True
    assert "TELEGRAM_BOT_TOKEN" in str(send_env)


def test_ai_brief_workflow_keeps_freeform_inputs_out_of_shell_templates() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)

    params_step = _find_step_by_name(steps, "Resolve workflow inputs")
    params_script = str(params_step.get("run") or "")
    params_env = params_step.get("env") or {}

    assert "${{ github.event.inputs.model_name }}" not in params_script
    assert "${{ github.event.inputs.source_report_path }}" not in params_script
    assert params_env.get("EVENT_SCHEDULE") == "${{ github.event.schedule }}"
    assert params_env.get("RAW_MODEL_NAME") == "${{ github.event.inputs.model_name }}"
    assert (
        params_env.get("RAW_SOURCE_REPORT_PATH")
        == "${{ github.event.inputs.source_report_path }}"
    )
    assert (
        params_env.get("RAW_SOURCE_API_URL")
        == "${{ github.event.inputs.source_api_url }}"
    )
    assert (
        params_env.get("RAW_SEND_NOTIFICATIONS")
        == "${{ github.event.inputs.send_notifications }}"
    )
    assert "model_name must be a single-line value" in params_script
    assert "model_timeout_seconds must be a single-line value" in params_script
    assert "source_report_path must be a single-line value" in params_script
    assert "source_api_url must be a single-line value" in params_script
    assert "source_timeout_seconds must be a single-line value" in params_script
    assert "source_provider=http-json requires source_api_url" in params_script
    assert (
        "none|local-json|http-json|finnhub|polygon-news|alpha-vantage-news|marketaux-news|benzinga-news|naver-news"
    ) in params_script
    assert "Unsupported send_notifications" in params_script

    ai_brief_step = _find_step_by_name(steps, "Run AI brief")
    ai_brief_script = str(ai_brief_step.get("run") or "")
    ai_brief_env = ai_brief_step.get("env") or {}

    assert "${{ steps.params.outputs.model_name }}" not in ai_brief_script
    assert "${{ steps.params.outputs.source_report_path }}" not in ai_brief_script
    assert "${{ steps.params.outputs.source_api_url }}" not in ai_brief_script
    assert (
        ai_brief_env.get("PARAM_MODEL_NAME") == "${{ steps.params.outputs.model_name }}"
    )
    assert (
        ai_brief_env.get("PARAM_SOURCE_REPORT_PATH")
        == "${{ steps.params.outputs.source_report_path }}"
    )
    assert (
        ai_brief_env.get("PARAM_SOURCE_API_URL")
        == "${{ steps.params.outputs.source_api_url }}"
    )
    assert ai_brief_env.get("AI_BRIEF_SOURCE_API_TOKEN") == (
        "${{ steps.params.outputs.source_provider == 'http-json' && "
        "secrets.AI_BRIEF_SOURCE_API_TOKEN || '' }}"
    )
    assert (
        ai_brief_env.get("AI_BRIEF_SOURCE_API_URL_KR")
        == "${{ vars.AI_BRIEF_SOURCE_API_URL_KR }}"
    )
    assert (
        ai_brief_env.get("AI_BRIEF_SOURCE_API_URL_US")
        == "${{ vars.AI_BRIEF_SOURCE_API_URL_US }}"
    )
    assert ai_brief_env.get("FINNHUB_API_KEY") == (
        "${{ steps.params.outputs.source_provider == 'finnhub' && "
        "secrets.FINNHUB_API_KEY || '' }}"
    )
    assert ai_brief_env.get("POLYGON_API_KEY") == (
        "${{ steps.params.outputs.source_provider == 'polygon-news' && "
        "secrets.POLYGON_API_KEY || '' }}"
    )
    assert ai_brief_env.get("ALPHA_VANTAGE_API_KEY") == (
        "${{ steps.params.outputs.source_provider == 'alpha-vantage-news' && "
        "secrets.ALPHA_VANTAGE_API_KEY || '' }}"
    )
    assert ai_brief_env.get("MARKETAUX_API_TOKEN") == (
        "${{ steps.params.outputs.source_provider == 'marketaux-news' && "
        "secrets.MARKETAUX_API_TOKEN || '' }}"
    )
    assert ai_brief_env.get("BENZINGA_API_TOKEN") == (
        "${{ steps.params.outputs.source_provider == 'benzinga-news' && "
        "secrets.BENZINGA_API_TOKEN || '' }}"
    )
    assert ai_brief_env.get("NAVER_CLIENT_ID") == (
        "${{ steps.params.outputs.source_provider == 'naver-news' && "
        "secrets.NAVER_CLIENT_ID || '' }}"
    )
    assert ai_brief_env.get("NAVER_CLIENT_SECRET") == (
        "${{ steps.params.outputs.source_provider == 'naver-news' && "
        "secrets.NAVER_CLIENT_SECRET || '' }}"
    )
    assert "--source-api-url" in ai_brief_script
    assert "--source-timeout-seconds" in ai_brief_script
    expected_timeout_provider_condition = (
        '[[ "${PARAM_SOURCE_PROVIDER}" == "http-json" || '
        '"${PARAM_SOURCE_PROVIDER}" == "finnhub" || '
        '"${PARAM_SOURCE_PROVIDER}" == "polygon-news" || '
        '"${PARAM_SOURCE_PROVIDER}" == "alpha-vantage-news" || '
        '"${PARAM_SOURCE_PROVIDER}" == "marketaux-news" || '
        '"${PARAM_SOURCE_PROVIDER}" == "benzinga-news" || '
        '"${PARAM_SOURCE_PROVIDER}" == "naver-news" ]]'
    )
    assert expected_timeout_provider_condition in ai_brief_script
    assert 'source_api_token=""' in ai_brief_script
    assert (
        '[[ -n "${AI_BRIEF_SOURCE_API_URL}" && "${PARAM_SOURCE_API_URL}" == "${AI_BRIEF_SOURCE_API_URL}" ]]'
        in ai_brief_script
    )
    assert (
        '[[ -n "${AI_BRIEF_SOURCE_API_URL_KR}" && "${PARAM_SOURCE_API_URL}" == "${AI_BRIEF_SOURCE_API_URL_KR}" ]]'
        in ai_brief_script
    )
    assert (
        '[[ -n "${AI_BRIEF_SOURCE_API_URL_US}" && "${PARAM_SOURCE_API_URL}" == "${AI_BRIEF_SOURCE_API_URL_US}" ]]'
        in ai_brief_script
    )
    assert 'source_api_token="${AI_BRIEF_SOURCE_API_TOKEN:-}"' in ai_brief_script
    assert (
        'AI_BRIEF_SOURCE_API_TOKEN="${source_api_token}" "${cmd[@]}"' in ai_brief_script
    )
