from __future__ import annotations

import json
import os
import plistlib
import shlex
import subprocess
import sys
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
    cwd: Path | None = None,
    home_dir: Path | None = None,
    path_env: str | None = None,
    curl_bin_dir: Path | None = None,
    uv_bin_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    effective_home_dir = home_dir or (tmp_path / "home")
    default_curl_bin_dir = curl_bin_dir or (effective_home_dir / ".local/bin")
    default_uv_bin_dir = uv_bin_dir or (effective_home_dir / ".local/share/mise/shims")
    default_curl_bin_dir.mkdir(parents=True, exist_ok=True)
    default_uv_bin_dir.mkdir(parents=True, exist_ok=True)
    env_file = tmp_path / ".env.scheduler.local"
    env_file.write_text(env_file_text, encoding="utf-8")
    _write_executable(default_curl_bin_dir / "curl", curl_script)
    _write_executable(
        default_uv_bin_dir / "uv",
        uv_script
        or (
            "#!/usr/bin/env bash\n"
            'printf \'%s\\n\' "$*" > "$UV_STUB_ARGS_FILE"\n'
            'printf \'%s\\n\' "$PWD" > "$UV_STUB_PWD_FILE"\n'
            'if [[ -n "${EXPECTED_REPO_ROOT:-}" && "$PWD" != "$EXPECTED_REPO_ROOT" ]]; then\n'
            "  exit 98\n"
            "fi\n"
            'if [[ "$1" != "run" || "$2" != "python" || "$3" != "-" ]]; then\n'
            "  exit 97\n"
            "fi\n"
            "shift 3\n"
            "script=''\n"
            "while IFS= read -r line; do script+=\"$line\"$'\\n'; done\n"
            f'{shlex.quote(sys.executable)} - "$@" <<< "$script"\n'
        ),
    )
    env = {
        **os.environ,
        "HOME": str(effective_home_dir),
        "PATH": path_env or os.environ.get("PATH", ""),
        "TOSS_SYNC_ENV_FILE": str(env_file),
        "TOSS_SYNC_CURRENT_TZ_FOR_TEST": "Asia/Seoul",
        "UV_STUB_ARGS_FILE": str(tmp_path / "uv.args"),
        "UV_STUB_PWD_FILE": str(tmp_path / "uv.pwd"),
        **(extra_env or {}),
    }
    if default_web_host_port is not None:
        env.setdefault("WEB_HOST_PORT", default_web_host_port)
    else:
        env.pop("WEB_HOST_PORT", None)
    return subprocess.run(
        [str(REPO_ROOT / "scripts/toss_daily_auto_sync.sh")],
        cwd=cwd or REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _read_uv_args(tmp_path: Path) -> str:
    return (tmp_path / "uv.args").read_text(encoding="utf-8")


def _read_uv_pwd(tmp_path: Path) -> str:
    return (tmp_path / "uv.pwd").read_text(encoding="utf-8").strip()


def _curl_stdin_recorder(recorder: Path) -> Path:
    return Path(f"{recorder}.stdin")


def _curl_pwd_recorder(recorder: Path) -> Path:
    return Path(f"{recorder}.pwd")


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
        f"printf '%s\\n' \"$PWD\" > {shlex.quote(_curl_pwd_recorder(recorder).as_posix())}\n"
        f"cat > {shlex.quote(_curl_stdin_recorder(recorder).as_posix())}\n"
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


def test_toss_daily_auto_sync_runner_posts_local_origin_without_token_in_argv(
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
    curl_config = _curl_stdin_recorder(recorder).read_text(encoding="utf-8")
    assert "test-token" not in args
    assert "http://127.0.0.1:55300/api/holdings/toss-sync/scheduled" in curl_config
    assert "Authorization: Bearer test-token" in curl_config
    assert "Origin: http://127.0.0.1:55300" in curl_config
    assert '\\"mode\\":\\"auto-apply\\"' in curl_config
    assert "--connect-timeout" in args
    assert "--max-time" in args
    assert "--retry" in args
    assert "--retry-all-errors" in args
    assert "http=200 status=applied" in result.stdout
    assert "test-token" not in result.stdout


def test_toss_daily_auto_sync_runner_escapes_job_token_in_curl_config(
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
                    "incomingCount": 0,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            recorder,
        ),
        env_file_text='TOSS_SYNC_JOB_TOKEN=line"one\\nsecond\\\\token\n',
    )

    assert result.returncode == 0
    curl_config = _curl_stdin_recorder(recorder).read_text(encoding="utf-8")
    assert 'Authorization: Bearer line\\"one\\\\nsecond\\\\\\\\token' in curl_config
    assert 'Authorization: Bearer line"one' not in curl_config


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
    curl_config = _curl_stdin_recorder(recorder).read_text(encoding="utf-8")
    assert "http://127.0.0.1:55444/api/holdings/toss-sync/scheduled" in curl_config
    assert "Origin: http://127.0.0.1:55444" in curl_config


def test_toss_daily_auto_sync_runner_changes_to_repo_root_before_http_request(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "curl.args"
    result = _run_runner(
        tmp_path,
        cwd=tmp_path,
        extra_env={"EXPECTED_REPO_ROOT": str(REPO_ROOT)},
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "unchanged",
                "summary": {
                    "incomingCount": 0,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            recorder,
        ),
    )

    assert result.returncode == 0
    assert _curl_pwd_recorder(recorder).read_text(encoding="utf-8").strip() == str(
        REPO_ROOT
    )


def test_toss_daily_auto_sync_runner_bootstraps_path_for_launchd_environment(
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "fake-home"
    curl_bin_dir = fake_home / ".local/bin"
    uv_bin_dir = fake_home / ".local/share/mise/shims"
    recorder = tmp_path / "curl.args"

    result = _run_runner(
        tmp_path,
        curl_bin_dir=curl_bin_dir,
        uv_bin_dir=uv_bin_dir,
        home_dir=fake_home,
        path_env="/bin",
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "applied",
                "summary": {
                    "incomingCount": 3,
                    "createCount": 1,
                    "updateCount": 1,
                    "deleteCount": 0,
                    "unchangedCount": 1,
                },
                "blockedRows": [],
            },
            recorder,
        ),
    )

    assert result.returncode == 0
    assert "http=200 status=applied" in result.stdout
    assert (
        "incoming=3 create=1 update=1 delete=0 unchanged=1 blocked=0" in result.stdout
    )
    assert "test-token" not in result.stdout
    args = recorder.read_text(encoding="utf-8")
    curl_config = _curl_stdin_recorder(recorder).read_text(encoding="utf-8")
    assert "test-token" not in args
    assert "Authorization: Bearer test-token" in curl_config


def test_toss_daily_auto_sync_runner_preflights_json_parser_before_http_request(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "curl.args"
    missing_parser = tmp_path / "missing-python3"

    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "applied",
                "summary": {
                    "incomingCount": 1,
                    "createCount": 1,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            recorder,
        ),
        extra_env={"TOSS_SYNC_PYTHON_BIN": str(missing_parser)},
    )

    assert result.returncode != 0
    assert "JSON parser command is not available" in result.stderr
    assert not recorder.exists()


def test_toss_daily_auto_sync_runner_fails_closed_on_timezone_mismatch(
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
                    "incomingCount": 1,
                    "createCount": 1,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [],
            },
            recorder,
        ),
        extra_env={"TOSS_SYNC_CURRENT_TZ_FOR_TEST": "UTC"},
    )

    assert result.returncode != 0
    assert "Host timezone must be Asia/Seoul; detected UTC" in result.stderr
    assert not recorder.exists()


