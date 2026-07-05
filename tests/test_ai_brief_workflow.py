from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from sab.scheduler.schedule_policy import github_schedule_crons


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


def _script_index(script: str, needle: str) -> int:
    index = script.find(needle)
    assert index >= 0, f"Script fragment not found: {needle}"
    return index


def _resolve_context_python_script(workflow: dict[Any, Any]) -> str:
    resolve_steps = _job_steps(workflow, "resolve_context")
    resolve_step = _find_step_by_name(resolve_steps, "Resolve schedule context")
    resolve_script = str(resolve_step.get("run") or "")
    marker = "python - <<'PY'\n"
    start = resolve_script.index(marker) + len(marker)
    end = resolve_script.rindex("\nPY")
    return resolve_script[start:end]


def _run_scheduled_resolve_context(
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    output_path = tmp_path / "github-output.txt"
    merged_env = {
        **os.environ,
        "EVENT_NAME": "schedule",
        "EVENT_SCHEDULE": "55 12 * * 1-5",
        "GITHUB_OUTPUT": output_path.as_posix(),
        "RAW_MARKET": "",
        "DEFAULT_SOURCE_PROVIDER_CHAIN": "",
        "DEFAULT_SOURCE_PROVIDER_CHAIN_US": "",
        "DEFAULT_SOURCE_PROVIDER": "",
        "DEFAULT_SOURCE_PROVIDER_US": "",
        "DEFAULT_SOURCE_API_URL": "",
        "DEFAULT_SOURCE_API_URL_US": "",
        **(env or {}),
    }
    subprocess.run(
        [sys.executable, "-c", _resolve_context_python_script(workflow)],
        check=True,
        cwd=Path(__file__).parents[1],
        env=merged_env,
    )
    outputs: dict[str, str] = {}
    for line in output_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        assert separator
        outputs[key] = value
    return outputs


def test_ai_brief_workflow_has_manual_and_scheduled_triggers() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")

    triggers = _workflow_triggers(workflow)
    dispatch_inputs = triggers["workflow_dispatch"]["inputs"]
    schedules = triggers["schedule"]
    schedule_crons = [item["cron"] for item in schedules]

    assert "workflow_dispatch" in triggers
    assert schedule_crons == list(github_schedule_crons())
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


def test_ai_brief_workflow_scheduled_runs_use_monitor_fallback_context() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    jobs = workflow["jobs"]

    assert workflow.get("concurrency") is None
    assert "resolve_context" in jobs
    assert "scheduled_ai_brief" in jobs
    assert jobs["ai_brief"].get("if") == "github.event_name != 'schedule'"

    resolve_steps = _job_steps(workflow, "resolve_context")
    resolve_step_names = [str(step.get("name") or "") for step in resolve_steps]
    assert resolve_step_names == ["Checkout", "Resolve schedule context"]
    assert resolve_step_names.index("Checkout") < resolve_step_names.index(
        "Resolve schedule context"
    )
    resolve_step = _find_step_by_name(resolve_steps, "Resolve schedule context")
    resolve_script = str(resolve_step.get("run") or "")
    resolve_env = resolve_step.get("env") or {}

    assert resolve_env.get("EVENT_NAME") == "${{ github.event_name }}"
    assert resolve_env.get("EVENT_SCHEDULE") == "${{ github.event.schedule }}"
    assert (
        resolve_env.get("DEFAULT_SOURCE_PROVIDER_CHAIN_US")
        == "${{ vars.AI_BRIEF_SOURCE_PROVIDER_CHAIN_US }}"
    )
    assert (
        resolve_env.get("DEFAULT_SOURCE_PROVIDER_CHAIN")
        == "${{ vars.AI_BRIEF_SOURCE_PROVIDER_CHAIN }}"
    )
    assert "from sab.scheduler.schedule_policy import" in resolve_script
    assert "dispatch_for_github_cron" in resolve_script
    assert "is_within_role_window" in resolve_script
    assert "market_zone" in resolve_script
    assert "schedule_map = {" not in resolve_script
    assert "role_windows = {" not in resolve_script
    assert "role_window_end_grace = {" not in resolve_script
    assert 'out.write(f"session_date={session_date}\\n")' in resolve_script
    assert 'out.write(f"schedule_role={schedule_role}\\n")' in resolve_script
    assert 'out.write(f"runner_role={runner_role}\\n")' in resolve_script
    assert "should_run = is_within_role_window(" in resolve_script
    assert 'out.write(f"should_run={str(should_run).lower()}\\n")' in resolve_script
    assert 'out.write("should_run=true\\n")' not in resolve_script
    assert 'out.write(f"source_provider_chain={source_provider_chain}\\n")' in (
        resolve_script
    )
    assert (
        'out.write(f"source_provider_chain_memberships={source_provider_chain_memberships}\\n")'
        in resolve_script
    )
    assert (
        'out.write(f"source_provider_chain_origin={source_provider_chain_origin}\\n")'
        in resolve_script
    )
    assert 'out.write(f"source_api_url={source_api_url}\\n")' in resolve_script
    assert (
        jobs["resolve_context"]["outputs"].get("source_provider_chain")
        == "${{ steps.context.outputs.source_provider_chain }}"
    )
    assert (
        jobs["resolve_context"]["outputs"].get("source_provider_chain_memberships")
        == "${{ steps.context.outputs.source_provider_chain_memberships }}"
    )
    assert (
        jobs["resolve_context"]["outputs"].get("source_provider_chain_origin")
        == "${{ steps.context.outputs.source_provider_chain_origin }}"
    )

    workflow_env = workflow.get("env") or {}
    assert "KIS_BASE_URL" not in workflow_env

    scheduled_job = jobs["scheduled_ai_brief"]
    scheduled_job_env = scheduled_job.get("env") or {}
    assert "KIS_BASE_URL" not in scheduled_job_env
    assert scheduled_job.get("needs") == "resolve_context"
    assert scheduled_job.get("if") == (
        "github.event_name == 'schedule' && "
        "needs.resolve_context.outputs.should_run == 'true'"
    )
    concurrency = scheduled_job.get("concurrency") or {}
    assert "needs.resolve_context.outputs.market" in str(concurrency.get("group"))
    assert "needs.resolve_context.outputs.session_date" in str(concurrency.get("group"))
    assert "needs.resolve_context.outputs.schedule_role" in str(
        concurrency.get("group")
    )
    assert concurrency.get("cancel-in-progress") is False

    scheduled_steps = _job_steps(workflow, "scheduled_ai_brief")
    run_step = _find_step_by_name(scheduled_steps, "Run scheduled AI Brief monitor")
    run_script = str(run_step.get("run") or "")
    run_env = run_step.get("env") or {}
    assert "uv run python -m sab ai-brief-scheduled" in run_script
    assert "--schedule-role" in run_script
    assert "--runner-role" in run_script
    assert "--attempt-id" in run_script
    assert run_env.get("SUPABASE_URL") == "${{ secrets.SUPABASE_URL }}"
    assert run_env.get("TELEGRAM_BOT_TOKEN") == "${{ secrets.TELEGRAM_BOT_TOKEN }}"
    assert run_env.get("KIS_APP_KEY") == "${{ secrets.KIS_APP_KEY }}"
    assert run_env.get("KIS_APP_SECRET") == "${{ secrets.KIS_APP_SECRET }}"
    assert "KIS_BASE_URL" not in run_env
    assert (
        run_env.get("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US")
        == "${{ needs.resolve_context.outputs.source_provider_chain_origin == 'env_market' "
        "&& needs.resolve_context.outputs.source_provider_chain || '' }}"
    )
    assert (
        run_env.get("AI_BRIEF_SOURCE_PROVIDER_CHAIN")
        == "${{ needs.resolve_context.outputs.source_provider_chain_origin == 'env_global' "
        "&& needs.resolve_context.outputs.source_provider_chain || '' }}"
    )
    assert run_env.get("AI_BRIEF_SOURCE_API_TOKEN") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'http-json' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',http-json,')) && "
        "secrets.AI_BRIEF_SOURCE_API_TOKEN || '' }}"
    )
    assert (
        run_env["OPENAI_AI_BRIEF_FALLBACK_MODEL"]
        == "${{ vars.OPENAI_AI_BRIEF_FALLBACK_MODEL }}"
    )
    assert (
        run_env["AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS"]
        == "${{ vars.AI_BRIEF_MODEL_FALLBACK_TIMEOUT_SECONDS }}"
    )
    assert (
        run_env["AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS"]
        == "${{ vars.AI_BRIEF_MODEL_TOTAL_TIMEOUT_SECONDS }}"
    )
    assert (
        run_env.get("AI_BRIEF_SOURCE_API_URL")
        == "${{ needs.resolve_context.outputs.source_api_url }}"
    )
    assert run_env.get("FINNHUB_API_KEY") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'finnhub' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',finnhub,')) && "
        "secrets.FINNHUB_API_KEY || '' }}"
    )
    assert run_env.get("POLYGON_API_KEY") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'polygon-news' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',polygon-news,')) && "
        "secrets.POLYGON_API_KEY || '' }}"
    )
    assert run_env.get("ALPHA_VANTAGE_API_KEY") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'alpha-vantage-news' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',alpha-vantage-news,')) && "
        "secrets.ALPHA_VANTAGE_API_KEY || '' }}"
    )
    assert run_env.get("MARKETAUX_API_TOKEN") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'marketaux-news' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',marketaux-news,')) && "
        "secrets.MARKETAUX_API_TOKEN || '' }}"
    )
    assert run_env.get("BENZINGA_API_TOKEN") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'benzinga-news' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',benzinga-news,')) && "
        "secrets.BENZINGA_API_TOKEN || '' }}"
    )
    assert run_env.get("NAVER_CLIENT_ID") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'naver-news' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',naver-news,')) && "
        "secrets.NAVER_CLIENT_ID || '' }}"
    )
    assert run_env.get("NAVER_CLIENT_SECRET") == (
        "${{ (needs.resolve_context.outputs.source_provider == 'naver-news' || "
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',naver-news,')) && "
        "secrets.NAVER_CLIENT_SECRET || '' }}"
    )


