from __future__ import annotations

import datetime as dt
import importlib
import io
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sab.scheduler.state import RuntimeStateEntry


def _load_module():
    try:
        return importlib.import_module("scripts.verify_scheduled_sell_runtime_state")
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"scheduled sell runtime_state verification script is missing: {exc}"
        )


@dataclass
class _FakeRuntimeStateClient:
    entries: dict[str, RuntimeStateEntry] = field(default_factory=dict)
    listed_prefixes: list[tuple[str, int]] = field(default_factory=list)
    fetched_keys: list[str] = field(default_factory=list)

    def get_entry(self, key: str) -> RuntimeStateEntry | None:
        self.fetched_keys.append(key)
        return self.entries.get(key)

    def list_entries(self, *, prefix: str, limit: int = 20) -> list[RuntimeStateEntry]:
        self.listed_prefixes.append((prefix, limit))
        return [
            entry
            for key, entry in sorted(self.entries.items())
            if key.startswith(prefix)
        ][:limit]


@dataclass
class _PrefixWindowRuntimeStateClient(_FakeRuntimeStateClient):
    omitted_list_key: str = ""

    def list_entries(self, *, prefix: str, limit: int = 20) -> list[RuntimeStateEntry]:
        self.listed_prefixes.append((prefix, limit))
        return [
            entry
            for key, entry in sorted(self.entries.items())
            if key.startswith(prefix) and key != self.omitted_list_key
        ][:limit]


@dataclass
class _FailingRuntimeStateClient:
    exception: Exception

    def get_entry(self, key: str) -> RuntimeStateEntry | None:
        raise self.exception


def _entry(
    key: str,
    payload: dict[str, object],
    *,
    expires_at: str = "2026-07-09T00:00:00Z",
) -> RuntimeStateEntry:
    return RuntimeStateEntry(
        state_key=key,
        state_payload=payload,
        expires_at=expires_at,
    )


def test_reports_success_when_freshness_and_success_markers_exist() -> None:
    verify = _load_module()
    secret = "sb_secret_should_not_leak"
    client = _FakeRuntimeStateClient(
        {
            "toss-sync:success:MIXED:2026-07-08": _entry(
                "toss-sync:success:MIXED:2026-07-08",
                {
                    "scope": "MIXED",
                    "sessionDate": "2026-07-08",
                    "status": "applied",
                    "quarantinedCount": 1,
                    "quarantinedTickers": ["META.NAS"],
                },
            ),
            "scheduled-sell:success:MIXED:2026-07-08": _entry(
                "scheduled-sell:success:MIXED:2026-07-08",
                {"storageKey": "2026/07/2026-07-08.sell-ai-brief.json"},
            ),
        }
    )
    output = io.StringIO()
    error = io.StringIO()

    exit_code = verify.run_verification(
        client,
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env={
            "SUPABASE_URL": "https://scheduler-project.supabase.co",
            "SUPABASE_SECRET_KEY": secret,
        },
        web_env={"SUPABASE_URL": "https://scheduler-project.supabase.co"},
        output=output,
        error=error,
        now=dt.datetime(2026, 7, 8, 1, 0, tzinfo=dt.UTC),
    )

    text = output.getvalue()
    assert exit_code == 0
    assert "readiness=ready" in text
    assert "toss-sync:success:MIXED:2026-07-08 present status=applied" in text
    assert "quarantined=1 quarantined_tickers=META.NAS" in text
    assert "scheduled-sell:success:MIXED:2026-07-08 present" in text
    assert "supabase_env_match=true" in text
    assert "scheduled-sell:success:MIXED:2026-07-08" in client.fetched_keys
    assert client.listed_prefixes == []
    assert secret not in text
    assert secret not in error.getvalue()


