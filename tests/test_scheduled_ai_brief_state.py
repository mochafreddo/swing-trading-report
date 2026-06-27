from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import cast

import pytest
from sab.scheduler.state import (
    RuntimeStateConfig,
    SchedulerStateError,
    SupabaseRuntimeStateClient,
    build_scheduler_state_key,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def get(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _FakeResponse:
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self._pop()

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: bytes,
        timeout: float,
    ) -> _FakeResponse:
        self.post_calls.append(
            {"url": url, "headers": headers, "data": data, "timeout": timeout}
        )
        return self._pop()

    def delete(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _FakeResponse:
        self.delete_calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self._pop()

    def _pop(self) -> _FakeResponse:
        if not self._responses:
            raise AssertionError("unexpected request")
        return self._responses.pop(0)


def _client(session: _FakeSession) -> SupabaseRuntimeStateClient:
    return SupabaseRuntimeStateClient(
        RuntimeStateConfig(
            url="https://example.supabase.co",
            service_role_key="sb_secret_test",
            timeout_seconds=3.0,
        ),
        session=session,
    )


def test_scheduler_state_keys_include_market_session_role_and_attempt() -> None:
    assert (
        build_scheduler_state_key(kind="lock", market="us", session_date="2026-05-28")
        == "scheduled-ai-brief:lock:US:2026-05-28"
    )
    assert (
        build_scheduler_state_key(
            kind="attempt",
            market="US",
            session_date="2026-05-28",
            runner_role="local-primary",
            attempt_id="0810-20260528T121000Z",
        )
        == "scheduled-ai-brief:attempt:US:2026-05-28:local-primary:0810-20260528T121000Z"
    )


def test_scheduler_state_keys_reject_unsafe_attempt_tokens() -> None:
    with pytest.raises(ValueError, match="attempt_id contains unsafe characters"):
        build_scheduler_state_key(
            kind="attempt",
            market="US",
            session_date="2026-05-28",
            runner_role="local-primary",
            attempt_id="attempt:ambiguous",
        )


def test_client_claim_lock_posts_owner_token_payload() -> None:
    session = _FakeSession(
        [_FakeResponse(200, [{"acquired": True, "expires_at": "2026-05-28T12:35:00Z"}])]
    )
    now = dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC)

    result = _client(session).claim_lock(
        key="scheduled-ai-brief:lock:US:2026-05-28",
        owner_token="owner-1",
        ttl_seconds=1500,
        now=now,
        payload={"attemptId": "attempt-1"},
    )

    assert result.acquired is True
    assert result.expires_at == "2026-05-28T12:35:00Z"
    call = session.post_calls[0]
    assert str(call["url"]).endswith("/rest/v1/rpc/claim_runtime_state_lock")
    body = json.loads(cast(bytes, call["data"]))
    assert body["p_now"] is None
    assert body["p_ttl_seconds"] == 1500
    assert body["p_state_payload"] == {
        "attemptId": "attempt-1",
        "ownerToken": "owner-1",
    }


def test_client_rejects_blank_owner_tokens_before_rpc_calls() -> None:
    session = _FakeSession([])
    client = _client(session)

    with pytest.raises(ValueError, match="owner_token must not be blank"):
        client.release_lock("key", owner_token=" ")
    with pytest.raises(ValueError, match="owner_token must not be blank"):
        client.renew_lock("key", owner_token="", ttl_seconds=60)
    with pytest.raises(ValueError, match="owner_token must not be blank"):
        client.check_ownership("key", owner_token="\t")

    assert session.post_calls == []


def test_client_upserts_marker_with_ttl() -> None:
    session = _FakeSession([_FakeResponse(201, [], "")])
    now = dt.datetime(2026, 5, 28, 12, 10, tzinfo=dt.UTC)

    _client(session).upsert_marker(
        key="scheduled-ai-brief:success:US:2026-05-28",
        payload={"market": "US"},
        ttl_seconds=48 * 60 * 60,
        now=now,
    )

    call = session.post_calls[0]
    assert str(call["url"]).endswith("/rest/v1/runtime_state?on_conflict=state_key")
    body = json.loads(cast(bytes, call["data"]))
    assert body == [
        {
            "state_key": "scheduled-ai-brief:success:US:2026-05-28",
            "state_payload": {"market": "US"},
            "expires_at": "2026-05-30T12:10:00+00:00",
        }
    ]


def test_runtime_state_scheduler_rpc_migration_rejects_blank_owner_tokens() -> None:
    migration = Path(
        "supabase/migrations/20260529090000_harden_runtime_state_scheduler_locks.sql"
    )
    sql = migration.read_text(encoding="utf-8")

    assert "create or replace function public.claim_runtime_state_lock" in sql
    assert "create or replace function public.renew_runtime_state_lock" in sql
    assert "create or replace function public.check_runtime_state_lock_owner" in sql
    assert "p_state_payload ->> 'ownerToken'" in sql
    assert "v_now timestamptz := now();" in sql
    assert "coalesce(p_now" not in sql
    assert "btrim(coalesce(p_owner_token, '')) = ''" in sql
    assert "state_payload ->> 'ownerToken'" in sql
    assert "owner token must not be blank" in sql
    assert "raise exception" in sql.lower()


def _extract_migration_function_body(sql: str, function_name: str) -> str:
    pattern = re.compile(
        rf"create or replace function public\.{re.escape(function_name)}\(.*?"
        rf"\nrevoke all on function public\.{re.escape(function_name)}\(",
        re.DOTALL,
    )
    match = pattern.search(sql)
    assert match is not None, f"{function_name} definition not found"
    return match.group(0)


@pytest.mark.parametrize(
    ("function_name", "required_patterns", "forbidden_patterns"),
    [
        (
            "claim_runtime_state_lock",
            [
                "delete from public.runtime_state as rs",
                "select rs.expires_at",
                "from public.runtime_state as rs",
                "where rs.state_key = p_state_key",
                "rs.expires_at <= v_now",
            ],
            [
                "delete from public.runtime_state\n  where state_key = p_state_key",
                "select runtime_state.expires_at",
                "where state_key = p_state_key",
                "and expires_at <= v_now",
            ],
        ),
        (
            "release_runtime_state_lock",
            [
                "delete from public.runtime_state as rs",
                "where rs.state_key = p_state_key",
                "rs.state_payload ->> 'ownerToken' = p_owner_token",
            ],
            [
                "delete from public.runtime_state\n  where state_key = p_state_key",
                "where state_key = p_state_key",
                "and state_payload ->> 'ownerToken' = p_owner_token",
            ],
        ),
        (
            "renew_runtime_state_lock",
            [
                "update public.runtime_state as rs",
                "where rs.state_key = p_state_key",
                "rs.expires_at > now()",
                "rs.state_payload ->> 'ownerToken' = p_owner_token",
            ],
            [
                "update public.runtime_state\n  set expires_at = v_expires_at",
                "where state_key = p_state_key",
                "and expires_at > now()",
                "and state_payload ->> 'ownerToken' = p_owner_token",
            ],
        ),
        (
            "check_runtime_state_lock_owner",
            [
                "from public.runtime_state as rs",
                "where rs.state_key = p_state_key",
                "rs.expires_at > now()",
                "rs.state_payload ->> 'ownerToken' = p_owner_token",
            ],
            [
                "from public.runtime_state\n      where state_key = p_state_key",
                "where state_key = p_state_key",
                "and expires_at > now()",
                "and state_payload ->> 'ownerToken' = p_owner_token",
            ],
        ),
    ],
)
def test_runtime_state_lock_rpc_hotfix_migration_uses_alias_qualified_columns(
    function_name: str,
    required_patterns: list[str],
    forbidden_patterns: list[str],
) -> None:
    migration = Path(
        "supabase/migrations/"
        "20260603090000_fix_runtime_state_lock_rpc_column_qualification.sql"
    )
    assert migration.exists()
    function_body = _extract_migration_function_body(
        migration.read_text(encoding="utf-8"),
        function_name,
    )

    for pattern in required_patterns:
        assert pattern in function_body
    for pattern in forbidden_patterns:
        assert pattern not in function_body


def test_client_raises_scheduler_state_error_on_failed_upsert() -> None:
    session = _FakeSession([_FakeResponse(500, {"error": "boom"}, "boom")])

    with pytest.raises(SchedulerStateError, match="failed to upsert runtime state"):
        _client(session).upsert_marker(
            key="scheduled-ai-brief:success:US:2026-05-28",
            payload={},
            ttl_seconds=60,
        )