@pytest.mark.parametrize(
    ("status", "incoming_count", "delete_count"),
    [
        ("disabled", 0, 0),
        ("wipe_guard_blocked", 0, 2),
        ("delete_guard_blocked", 1, 1),
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


def test_toss_daily_auto_sync_runner_exits_nonzero_for_blocked_status(
    tmp_path: Path,
) -> None:
    result = _run_runner(
        tmp_path,
        curl_script=_curl_response(
            {
                "mode": "auto-apply",
                "status": "blocked",
                "summary": {
                    "incomingCount": 1,
                    "createCount": 0,
                    "updateCount": 0,
                    "deleteCount": 0,
                    "unchangedCount": 0,
                },
                "blockedRows": [{"symbol": "AAPL.NAS"}],
            },
            tmp_path / "curl.args",
        ),
    )

    assert result.returncode != 0
    assert "http=200 status=blocked" in result.stdout
    assert "blocked=1" in result.stdout


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


def test_toss_daily_auto_sync_launchd_plist_runs_before_signal_jobs() -> None:
    plist_path = (
        REPO_ROOT / "scripts/launchd/com.mochafreddo.sab.toss-daily-auto-sync.plist"
    )
    payload = plistlib.loads(plist_path.read_bytes())

    assert payload["Label"] == "com.mochafreddo.sab.toss-daily-auto-sync"
    assert payload["ProgramArguments"][0].endswith("scripts/toss_daily_auto_sync.sh")
    intervals = payload["StartCalendarInterval"]
    assert isinstance(intervals, list)
    assert sorted(
        intervals, key=lambda item: (item["Weekday"], item["Hour"], item["Minute"])
    ) == sorted(
        [
            *(
                {"Hour": hour, "Minute": minute, "Weekday": weekday}
                for hour, minute in ((6, 55), (7, 15))
                for weekday in range(2, 7)
            ),
            *(
                {"Hour": hour, "Minute": minute, "Weekday": weekday}
                for hour, minute in ((21, 5), (21, 40), (22, 5), (22, 40))
                for weekday in range(1, 6)
            ),
        ],
        key=lambda item: (item["Weekday"], item["Hour"], item["Minute"]),
    )
