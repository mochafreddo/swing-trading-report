from __future__ import annotations

import datetime as dt
import importlib
import io
from dataclasses import dataclass

import pytest
from sab.scheduler.state import RuntimeStateLockClaim, SchedulerStateError

SMOKE_NOW = dt.datetime(2026, 6, 3, 9, 0, tzinfo=dt.UTC)


def _load_smoke_module():
    try:
        return importlib.import_module("scripts.runtime_state_lock_smoke")
    except ModuleNotFoundError as exc:
        pytest.fail(f"runtime_state lock smoke script is missing: {exc}")


@dataclass(frozen=True)
class _SmokeCall:
    operation: str
    owner_token: str


class _FakeRuntimeStateClient:
    def __init__(
        self,
        *,
        fail_on: str | None = None,
        fail_final_cleanup: bool = False,
    ) -> None:
        self.calls: list[_SmokeCall] = []
        self.correct_owner_token: str | None = None
        self.fail_on = fail_on
        self.fail_final_cleanup = fail_final_cleanup
        self.correct_owner_release_count = 0
        self.held = False

    def claim_lock(
        self,
        *,
        key: str,
        owner_token: str,
        ttl_seconds: int,
        now: dt.datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> RuntimeStateLockClaim:
        del key, ttl_seconds, now, payload
        self.calls.append(_SmokeCall("claim", owner_token))
        if self.correct_owner_token is None:
            self.correct_owner_token = owner_token
        if self.held:
            return RuntimeStateLockClaim(
                acquired=False,
                expires_at="2026-06-03T09:01:00+00:00",
            )
        self.held = True
        return RuntimeStateLockClaim(
            acquired=True,
            expires_at="2026-06-03T09:01:00+00:00",
        )

    def check_ownership(self, key: str, *, owner_token: str) -> bool:
        del key
        self.calls.append(_SmokeCall("check", owner_token))
        return self.held and owner_token == self.correct_owner_token

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool:
        del key, ttl_seconds
        self.calls.append(_SmokeCall("renew", owner_token))
        if self.fail_on == "correct-renew" and owner_token == self.correct_owner_token:
            raise SchedulerStateError("synthetic renew failure")
        return self.held and owner_token == self.correct_owner_token

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        del key
        self.calls.append(_SmokeCall("release", owner_token))
        if owner_token == self.correct_owner_token:
            self.correct_owner_release_count += 1
            if self.fail_final_cleanup and self.correct_owner_release_count == 2:
                return False
        if self.held and owner_token == self.correct_owner_token:
            self.held = False
            return True
        return False


def test_runtime_state_lock_smoke_runs_positive_and_wrong_owner_sequence() -> None:
    smoke = _load_smoke_module()
    client = _FakeRuntimeStateClient()
    output = io.StringIO()
    error = io.StringIO()

    exit_code = smoke.run_smoke(
        client,
        now=SMOKE_NOW,
        output=output,
        error=error,
    )

    assert exit_code == 0
    assert [call.operation for call in client.calls] == [
        "claim",
        "claim",
        "check",
        "renew",
        "release",
        "check",
        "renew",
        "release",
        "claim",
        "release",
    ]
    assert client.correct_owner_token is not None
    wrong_owner_tokens = {
        call.owner_token
        for call in client.calls[2:5]
        if call.owner_token != client.correct_owner_token
    }
    assert len(wrong_owner_tokens) == 1
    assert "runtime_state lock smoke passed" in output.getvalue()
    assert error.getvalue() == ""


def test_runtime_state_lock_smoke_releases_synthetic_lock_on_failure() -> None:
    smoke = _load_smoke_module()
    client = _FakeRuntimeStateClient(fail_on="correct-renew")
    output = io.StringIO()
    error = io.StringIO()

    exit_code = smoke.run_smoke(
        client,
        now=SMOKE_NOW,
        output=output,
        error=error,
    )

    assert exit_code == 1
    assert client.calls[-1].operation == "release"
    assert client.calls[-1].owner_token == client.correct_owner_token
    assert "correct-owner renew" in error.getvalue()
    assert "runtime_state lock smoke failed" in error.getvalue()


def test_runtime_state_lock_smoke_returns_nonzero_when_final_cleanup_fails() -> None:
    smoke = _load_smoke_module()
    client = _FakeRuntimeStateClient(fail_final_cleanup=True)
    output = io.StringIO()
    error = io.StringIO()

    exit_code = smoke.run_smoke(
        client,
        now=SMOKE_NOW,
        output=output,
        error=error,
    )

    assert exit_code == 1
    assert client.calls[-1].operation == "release"
    assert "runtime_state lock smoke passed" not in output.getvalue()
    assert "cleanup release returned false" in error.getvalue()


def test_runtime_state_lock_smoke_output_does_not_include_service_role_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke = _load_smoke_module()
    client = _FakeRuntimeStateClient()
    secret = "sb_secret_should_not_be_printed"
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", secret)
    monkeypatch.setattr(
        smoke.SupabaseRuntimeStateClient,
        "from_env",
        staticmethod(lambda: client),
    )

    exit_code = smoke.main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert secret not in captured.out
    assert secret not in captured.err
