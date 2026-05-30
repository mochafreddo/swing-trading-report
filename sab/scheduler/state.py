from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests  # type: ignore[import-untyped]


class SchedulerStateError(RuntimeError):
    """Raised when scheduler runtime_state access fails."""


@dataclass(frozen=True)
class RuntimeStateConfig:
    url: str
    service_role_key: str
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class RuntimeStateEntry:
    state_key: str
    state_payload: dict[str, object]
    expires_at: str


@dataclass(frozen=True)
class RuntimeStateLockClaim:
    acquired: bool
    expires_at: str


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _normalize_market(market: str) -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in {"KR", "US"}:
        raise ValueError("market must be KR or US")
    return normalized


def _require_non_blank(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


def build_scheduler_state_key(
    *,
    kind: str,
    market: str,
    session_date: str,
    runner_role: str | None = None,
    attempt_id: str | None = None,
) -> str:
    normalized_kind = _require_non_blank(kind, field_name="kind").lower()
    normalized_market = _normalize_market(market)
    normalized_session_date = _require_non_blank(
        session_date, field_name="session_date"
    )

    base = f"scheduled-ai-brief:{normalized_kind}:{normalized_market}:{normalized_session_date}"
    if normalized_kind != "attempt":
        return base

    normalized_runner_role = _require_non_blank(
        runner_role or "", field_name="runner_role"
    )
    normalized_attempt_id = _require_non_blank(
        attempt_id or "", field_name="attempt_id"
    )
    return f"{base}:{normalized_runner_role}:{normalized_attempt_id}"


def _parse_runtime_state_entry(payload: object) -> RuntimeStateEntry | None:
    entries = _parse_runtime_state_entries(payload)
    return entries[0] if entries else None


def _parse_runtime_state_entries(payload: object) -> list[RuntimeStateEntry]:
    if not isinstance(payload, list):
        return []

    entries: list[RuntimeStateEntry] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        state_key = raw.get("state_key")
        state_payload = raw.get("state_payload")
        expires_at = raw.get("expires_at")
        if (
            not isinstance(state_key, str)
            or not state_key.strip()
            or not isinstance(state_payload, dict)
            or not isinstance(expires_at, str)
            or not expires_at.strip()
        ):
            continue
        entries.append(
            RuntimeStateEntry(
                state_key=state_key,
                state_payload=dict(state_payload),
                expires_at=expires_at,
            )
        )
    return entries


def _parse_claim_result(payload: object) -> RuntimeStateLockClaim:
    if not isinstance(payload, list) or not payload:
        raise SchedulerStateError("failed to parse runtime state lock claim result")
    raw = payload[0]
    if not isinstance(raw, dict):
        raise SchedulerStateError("failed to parse runtime state lock claim result")
    acquired = raw.get("acquired")
    expires_at = raw.get("expires_at")
    if not isinstance(acquired, bool) or not isinstance(expires_at, str):
        raise SchedulerStateError("failed to parse runtime state lock claim result")
    return RuntimeStateLockClaim(acquired=acquired, expires_at=expires_at)


def _parse_bool_result(payload: object, *, label: str) -> bool:
    if not isinstance(payload, bool):
        raise SchedulerStateError(f"failed to parse {label} result")
    return payload


def _response_json(response: Any) -> object:
    try:
        return response.json()
    except ValueError as exc:
        raise SchedulerStateError("failed to parse Supabase JSON response") from exc


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    return str(text or "").strip() or f"HTTP {getattr(response, 'status_code', '-')}"


class SupabaseRuntimeStateClient:
    def __init__(
        self,
        config: RuntimeStateConfig,
        *,
        session: Any | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()

    @classmethod
    def from_env(cls) -> SupabaseRuntimeStateClient:
        url = str(os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
        key = str(
            os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        if not url or not key:
            raise SchedulerStateError(
                "SUPABASE_URL and SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY "
                "must be set for scheduled runtime_state access"
            )
        if key.startswith("sb_publishable_"):
            raise SchedulerStateError(
                "SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY must be server-side"
            )
        return cls(RuntimeStateConfig(url=url, service_role_key=key))

    def preflight(self) -> None:
        if not self._config.url or not self._config.service_role_key:
            raise SchedulerStateError("runtime_state Supabase config is incomplete")

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        return {
            "apikey": self._config.service_role_key,
            "authorization": f"Bearer {self._config.service_role_key}",
            **(extra or {}),
        }

    def _runtime_state_url(self, query: dict[str, str] | None = None) -> str:
        base = f"{self._config.url}/rest/v1/runtime_state"
        if not query:
            return base
        return f"{base}?{urlencode(query)}"

    def get_entry(self, key: str) -> RuntimeStateEntry | None:
        query = {
            "select": "state_key,state_payload,expires_at",
            "state_key": f"eq.{key}",
            "limit": "1",
        }
        response = self._session.get(
            self._runtime_state_url(query),
            headers=self._headers({"Accept": "application/json"}),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise SchedulerStateError(
                f"failed to fetch runtime state '{key}': {_response_text(response)}"
            )
        return _parse_runtime_state_entry(_response_json(response))

    def list_entries(self, *, prefix: str, limit: int = 20) -> list[RuntimeStateEntry]:
        normalized_prefix = _require_non_blank(prefix, field_name="prefix")
        query = {
            "select": "state_key,state_payload,expires_at",
            "state_key": f"like.{normalized_prefix}*",
            "order": "expires_at.desc",
            "limit": str(max(1, int(limit))),
        }
        response = self._session.get(
            self._runtime_state_url(query),
            headers=self._headers({"Accept": "application/json"}),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise SchedulerStateError(
                "failed to list runtime state entries "
                f"for prefix '{normalized_prefix}': {_response_text(response)}"
            )
        return _parse_runtime_state_entries(_response_json(response))

    def upsert_marker(
        self,
        *,
        key: str,
        payload: dict[str, object],
        ttl_seconds: int,
        now: dt.datetime | None = None,
    ) -> None:
        base_now = now or _utc_now()
        if base_now.tzinfo is None:
            base_now = base_now.replace(tzinfo=dt.UTC)
        expires_at = base_now + dt.timedelta(seconds=max(1, int(ttl_seconds)))
        body = [
            {
                "state_key": key,
                "state_payload": payload,
                "expires_at": expires_at.isoformat(),
            }
        ]
        response = self._session.post(
            self._runtime_state_url({"on_conflict": "state_key"}),
            headers=self._headers(
                {
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                }
            ),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code not in {200, 201, 204}:
            raise SchedulerStateError(
                f"failed to upsert runtime state '{key}': {_response_text(response)}"
            )

    def claim_lock(
        self,
        *,
        key: str,
        owner_token: str,
        ttl_seconds: int,
        now: dt.datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> RuntimeStateLockClaim:
        normalized_owner_token = _require_non_blank(
            owner_token, field_name="owner_token"
        )
        state_payload = {**(payload or {}), "ownerToken": normalized_owner_token}
        body = {
            "p_state_key": key,
            # Keep p_now for older RPC signatures; lock expiry uses DB now().
            "p_now": None,
            "p_ttl_seconds": max(1, int(ttl_seconds)),
            "p_state_payload": state_payload,
        }
        response = self._session.post(
            f"{self._config.url}/rest/v1/rpc/claim_runtime_state_lock",
            headers=self._headers(
                {"Content-Type": "application/json", "Accept": "application/json"}
            ),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise SchedulerStateError(
                f"failed to claim runtime state lock '{key}': {_response_text(response)}"
            )
        return _parse_claim_result(_response_json(response))

    def release_lock(self, key: str, *, owner_token: str) -> bool:
        normalized_owner_token = _require_non_blank(
            owner_token, field_name="owner_token"
        )
        return self._post_bool_rpc(
            "release_runtime_state_lock",
            {
                "p_state_key": key,
                "p_owner_token": normalized_owner_token,
            },
            label="runtime state lock release",
        )

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool:
        normalized_owner_token = _require_non_blank(
            owner_token, field_name="owner_token"
        )
        return self._post_bool_rpc(
            "renew_runtime_state_lock",
            {
                "p_state_key": key,
                "p_owner_token": normalized_owner_token,
                "p_ttl_seconds": max(1, int(ttl_seconds)),
            },
            label="runtime state lock renew",
        )

    def check_ownership(self, key: str, *, owner_token: str) -> bool:
        normalized_owner_token = _require_non_blank(
            owner_token, field_name="owner_token"
        )
        return self._post_bool_rpc(
            "check_runtime_state_lock_owner",
            {
                "p_state_key": key,
                "p_owner_token": normalized_owner_token,
            },
            label="runtime state lock ownership check",
        )

    def _post_bool_rpc(
        self, rpc_name: str, body: dict[str, object], *, label: str
    ) -> bool:
        response = self._session.post(
            f"{self._config.url}/rest/v1/rpc/{rpc_name}",
            headers=self._headers(
                {"Content-Type": "application/json", "Accept": "application/json"}
            ),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise SchedulerStateError(
                f"failed to call {label}: {_response_text(response)}"
            )
        return _parse_bool_result(_response_json(response), label=label)


__all__ = [
    "RuntimeStateConfig",
    "RuntimeStateEntry",
    "RuntimeStateLockClaim",
    "SchedulerStateError",
    "SupabaseRuntimeStateClient",
    "build_scheduler_state_key",
]