def test_uses_exact_scheduled_marker_lookup_when_prefix_page_omits_target() -> None:
    verify = _load_module()
    success_key = "scheduled-sell:success:MIXED:2026-07-08"
    client = _PrefixWindowRuntimeStateClient(
        entries={
            "toss-sync:success:MIXED:2026-07-08": _entry(
                "toss-sync:success:MIXED:2026-07-08",
                {
                    "scope": "MIXED",
                    "sessionDate": "2026-07-08",
                    "status": "applied",
                },
            ),
            success_key: _entry(
                success_key,
                {"storageKey": "2026/07/2026-07-08.sell-ai-brief.json"},
            ),
            **{
                f"scheduled-sell:attempt:MIXED:2026-07-09:local-primary:{idx}": _entry(
                    f"scheduled-sell:attempt:MIXED:2026-07-09:local-primary:{idx}",
                    {"attempt": idx},
                )
                for idx in range(120)
            },
        },
        omitted_list_key=success_key,
    )
    output = io.StringIO()

    exit_code = verify.run_verification(
        client,
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env={"SUPABASE_URL": "http://127.0.0.1:54321"},
        web_env={"SUPABASE_URL": "http://127.0.0.1:54321"},
        output=output,
        error=io.StringIO(),
        now=dt.datetime(2026, 7, 8, 1, 0, tzinfo=dt.UTC),
    )

    assert exit_code == 0
    assert "readiness=ready" in output.getvalue()
    assert success_key in client.fetched_keys
    assert client.listed_prefixes == []


@pytest.mark.parametrize(
    ("payload", "expires_at", "reason"),
    [
        (
            {"scope": "MIXED", "sessionDate": "2026-07-07", "status": "applied"},
            "2026-07-09T00:00:00Z",
            "toss_freshness_invalid",
        ),
        (
            {"scope": "KR", "sessionDate": "2026-07-08", "status": "applied"},
            "2026-07-09T00:00:00Z",
            "toss_freshness_invalid",
        ),
        (
            {"scope": "MIXED", "sessionDate": "2026-07-08", "status": "applied"},
            "2026-07-08T00:00:00Z",
            "toss_freshness_stale",
        ),
    ],
)
def test_rejects_toss_marker_that_generation_gate_would_block(
    payload: dict[str, object],
    expires_at: str,
    reason: str,
) -> None:
    verify = _load_module()
    client = _FakeRuntimeStateClient(
        {
            "toss-sync:success:MIXED:2026-07-08": _entry(
                "toss-sync:success:MIXED:2026-07-08",
                payload,
                expires_at=expires_at,
            ),
            "scheduled-sell:success:MIXED:2026-07-08": _entry(
                "scheduled-sell:success:MIXED:2026-07-08",
                {"storageKey": "2026/07/2026-07-08.sell-ai-brief.json"},
            ),
        }
    )
    output = io.StringIO()

    exit_code = verify.run_verification(
        client,
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env={"SUPABASE_URL": "http://127.0.0.1:54321"},
        web_env={"SUPABASE_URL": "http://127.0.0.1:54321"},
        output=output,
        error=io.StringIO(),
        now=dt.datetime(2026, 7, 8, 1, 0, tzinfo=dt.UTC),
    )

    text = output.getvalue()
    assert exit_code == 1
    assert "readiness=blocked" in text
    assert reason in text
    assert "treat_as=holdings_freshness_problem" in text


def test_returns_query_failure_exit_code_without_leaking_secrets() -> None:
    verify = _load_module()
    output = io.StringIO()
    error = io.StringIO()

    exit_code = verify.run_verification(
        _FailingRuntimeStateClient(
            RuntimeError("connection failed with sb_secret_scheduler")
        ),
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env={
            "SUPABASE_URL": "https://scheduler-project.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_scheduler",
        },
        web_env={"SUPABASE_URL": "https://scheduler-project.supabase.co"},
        output=output,
        error=error,
    )

    assert exit_code == 2
    assert "runtime_state query failed" in error.getvalue()
    assert "sb_secret_scheduler" not in output.getvalue()
    assert "sb_secret_scheduler" not in error.getvalue()


