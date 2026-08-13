from __future__ import annotations

import json
from pathlib import Path

import yaml  # type: ignore[import-untyped]


def test_decision_board_playwright_is_pinned_fixture_only_and_runs_in_ci() -> None:
    package = json.loads(Path("web/package.json").read_text(encoding="utf-8"))
    config = Path("web/playwright.decision-board.config.ts").read_text(encoding="utf-8")
    fixture_server = Path("web/e2e/decision-board-fixture-server.mjs").read_text(
        encoding="utf-8"
    )
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["web"]["steps"]
    commands = "\n".join(str(step.get("run", "")) for step in steps)

    assert package["devDependencies"]["@playwright/test"] == "1.61.1"
    assert package["scripts"]["playwright:install"] == "playwright install chromium"
    assert "NEXT_TELEMETRY_DISABLED" in config
    assert "DECISION_BOARD_E2E_WEB_PORT" in config
    assert "DECISION_BOARD_E2E_FIXTURE_PORT" in config
    assert "127.0.0.1" in fixture_server
    assert "playwright:install" in commands
    assert "test:e2e:decision-board" in commands
    assert "secrets." not in commands