def test_ai_brief_workflow_scheduled_resolve_preserves_global_chain_origin(
    tmp_path: Path,
) -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    jobs = workflow["jobs"]

    outputs = _run_scheduled_resolve_context(
        tmp_path,
        env={"DEFAULT_SOURCE_PROVIDER_CHAIN": "finnhub,benzinga-news"},
    )

    assert outputs["source_provider_chain"] == "finnhub,benzinga-news"
    assert outputs["source_provider_chain_origin"] == "env_global"
    assert (
        jobs["resolve_context"]["outputs"].get("source_provider_chain_origin")
        == "${{ steps.context.outputs.source_provider_chain_origin }}"
    )

    run_env = (
        _find_step_by_name(
            _job_steps(workflow, "scheduled_ai_brief"),
            "Run scheduled AI Brief monitor",
        ).get("env")
        or {}
    )
    assert run_env.get("AI_BRIEF_SOURCE_PROVIDER_CHAIN") == (
        "${{ needs.resolve_context.outputs.source_provider_chain_origin == 'env_global' "
        "&& needs.resolve_context.outputs.source_provider_chain || '' }}"
    )
    assert run_env.get("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US") == (
        "${{ needs.resolve_context.outputs.source_provider_chain_origin == 'env_market' "
        "&& needs.resolve_context.outputs.source_provider_chain || '' }}"
    )


