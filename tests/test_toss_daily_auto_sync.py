from __future__ import annotations

import json
import os
import plistlib
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run_runner(
    tmp_path: Path,
    *,
    curl_script: str,
    uv_script: str | None = None,
    env_file_text: str = "TOSS_SYNC_JOB_TOKEN=test-token\n",
    default_web_host_port: str | None = "55300",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env_file = tmp_path / ".env.scheduler.local"
    env_file.write_text(env_file_text, encoding="utf-8")
    _write_executable(bin_dir / "curl", curl_script)
    _write_executable(
        bin_dir / "uv",
        uv_script
        or (
            "#!/usr/bin/env bash\n"
            "shift 2\n"
            "script=''\n"
            "while IFS= read -r line; do script+=\"$line\"$'\\n'; done\n"
            'python3 - "$@" <<< "$script"\n'
        ),
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "TOSS_SYNC_ENV_FILE": str(env_file),
        **(extra_env or {}),
    }
    if default_web_host_port is not None:
        env.setdefault("WEB_HOST_PORT", default_web_host_port)
    return subprocess.run(
        [str(REPO_ROOT / "scripts/toss_daily_auto_sync.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _curl_response(
    payload: dict[str, object],
    recorder: Path,
    *,
    http_status: str = "200",
    exit_code: int = 0,
) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" > {shlex.quote(recorder.as_posix())}\n"
        "output_file=''\n"
        "write_out=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  case "$1" in\n'
        "    --output)\n"
        '      output_file="$2"\n'
        "      shift 2\n"
        "      ;;\n"
        "    --write-out)\n"
        '      write_out="$2"\n'
        "      shift 2\n"
        "      ;;\n"
        "    *)\n"
        "      shift\n"
        "      ;;\n"
        "  esac\n"
        "done\n"
        'if [[ -n "$output_file" ]]; then\n'
        f"  cat <<'JSON' > \"$output_file\"\n{json.dumps(payload)}\nJSON\n"
        "else\n"
        f"  cat <<'JSON'\n{json.dumps(payload)}\nJSON\n"
        "fi\n"
        "if [[ \"$write_out\" == '%{http_code}' ]]; then\n"
        f"  printf '%s' {shlex.quote(http_status)}\n"
        "fi\n"
        f"exit {exit_code}\n"
    )


def test_toss_daily_auto_sync_runner_requires_job_token(tmp_path: Path) -> None:
    result = _run_runner(
        tmp_path,
        curl_script="#!/usr/bin/env bash\nexit 99\n",
        env_file_text="",
    )

    assert result.returncode != 0
    assert "TOSS_SYNC_JOB_TOKEN must be set" in result.stderr


def test_toss_daily_auto_sync_runner_posts_local_origin_and_token(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "curl.args"
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "applied",
                "summary": {
                    "incomingCount": 2,
                    "createCount": 0,
                    "updateCount": 1,
                    "deleteCount": 1,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            recorder,
        ),
    )

    assert result.returncode == 0
    args = recorder.read_text(encoding="utf-8")
    assert "http://127.0.0.1:55300/api/holdings/toss-sync/scheduled" in args
    assert "Authorization: Bearer test-token" in args
    assert "Origin: http://127.0.0.1:55300" in args
    assert '"mode":"auto-apply"' in args
    assert "http=200 status=applied" in result.stdout
    assert "test-token" not in result.stdout


def test_toss_daily_auto_sync_runner_uses_web_host_port_from_env_file(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "curl.args"
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "unchanged",
                "summary": {
                    "incomingCount": 1,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 1,
                },
                "blockedRows": [],
            },
            recorder,
        ),
        env_file_text="TOSS_SYNC_JOB_TOKEN=test-token\nWEB_HOST_PORT=55444\n",
        default_web_host_port=None,
    )

    assert result.returncode == 0
    args = recorder.read_text(encoding="utf-8")
    assert "http://127.0.0.1:55444/api/holdings/toss-sync/scheduled" in args
    assert "Origin: http://127.0.0.1:55444" in args


@pytest.mark.parametrize(
    ("status", "incoming_count", "delete_count"),
    [
        ("disabled", 0, 0),
        ("wipe_guard_blocked", 0, 2),
        ("error", 0, 0),
    ],
)
def test_toss_daily_auto_sync_runner_exits_nonzero_for_unsuccessful_statuses(
    tmp_path: Path,
    status: str,
    incoming_count: int,
    delete_count: int,
) -> None:
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": status,
                "summary": {
                    "incomingCount": incoming_count,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": delete_count,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            tmp_path / "curl.args",
        ),
    )

    assert result.returncode != 0
    assert f"http=200 status={status}" in result.stdout


def test_toss_daily_auto_sync_runner_prints_bounded_summary_for_http_error_json(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "error",
                "summary": {
                    "incomingCount": 0,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            tmp_path / "curl.args",
            http_status="500",
        ),
    )

    assert result.returncode != 0
    assert (
        "http=500 status=error incoming=0 create=0 update=0 delete=0 "
        "unchanged=0 blocked=0"
    ) in result.stdout


def test_toss_daily_auto_sync_runner_fail_closed_on_http_error_status(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "applied",
                "summary": {
                    "incomingCount": 1,
                    "createCount": 0,
                    "updateCount": 1,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            tmp_path / "curl.args",
            http_status="500",
        ),
    )

    assert result.returncode != 0
    assert "http=500 status=applied" in result.stdout


def test_toss_daily_auto_sync_launchd_plist_runs_at_0805() -> None:
    plist_path = (
        REPO_ROOT / "scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist"
    )
    payload = plistlib.loads(plist_path.read_bytes())

    assert payload["Label"] == "com.mochafreddo.sab.toss-daily-auto-sync"
    assert payload["ProgramArguments"][0].endswith("scripts/toss_daily_auto_sync.sh")
    interval = payload["StartCalendarInterval"]
    assert interval == {"Hour": 8, "Minute": 5}