def test_reports_blocked_when_freshness_missing_and_blocked_markers_exist() -> None:
    verify = _load_module()
    client = _FakeRuntimeStateClient(
        {
            "scheduled-sell:blocked:MIXED:2026-07-08": _entry(
                "scheduled-sell:blocked:MIXED:2026-07-08",
                {"reason": "toss_freshness_missing"},
            ),
            "scheduled-sell:notification:blocked-sent:MIXED:2026-07-08": _entry(
                "scheduled-sell:notification:blocked-sent:MIXED:2026-07-08",
                {"channel": "telegram"},
            ),
        }
    )
    output = io.StringIO()

    exit_code = verify.run_verification(
        client,
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env={"SUPABASE_URL": "http://127.0.0.1:54321"},
        web_env={"SUPABASE_URL": "http://127.0.0.1:54321"},
        output=output,
        error=io.StringIO(),
    )

    text = output.getvalue()
    assert exit_code == 1
    assert "readiness=blocked" in text
    assert "toss-sync:success:MIXED:2026-07-08 missing" in text
    assert "scheduled-sell:blocked:MIXED:2026-07-08 present" in text
    assert "scheduled-sell:notification:blocked-sent:MIXED:2026-07-08 present" in text
    assert "treat_as=holdings_freshness_problem" in text


def test_loads_env_files_and_warns_when_supabase_sources_drift(
    tmp_path: Path,
) -> None:
    verify = _load_module()
    scheduler_env_file = tmp_path / ".env.scheduler.local"
    web_env_file = tmp_path / ".env"
    scheduler_env_file.write_text(
        "\n".join(
            [
                "SUPABASE_URL=https://scheduler-project.supabase.co",
                "SUPABASE_SECRET_KEY=sb_secret_scheduler",
            ]
        ),
        encoding="utf-8",
    )
    web_env_file.write_text(
        "SUPABASE_URL=https://web-project.supabase.co\n",
        encoding="utf-8",
    )

    scheduler_env = verify.load_env_file(scheduler_env_file)
    web_env = verify.load_env_file(web_env_file)
    output = io.StringIO()

    exit_code = verify.run_verification(
        _FakeRuntimeStateClient(),
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env=scheduler_env,
        web_env=web_env,
        output=output,
        error=io.StringIO(),
    )

    text = output.getvalue()
    assert exit_code == 1
    assert "supabase_env_match=false" in text
    assert "scheduler-project" in text
    assert "web-project" in text
    assert "sb_secret_scheduler" not in text


def test_web_env_comparison_keeps_file_url_when_shell_has_scheduler_env(
    tmp_path: Path,
) -> None:
    verify = _load_module()
    web_env_file = tmp_path / ".env"
    web_env_file.write_text(
        "SUPABASE_URL=https://web-project.supabase.co\n",
        encoding="utf-8",
    )
    shell_env = {
        "SUPABASE_URL": "https://scheduler-project.supabase.co",
        "SUPABASE_SECRET_KEY": "sb_secret_scheduler",
    }

    web_env = verify.load_comparison_env_file(web_env_file, environ=shell_env)
    output = io.StringIO()

    exit_code = verify.run_verification(
        _FakeRuntimeStateClient(),
        session_date="2026-07-08",
        scope="MIXED",
        scheduler_env=shell_env,
        web_env=web_env,
        output=output,
        error=io.StringIO(),
    )

    text = output.getvalue()
    assert exit_code == 1
    assert "supabase_env_match=false" in text
    assert "scheduler-project" in text
    assert "web-project" in text
    assert "sb_secret_scheduler" not in text


def test_default_session_date_uses_kst_date() -> None:
    verify = _load_module()
    now = dt.datetime(2026, 7, 7, 16, 0, tzinfo=dt.UTC)

    assert verify.resolve_kst_session_date(now) == "2026-07-08"