def test_ai_brief_workflow_scheduled_resolve_trims_chain_tokens_for_http_json(
    tmp_path: Path,
) -> None:
    outputs = _run_scheduled_resolve_context(
        tmp_path,
        env={
            "DEFAULT_SOURCE_PROVIDER_CHAIN_US": "finnhub, http-json",
            "DEFAULT_SOURCE_API_URL_US": "https://source.example/us",
        },
    )

    assert outputs["source_provider_chain"] == "finnhub, http-json"
    assert outputs["source_provider_chain_memberships"] == ",finnhub,http-json,"
    assert outputs["source_provider_chain_origin"] == "env_market"
    assert outputs["source_api_url"] == "https://source.example/us"


def test_ai_brief_workflow_scheduled_secret_chain_membership_is_exact(
    tmp_path: Path,
) -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    run_env = (
        _find_step_by_name(
            _job_steps(workflow, "scheduled_ai_brief"),
            "Run scheduled AI Brief monitor",
        ).get("env")
        or {}
    )

    invalid_outputs = _run_scheduled_resolve_context(
        tmp_path,
        env={"DEFAULT_SOURCE_PROVIDER_CHAIN_US": "not-finnhub"},
    )
    assert invalid_outputs["source_provider_chain"] == "not-finnhub"
    assert invalid_outputs["source_provider_chain_memberships"] == ",not-finnhub,"
    assert ",finnhub," not in invalid_outputs["source_provider_chain_memberships"]

    valid_outputs = _run_scheduled_resolve_context(
        tmp_path,
        env={"DEFAULT_SOURCE_PROVIDER_CHAIN_US": "finnhub,benzinga-news"},
    )
    assert valid_outputs["source_provider_chain_memberships"] == (
        ",finnhub,benzinga-news,"
    )
    assert ",finnhub," in valid_outputs["source_provider_chain_memberships"]
    assert ",benzinga-news," in valid_outputs["source_provider_chain_memberships"]
    assert (
        "contains(needs.resolve_context.outputs.source_provider_chain_memberships, ',finnhub,')"
        in str(run_env.get("FINNHUB_API_KEY") or "")
    )
    assert (
        "contains(needs.resolve_context.outputs.source_provider_chain, 'finnhub')"
        not in str(run_env.get("FINNHUB_API_KEY") or "")
    )


