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


def test_scheduled_sell_checks_runtime_state_before_holdings_and_provider_execution() -> (
    None
):
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]

    preflight_index = _step_index(steps, "Scheduled runtime_state preflight")
    install_index = _step_index(steps, "Install dependencies")
    holdings_index = _step_index(steps, "Load holdings from Supabase")
    run_sell_index = _step_index(steps, "Run sell")

    assert preflight_index < install_index < holdings_index < run_sell_index

    preflight = steps[preflight_index]
    assert preflight["if"] == "github.event_name == 'schedule'"
    assert preflight.get("env") == {
        "SUPABASE_URL": "${{ secrets.SUPABASE_URL }}",
    }


def test_scheduled_sell_telegram_sender_keeps_token_out_of_shell_argv() -> None:
    workflow = _load_workflow(".github/workflows/sell.yml")
    steps = workflow["jobs"]["sell"]["steps"]
    telegram = steps[_step_index(steps, "Send Telegram notification (schedule only)")]
    run = telegram["run"]

    assert "curl" not in run
    assert "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}" not in run
    assert "urllib.request.Request" in run
    assert 'os.environ["TELEGRAM_BOT_TOKEN"]' in run
