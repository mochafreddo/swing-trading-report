from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS_RESPONSE = (
    '{"items":[{"ticker":"005930","quantity":2,"entry_price":70000},'
    '{"ticker":"AAPL.NAS","quantity":1,"entry_price":190}],"nextCursor":null}'
)
DEFAULT_RUNNER_STDOUT = "http=200 status=applied incoming=2 create=0 update=2 delete=0 unchanged=0 blocked=0"
LOCAL_QA_ENV = {
    "SUPABASE_URL": "http://127.0.0.1:54321",
    "SUPABASE_SECRET_KEY": "secret",
    "SAB_BASIC_AUTH_USER": "admin",
    "SAB_BASIC_AUTH_PASS": "password",
    "SAB_SESSION_SECRET": "abcdefghijklmnopqrstuvwxyz123456",
    "TOSS_SYNC_JOB_TOKEN": "qa-token",
}


def _env_file_text(**overrides: str) -> str:
    values = {**LOCAL_QA_ENV, **overrides}
    return "".join(f"{key}={value}\n" for key, value in values.items())


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _run_qa_script(
    tmp_path: Path,
    *,
    env_file_text: str,
    holdings_response: str = DEFAULT_HOLDINGS_RESPONSE,
    runner_stdout: str = DEFAULT_RUNNER_STDOUT,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env_file = tmp_path / ".env.qa.local"
    env_file.write_text(env_file_text, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "TOSS_SYNC_QA_ENV_FILE": str(env_file),
        "TOSS_SYNC_QA_DOCKER_LOG": str(tmp_path / "docker.log"),
        "TOSS_SYNC_QA_CURL_LOG": str(tmp_path / "curl.log"),
        "TOSS_SYNC_QA_RUNNER_BIN": str(tmp_path / "runner.sh"),
        "TOSS_SYNC_QA_WORK_DIR": str(tmp_path / "qa-work"),
        **(extra_env or {}),
    }
    _write_executable(
        bin_dir / "docker",
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$TOSS_SYNC_QA_DOCKER_LOG"\n'
        'env | sort | grep -E "^(SUPABASE_URL|TOSS_SYNC_)" >> "$TOSS_SYNC_QA_DOCKER_LOG"\n',
    )
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$TOSS_SYNC_QA_CURL_LOG"\n'
        'cat >> "$TOSS_SYNC_QA_CURL_LOG"\n'
        'if [[ "$*" == *"/login"* && "$*" != *"/api/auth/login"* ]]; then\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$*" == *"/api/holdings/yaml"* && "$*" == *"--request POST"* ]]; then\n'
        '  printf "%s\\n" \'{"mode":"apply","summary":{"incomingCount":2,"createCount":0,"updateCount":2,"deleteCount":0,"unchangedCount":0}}\'\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$*" == *"/api/holdings/yaml"* ]]; then\n'
        '  printf "%s\\n" "version: 1"\n'
        '  printf "%s\\n" "holdings: []"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$*" == *"/api/holdings?"* ]]; then\n'
        f"  printf '%s\\n' {holdings_response!r}\n"
        "  exit 0\n"
        "fi\n"
        'printf "%s\\n" \'{"ok":true}\'\n',
    )
    _write_executable(
        Path(env["TOSS_SYNC_QA_RUNNER_BIN"]),
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "runner" > "$TOSS_SYNC_QA_WORK_DIR/runner.log"\n'
        f"printf '%s\\n' {runner_stdout!r}\n",
    )
    return subprocess.run(
        [str(REPO_ROOT / "scripts/qa_toss_sync_local.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_toss_sync_qa_local_refuses_non_loopback_supabase(
    tmp_path: Path,
) -> None:
    result = _run_qa_script(
        tmp_path,
        env_file_text=_env_file_text(SUPABASE_URL="https://example.supabase.co"),
    )

    assert result.returncode != 0
    assert "refuses to run against non-local SUPABASE_URL" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_toss_sync_qa_local_starts_web_with_fixture_source_and_runs_valid_token_flow(
    tmp_path: Path,
) -> None:
    result = _run_qa_script(
        tmp_path,
        env_file_text=_env_file_text(WEB_HOST_PORT="55444"),
    )

    assert result.returncode == 0, result.stderr
    docker_log = (tmp_path / "docker.log").read_text(encoding="utf-8")
    assert docker_log.count("compose up -d --build web") == 2
    assert "SUPABASE_URL=http://host.docker.internal:54321" in docker_log
    assert "TOSS_SYNC_QA_FIXTURE_ENABLED=1" in docker_log
    assert "TOSS_SYNC_SOURCE=fixture" in docker_log
    assert "TOSS_SYNC_AUTO_APPLY_ENABLED=1" in docker_log
    assert "status=applied" in result.stdout
    assert (tmp_path / "qa-work/runner.log").exists()
    for filename in (
        "cookies.txt",
        "holdings.backup.yaml",
        "login.json",
        "restore.json",
        "seed.json",
    ):
        assert not (tmp_path / f"qa-work/{filename}").exists()


def test_toss_sync_qa_local_refuses_non_loopback_base_url(
    tmp_path: Path,
) -> None:
    result = _run_qa_script(
        tmp_path,
        env_file_text=_env_file_text(),
        extra_env={"TOSS_SYNC_QA_BASE_URL": "https://example.com"},
    )

    assert result.returncode != 0
    assert "refuses to run against non-local TOSS_SYNC_QA_BASE_URL" in result.stderr
    assert not (tmp_path / "docker.log").exists()


def test_toss_sync_qa_local_requires_the_seeded_diff_to_apply(
    tmp_path: Path,
) -> None:
    result = _run_qa_script(
        tmp_path,
        env_file_text=_env_file_text(),
        runner_stdout=(
            "http=200 status=unchanged incoming=2 create=0 update=0 "
            "delete=0 unchanged=2 blocked=0"
        ),
    )

    assert result.returncode != 0
    assert "Toss sync QA runner did not apply the seeded fixture diff" in result.stderr


def test_toss_sync_qa_local_verifies_expected_fixture_values(
    tmp_path: Path,
) -> None:
    result = _run_qa_script(
        tmp_path,
        env_file_text=_env_file_text(),
        holdings_response=(
            '{"items":[{"ticker":"005930","quantity":1,"entry_price":69000},'
            '{"ticker":"AAPL.NAS","quantity":1,"entry_price":185}],'
            '"nextCursor":null}'
        ),
    )

    assert result.returncode != 0
    assert "unexpected QA holding values" in result.stderr