def test_ai_brief_workflow_scheduled_context_rejects_multiline_outputs() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    resolve_steps = _job_steps(workflow, "resolve_context")
    resolve_step = _find_step_by_name(resolve_steps, "Resolve schedule context")
    resolve_script = str(resolve_step.get("run") or "")

    assert "def _single_line_output_value" in resolve_script
    assert "must be a single-line value" in resolve_script
    assert (
        'source_provider = _single_line_output_value("source_provider", source_provider)'
        in resolve_script
    )
    assert (
        'source_provider_chain = _single_line_output_value("source_provider_chain", source_provider_chain)'
        in resolve_script
    )
    assert (
        'source_provider_chain_memberships = _single_line_output_value("source_provider_chain_memberships", source_provider_chain_memberships)'
        in resolve_script
    )
    assert (
        'source_provider_chain_origin = _single_line_output_value("source_provider_chain_origin", source_provider_chain_origin)'
        in resolve_script
    )
    assert (
        'source_api_url = _single_line_output_value("source_api_url", source_api_url)'
        in resolve_script
    )


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
    assert "--upload" not in ai_brief_script
    assert ai_brief_env.get("SAB_SUPPRESS_REPORT_UPLOADS") == "true"
    assert "SUPABASE_URL" not in ai_brief_env
    assert "SUPABASE_SECRET_KEY" not in ai_brief_env
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


