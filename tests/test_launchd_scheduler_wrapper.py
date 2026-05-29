from __future__ import annotations

import plistlib
from pathlib import Path


def test_launchd_wrapper_guards_role_before_env_and_docker_preflight() -> None:
    wrapper = Path("scripts/launchd/sab-ai-brief-wrapper.sh")
    text = wrapper.read_text(encoding="utf-8")

    guard_index = text.index("--guard-only")
    docker_index = text.index("docker info")
    missing_env_index = text.index("scheduler env file is missing")

    assert guard_index < missing_env_index < docker_index
    assert "export PATH=" in text
    assert text.index("export PATH=") < text.index("uv run python")
    assert "source " not in text
    assert "load_host_alert_env" in text
    assert 'send_host_failure_alert "guard_failed"' in text
    assert "send_host_failure_alert" in text
    assert "TELEGRAM_BOT_TOKEN" in text
    assert "TELEGRAM_CHAT_ID" in text


def test_launchd_plist_templates_keep_one_schedule_role_per_job() -> None:
    template_dir = Path("scripts/launchd")
    templates = sorted(template_dir.glob("com.mochafreddo.sab.ai-brief.*.plist"))

    assert templates
    for template in templates:
        text = template.read_text(encoding="utf-8")
        payload = plistlib.loads(template.read_bytes())
        intervals = payload["StartCalendarInterval"]

        assert "sab-ai-brief-wrapper.sh" in text
        assert text.count("--schedule-role") == 1
        assert "com.mochafreddo.sab.ai-brief." in text
        assert intervals
        assert {item["Weekday"] for item in intervals} == {1, 2, 3, 4, 5}
        assert all("Hour" in item and "Minute" in item for item in intervals)


def test_scheduler_compose_has_one_shot_runner_service() -> None:
    compose = Path("docker-compose.scheduler.yml").read_text(encoding="utf-8")

    assert "scheduler:" in compose
    assert 'restart: "no"' in compose
    assert ".env.scheduler.local" in compose
    assert "uv run python -m sab ai-brief-scheduled" in compose


def test_launchd_verify_script_is_non_destructive() -> None:
    script = Path("scripts/launchd/verify-sab-ai-brief.sh")
    text = script.read_text(encoding="utf-8")

    assert "plutil -lint" in text
    assert "bash -n" in text
    assert "docker compose" in text
    assert "launchctl print" in text
    assert "launchctl bootstrap" not in text
    assert "launchctl bootout" not in text
