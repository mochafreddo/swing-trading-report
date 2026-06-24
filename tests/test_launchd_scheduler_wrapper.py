from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run_wrapper_with_stubs(
    tmp_path: Path,
    *,
    docker_script: str,
    tee_script: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    alerts_path = tmp_path / "alerts.log"
    env_file = tmp_path / ".env.scheduler.local"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_CHAT_ID=test-chat\n",
        encoding="utf-8",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"--guard-only"* ]]; then exit 0; fi\n'
        "exit 1\n",
    )
    _write_executable(bin_dir / "docker", docker_script)
    if tee_script is not None:
        _write_executable(bin_dir / "tee", tee_script)
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(alerts_path.as_posix())}\n"
        "exit 0\n",
    )
    wrapper_src = REPO_ROOT / "scripts/launchd/sab-ai-brief-wrapper.sh"
    wrapper_copy = tmp_path / "sab-ai-brief-wrapper.sh"
    wrapper_copy.write_text(
        wrapper_src.read_text(encoding="utf-8").replace(
            'export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/share/mise/shims:${HOME}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"',
            f'export PATH="{bin_dir}:/opt/homebrew/bin:/usr/local/bin:${{HOME}}/.local/share/mise/shims:${{HOME}}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"',
        ),
        encoding="utf-8",
    )
    wrapper_copy.chmod(0o755)
    env = {
        **os.environ,
    }
    result = subprocess.run(
        [
            str(wrapper_copy),
            "--repo-root",
            str(tmp_path),
            "--env-file",
            str(env_file),
            "--market",
            "US",
            "--schedule-role",
            "local-primary",
            "--runner-role",
            "local-primary",
            "--scheduled-tick",
            "0810",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, alerts_path


def _run_plist_timing_check(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "scripts/launchd/verify_ai_brief_plist_timing.py",
            "--repo-root",
            str(repo_root),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


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


def test_launchd_wrapper_suppresses_host_failure_for_structured_pipeline_failed(
    tmp_path: Path,
) -> None:
    result, alerts_path = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "info" ]]; then exit 0; fi\n'
            'printf \'%s\\n\' \'{"status": "pipeline_failed", "storage_key": null}\'\n'
            "exit 1\n"
        ),
    )

    assert result.returncode == 1
    assert '{"status": "pipeline_failed", "storage_key": null}' in result.stdout
    assert not alerts_path.exists()


def test_launchd_wrapper_sends_host_failure_without_structured_status(
    tmp_path: Path,
) -> None:
    result, alerts_path = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "info" ]]; then exit 0; fi\n'
            "printf '%s\\n' 'container crashed before app status'\n"
            "exit 1\n"
        ),
    )

    assert result.returncode == 1
    assert "container crashed before app status" in result.stdout
    alert_text = alerts_path.read_text(encoding="utf-8")
    assert "reason=scheduler_container_failed" in alert_text


def test_launchd_wrapper_sends_host_failure_when_stdout_capture_fails(
    tmp_path: Path,
) -> None:
    result, alerts_path = _run_wrapper_with_stubs(
        tmp_path,
        docker_script=(
            "#!/usr/bin/env bash\n"
            'if [[ "$1" == "info" ]]; then exit 0; fi\n'
            'printf \'%s\\n\' \'{"status": "pipeline_failed", "storage_key": null}\'\n'
            "exit 1\n"
        ),
        tee_script=("#!/usr/bin/env bash\ncat\nexit 1\n"),
    )

    assert result.returncode == 1
    assert '{"status": "pipeline_failed", "storage_key": null}' in result.stdout
    alert_text = alerts_path.read_text(encoding="utf-8")
    assert "reason=scheduler_stdout_capture_failed" in alert_text


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


def test_us_cutoff_alert_plist_runs_after_github_fallback_grace() -> None:
    payload = plistlib.loads(
        Path(
            "scripts/launchd/com.mochafreddo.sab.ai-brief.us.cutoff-alert.plist"
        ).read_bytes()
    )
    text = Path(
        "scripts/launchd/com.mochafreddo.sab.ai-brief.us.cutoff-alert.plist"
    ).read_text(encoding="utf-8")

    assert "<string>0929</string>" in text
    assert {item["Minute"] for item in payload["StartCalendarInterval"]} == {29}


def test_launchd_log_directory_exists_before_bootstrap() -> None:
    assert Path("logs/launchd/.gitkeep").is_file()


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
    assert "verify_ai_brief_plist_timing.py" in text
    assert "bash -n" in text
    assert "docker compose" in text
    assert "launchctl print" in text
    assert "launchctl bootstrap" not in text
    assert "launchctl bootout" not in text


def test_launchd_plist_timing_check_accepts_current_policy() -> None:
    result = _run_plist_timing_check(REPO_ROOT)

    assert result.returncode == 0, result.stderr
    assert "launchd plist timing matches shared schedule policy" in result.stdout


def test_launchd_plist_timing_check_rejects_drift(tmp_path: Path) -> None:
    launchd_dir = tmp_path / "scripts" / "launchd"
    shutil.copytree(REPO_ROOT / "scripts" / "launchd", launchd_dir)

    plist_path = launchd_dir / "com.mochafreddo.sab.ai-brief.us.local-primary.plist"
    payload = plistlib.loads(plist_path.read_bytes())
    payload["StartCalendarInterval"][0]["Minute"] = 11
    plist_path.write_bytes(plistlib.dumps(payload, sort_keys=False))

    result = _run_plist_timing_check(tmp_path)

    assert result.returncode == 1
    assert "StartCalendarInterval drift" in result.stderr
    assert "local-primary" in result.stderr