def test_ai_brief_workflow_uploads_entry_artifact_after_fatal_entry() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)
    step_names = [str(step.get("name") or "") for step in steps]

    run_entry_step = _find_step_by_name(steps, "Run entry")
    run_entry_script = str(run_entry_step.get("run") or "")

    assert "set +e" in run_entry_script
    assert "entry_status=${PIPESTATUS[0]}" in run_entry_script
    assert "entry_reports_before=" in run_entry_script
    assert "ENTRY_REPORTS_BEFORE" in run_entry_script
    assert "from sab.config import load_config" in run_entry_script
    assert "entry_reports_before=\"$(uv run python - <<'PY'" in run_entry_script
    assert (
        'entry_report_path="$(ENTRY_REPORTS_BEFORE="${entry_reports_before}" '
        "uv run python - <<'PY'"
    ) in run_entry_script
    assert (
        "ENTRY_REPORT_PATH=\"${entry_report_path}\" uv run python - <<'PY'"
        in run_entry_script
    )
    assert "entry_reports_before=\"$(python - <<'PY'" not in run_entry_script
    assert (
        "ENTRY_REPORTS_BEFORE=\"${entry_reports_before}\" python - <<'PY'"
        not in run_entry_script
    )
    assert (
        "ENTRY_REPORT_PATH=\"${entry_report_path}\" python - <<'PY'"
        not in run_entry_script
    )
    assert "report_dir = Path(load_config().report_dir)" in run_entry_script
    assert "report_dir = PurePosixPath(Path(load_config().report_dir).as_posix())" in (
        run_entry_script
    )
    assert 'Path("reports").glob("*.entry.json")' not in run_entry_script
    assert "p.as_posix() not in before" in run_entry_script
    assert "ENTRY_REPORT_PATH=" in run_entry_script
    assert "path.parts[: len(report_dir.parts)] != report_dir.parts" in (
        run_entry_script
    )
    assert 'path.parts[0] != "reports"' not in run_entry_script
    assert (
        "entry_report_path must be a safe relative path ending with .entry.json"
        in run_entry_script
    )
    assert "entry_report_path must stay under reports/" not in run_entry_script
    assert 'out.write(f"entry_report_path={entry_report_path}\\n")' in run_entry_script
    assert (
        'echo "entry_report_path=${entry_report_path}" >> "${GITHUB_OUTPUT}"'
        not in run_entry_script
    )
    assert 'out.write(f"entry_status={entry_status}\\n")' in run_entry_script
    assert 'exit "${entry_status}"' in run_entry_script
    capture_status_index = _script_index(
        run_entry_script, "entry_status=${PIPESTATUS[0]}"
    )
    restore_errexit_index = run_entry_script.find("\nset -e\n", capture_status_index)
    assert restore_errexit_index >= 0
    status_output_index = _script_index(
        run_entry_script,
        'out.write(f"entry_status={entry_status}\\n")',
    )
    missing_report_check_index = _script_index(
        run_entry_script,
        'if [[ -z "${entry_report_path}" || ! -f "${entry_report_path}" ]]',
    )
    report_path_output_index = _script_index(
        run_entry_script,
        'out.write(f"entry_report_path={entry_report_path}\\n")',
    )
    assert (
        _script_index(run_entry_script, "entry_reports_before=")
        < _script_index(run_entry_script, "set +e")
        < _script_index(run_entry_script, "uv run -m sab entry")
        < capture_status_index
        < restore_errexit_index
        < status_output_index
        < missing_report_check_index
        < report_path_output_index
        < _script_index(run_entry_script, 'if [[ "${entry_status}" -ne 0 ]]')
        < _script_index(run_entry_script, 'exit "${entry_status}"')
    )

    upload_step = _find_step_by_name(steps, "Upload fatal entry artifact")
    assert step_names.index("Upload fatal entry artifact") == (
        step_names.index("Run entry") + 1
    )
    assert step_names.index("Upload fatal entry artifact") < step_names.index(
        "Run AI brief"
    )
    assert "failure()" in str(upload_step.get("if") or "")
    assert "steps.run_entry.outputs.entry_report_path != ''" in str(
        upload_step.get("if") or ""
    )
    assert (
        upload_step.get("uses")
        == "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
    )
    upload_with = upload_step.get("with") or {}
    assert upload_with.get("name") == (
        "ai-brief-entry-report-${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert upload_with.get("path") == "${{ steps.run_entry.outputs.entry_report_path }}"
    assert upload_with.get("if-no-files-found") == "error"


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
    telegram_script = str(telegram_step.get("run") or "")
    skipped_telegram_step = _find_step_by_name(
        steps,
        "Send skipped Telegram notification",
    )
    skipped_telegram_script = str(skipped_telegram_step.get("run") or "")

    assert "split_telegram_message_text" in telegram_script
    assert 'Path("ai-brief.telegram.txt").read_text' in telegram_script
    assert '"parse_mode": "HTML"' in telegram_script
    assert "for message_text in split_telegram_message_text(" in telegram_script
    assert '"text": message_text' in telegram_script
    assert "text@ai-brief.telegram.txt" not in telegram_script
    assert "parse_mode" not in skipped_telegram_script
    assert 'Path("ai-brief.skipped.telegram.txt").read_text' in (
        skipped_telegram_script
    )
    assert "urllib.request" in skipped_telegram_script
    assert "text@ai-brief.skipped.telegram.txt" not in skipped_telegram_script
    assert "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}" not in (
        skipped_telegram_script
    )
    assert "TELEGRAM_BOT_TOKEN" in str(skipped_telegram_step.get("env") or {})
    assert "SLACK_WEBHOOK_URL" in str(slack_step.get("env") or {})


def test_ai_brief_workflow_evaluates_quality_before_supabase_upload_and_delivery() -> (
    None
):
    workflow = _load_workflow(".github/workflows/ai-brief.yml")
    steps = _steps(workflow)
    step_names = [str(step.get("name") or "") for step in steps]

    eval_step = _find_step_by_name(steps, "Evaluate AI brief quality")
    eval_script = str(eval_step.get("run") or "")
    supabase_upload_step = _find_step_by_name(steps, "Upload AI brief to Supabase")
    supabase_upload_script = str(supabase_upload_step.get("run") or "")
    supabase_upload_env = supabase_upload_step.get("env") or {}

    assert step_names.index("Upload generated AI brief artifacts") < step_names.index(
        "Evaluate AI brief quality"
    )
    assert step_names.index("Evaluate AI brief quality") < step_names.index(
        "Upload AI brief to Supabase"
    )
    assert step_names.index("Upload AI brief to Supabase") < step_names.index(
        "Send Telegram notification"
    )
    assert step_names.index("Upload AI brief to Supabase") < step_names.index(
        "Send Slack notification"
    )
    assert "scripts/eval_ai_brief_recommendations.py" in eval_script
    assert '--entry-report "${{ steps.run_entry.outputs.entry_report_path }}"' in (
        eval_script
    )
    assert "--ai-brief-report" in eval_script
    assert "steps.run_ai_brief.outputs.ai_brief_report_path" in eval_script
    assert '--market "${{ steps.params.outputs.market }}"' in eval_script
    assert "--pretty" in eval_script
    assert "maybe_upload_report_artifact" in supabase_upload_script
    assert 'run_type="ai-brief"' in supabase_upload_script
    assert "force=True" in supabase_upload_script
    assert (
        supabase_upload_env.get("AI_BRIEF_REPORT_PATH")
        == "${{ steps.run_ai_brief.outputs.ai_brief_report_path }}"
    )
    assert supabase_upload_env.get("SUPABASE_URL") == "${{ secrets.SUPABASE_URL }}"
    assert (
        supabase_upload_env.get("SUPABASE_SECRET_KEY")
        == "${{ secrets.SUPABASE_SECRET_KEY }}"
    )
    assert (
        supabase_upload_env.get("SUPABASE_SERVICE_ROLE_KEY")
        == "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
    )


def test_ai_brief_workflow_top_level_concurrency_does_not_cancel_monitor_runs() -> None:
    workflow = _load_workflow(".github/workflows/ai-brief.yml")

    assert workflow.get("concurrency") is None


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
