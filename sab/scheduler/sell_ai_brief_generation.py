from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .generic_state import build_scheduled_state_key
from .sell_ai_brief_delivery import (
    FAILED_SCHEDULED_SELL_AI_BRIEF_DELIVERY_STATUSES,
    ScheduledSellAiBriefDeliveryRequest,
)
from .state import RuntimeStateEntry, RuntimeStateLockClaim

_SUCCESS_TTL_SECONDS = 48 * 60 * 60
_BLOCKED_TTL_SECONDS = 48 * 60 * 60
_BLOCKED_NOTIFICATION_LOCK_TTL_SECONDS = 10 * 60
_GENERATION_LOCK_TTL_SECONDS = 30 * 60
_ALLOWED_SCOPES = frozenset({"MIXED"})
FAILED_SCHEDULED_SELL_AI_BRIEF_GENERATION_STATUSES = (
    frozenset(
        {
            "lock_lost_before_upload",
            "sell_report_failed",
            "sell_ai_brief_failed",
            "quality_gate_failed",
            "upload_failed",
            "delivery_failed",
            "delivery_lock_held",
        }
    )
    | FAILED_SCHEDULED_SELL_AI_BRIEF_DELIVERY_STATUSES
)


class _StateStore(Protocol):
    def get_entry(self, key: str) -> RuntimeStateEntry | None: ...

    def upsert_marker(
        self,
        *,
        key: str,
        payload: dict[str, object],
        ttl_seconds: int,
        now: dt.datetime | None = None,
    ) -> None: ...

    def claim_lock(
        self,
        *,
        key: str,
        owner_token: str,
        ttl_seconds: int,
        now: dt.datetime | None = None,
        payload: dict[str, object] | None = None,
    ) -> RuntimeStateLockClaim: ...

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool: ...

    def check_ownership(self, key: str, *, owner_token: str) -> bool: ...

    def release_lock(self, key: str, *, owner_token: str) -> bool: ...


class _Storage(Protocol):
    def upload_sell(self, report_path: str, *, report_date: str) -> str: ...


class _Notifier(Protocol):
    def send_blocked(self, *, scope: str, session_date: str, reason: str) -> None: ...


@dataclass(frozen=True)
class ScheduledSellAiBriefGenerationRequest:
    scope: str = "MIXED"
    session_date: str = ""
    runner_role: str = "local-primary"
    scheduled_tick: str = "manual"
    attempt_id: str | None = None
    run_url: str = ""
    provider: str | None = None
    model_provider: str | None = "openai"
    model_name: str | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ScheduledSellAiBriefGenerationResult:
    status: str
    session_date: str
    sell_storage_key: str | None = None
    sell_ai_brief_storage_key: str | None = None


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "").strip().upper()
    if normalized not in _ALLOWED_SCOPES:
        raise ValueError("scope must be MIXED")
    return normalized


def _resolve_session_date(value: str, *, now: dt.datetime) -> str:
    normalized = str(value or "").strip()
    if normalized:
        return normalized
    return now.astimezone(dt.timezone(dt.timedelta(hours=9))).date().isoformat()


def _state_key(kind: str, *, scope: str, session_date: str) -> str:
    return build_scheduled_state_key(
        pipeline="sell",
        kind=kind,
        scope=scope,
        session_date=session_date,
    )


def _toss_success_key(*, scope: str, session_date: str) -> str:
    return f"toss-sync:success:{scope}:{session_date}"


def _result_exit_code(result: Any) -> int:
    return int(getattr(result, "exit_code", result if isinstance(result, int) else 1))


def _result_report_path(result: Any) -> str:
    return str(getattr(result, "report_path", "") or "").strip()


def _result_status(result: Any) -> str:
    return str(getattr(result, "status", "") or "").strip().upper()


def _parse_expires_at(value: str) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def _freshness_block_reason(
    entry: RuntimeStateEntry | None,
    *,
    scope: str,
    session_date: str,
    now: dt.datetime,
) -> str | None:
    if entry is None:
        return "toss_freshness_missing"
    payload = entry.state_payload
    status = str(payload.get("status") or "").strip()
    payload_session_date = str(payload.get("sessionDate") or "").strip()
    payload_scope = str(payload.get("scope") or scope).strip().upper()
    if (
        status not in {"applied", "unchanged"}
        or payload_session_date != session_date
        or payload_scope != scope
    ):
        return "toss_freshness_invalid"
    expires_at = _parse_expires_at(entry.expires_at)
    if expires_at is not None and expires_at <= now.astimezone(dt.UTC):
        return "toss_freshness_stale"
    return None


class ScheduledSellAiBriefGenerationRunner:
    def __init__(
        self,
        *,
        state_store: _StateStore,
        storage: _Storage,
        notifier: _Notifier,
        sell_runner: Callable[[ScheduledSellAiBriefGenerationRequest], Any],
        sell_ai_brief_runner: Callable[
            [ScheduledSellAiBriefGenerationRequest, str], Any
        ],
        evaluator: Callable[[str, str], Any],
        delivery_runner: Callable[[Any], Any],
        now_fn: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._state_store = state_store
        self._storage = storage
        self._notifier = notifier
        self._sell_runner = sell_runner
        self._sell_ai_brief_runner = sell_ai_brief_runner
        self._evaluator = evaluator
        self._delivery_runner = delivery_runner
        self._now_fn = now_fn or (lambda: dt.datetime.now(dt.UTC))

    def run(
        self,
        request: ScheduledSellAiBriefGenerationRequest,
    ) -> ScheduledSellAiBriefGenerationResult:
        scope = _normalize_scope(request.scope)
        now = self._now_fn()
        session_date = _resolve_session_date(request.session_date, now=now)

        if request.dry_run:
            return ScheduledSellAiBriefGenerationResult(
                status="dry_run",
                session_date=session_date,
            )

        success_entry = self._state_store.get_entry(
            _state_key("success", scope=scope, session_date=session_date)
        )
        if success_entry is not None:
            return ScheduledSellAiBriefGenerationResult(
                status="success_marker_skip",
                session_date=session_date,
                sell_ai_brief_storage_key=str(
                    success_entry.state_payload.get("storageKey") or ""
                )
                or None,
            )

        freshness_entry = self._state_store.get_entry(
            _toss_success_key(scope=scope, session_date=session_date)
        )
        freshness_block_reason = _freshness_block_reason(
            freshness_entry,
            scope=scope,
            session_date=session_date,
            now=now,
        )
        if freshness_block_reason is not None:
            self._send_blocked_once(
                scope=scope,
                session_date=session_date,
                reason=freshness_block_reason,
                now=now,
                owner_token=(
                    f"{request.attempt_id or request.scheduled_tick}-blocked-"
                    f"{uuid.uuid4().hex}"
                ),
            )
            return ScheduledSellAiBriefGenerationResult(
                status=freshness_block_reason,
                session_date=session_date,
            )

        return self._run_locked_generation(
            request=request,
            scope=scope,
            session_date=session_date,
            now=now,
        )

    def _send_blocked_once(
        self,
        *,
        scope: str,
        session_date: str,
        reason: str,
        now: dt.datetime,
        owner_token: str,
    ) -> None:
        payload: dict[str, object] = {
            "scope": scope,
            "sessionDate": session_date,
            "reason": reason,
            "updatedAt": now.astimezone(dt.UTC).replace(microsecond=0).isoformat(),
        }
        self._state_store.upsert_marker(
            key=_state_key("blocked", scope=scope, session_date=session_date),
            payload=payload,
            ttl_seconds=_BLOCKED_TTL_SECONDS,
            now=now,
        )
        sent_key = _state_key(
            "notification:blocked-sent",
            scope=scope,
            session_date=session_date,
        )
        if self._state_store.get_entry(sent_key) is not None:
            return
        lock_key = _state_key(
            "blocked-notification-lock",
            scope=scope,
            session_date=session_date,
        )
        claim = self._state_store.claim_lock(
            key=lock_key,
            owner_token=owner_token,
            ttl_seconds=_BLOCKED_NOTIFICATION_LOCK_TTL_SECONDS,
            now=now,
            payload={**payload, "notificationType": "blocked"},
        )
        if not getattr(claim, "acquired", False):
            return
        try:
            if self._state_store.get_entry(sent_key) is not None:
                return
            self._notifier.send_blocked(
                scope=scope,
                session_date=session_date,
                reason=reason,
            )
            self._state_store.upsert_marker(
                key=sent_key,
                payload={**payload, "channel": "telegram"},
                ttl_seconds=_BLOCKED_TTL_SECONDS,
                now=now,
            )
        finally:
            self._state_store.release_lock(lock_key, owner_token=owner_token)

    def _run_locked_generation(
        self,
        *,
        request: ScheduledSellAiBriefGenerationRequest,
        scope: str,
        session_date: str,
        now: dt.datetime,
    ) -> ScheduledSellAiBriefGenerationResult:
        lock_key = _state_key(
            "generation-lock",
            scope=scope,
            session_date=session_date,
        )
        owner_token = (
            f"{request.attempt_id or request.scheduled_tick}-generation-"
            f"{uuid.uuid4().hex}"
        )
        claim = self._state_store.claim_lock(
            key=lock_key,
            owner_token=owner_token,
            ttl_seconds=_GENERATION_LOCK_TTL_SECONDS,
            now=now,
            payload={
                "scope": scope,
                "sessionDate": session_date,
                "runnerRole": request.runner_role,
                "scheduledTick": request.scheduled_tick,
                "attemptId": request.attempt_id or "",
            },
        )
        if not getattr(claim, "acquired", False):
            return ScheduledSellAiBriefGenerationResult(
                status="lock_held_skip",
                session_date=session_date,
            )
        try:
            generation_request = replace(
                request,
                scope=scope,
                session_date=session_date,
            )
            if not self._renew_generation_lock(lock_key, owner_token=owner_token):
                return ScheduledSellAiBriefGenerationResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )

            sell_result = self._sell_runner(generation_request)
            sell_report_path = _result_report_path(sell_result)
            if _result_exit_code(sell_result) != 0 or not sell_report_path:
                return ScheduledSellAiBriefGenerationResult(
                    status="sell_report_failed",
                    session_date=session_date,
                )

            if not self._renew_generation_lock(lock_key, owner_token=owner_token):
                return ScheduledSellAiBriefGenerationResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )

            brief_result = self._sell_ai_brief_runner(
                generation_request,
                sell_report_path,
            )
            sell_ai_brief_report_path = _result_report_path(brief_result)
            if _result_exit_code(brief_result) != 0 or not sell_ai_brief_report_path:
                return ScheduledSellAiBriefGenerationResult(
                    status="sell_ai_brief_failed",
                    session_date=session_date,
                )

            if not self._renew_generation_lock(lock_key, owner_token=owner_token):
                return ScheduledSellAiBriefGenerationResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )

            eval_result = self._evaluator(
                sell_report_path,
                sell_ai_brief_report_path,
            )
            quality_status = _result_status(eval_result)
            if quality_status == "FAIL":
                return ScheduledSellAiBriefGenerationResult(
                    status="quality_gate_failed",
                    session_date=session_date,
                )

            if not self._renew_generation_lock(lock_key, owner_token=owner_token):
                return ScheduledSellAiBriefGenerationResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )
            try:
                sell_storage_key = str(
                    self._storage.upload_sell(
                        sell_report_path,
                        report_date=session_date,
                    )
                    or ""
                ).strip()
            except Exception:
                return ScheduledSellAiBriefGenerationResult(
                    status="upload_failed",
                    session_date=session_date,
                )
            if not sell_storage_key:
                return ScheduledSellAiBriefGenerationResult(
                    status="upload_failed",
                    session_date=session_date,
                )

            delivery_result = self._delivery_runner(
                ScheduledSellAiBriefDeliveryRequest(
                    sell_ai_brief_report_path=sell_ai_brief_report_path,
                    scope=scope,
                    session_date=session_date,
                    runner_role=request.runner_role,
                    scheduled_tick=request.scheduled_tick,
                    attempt_id=request.attempt_id,
                    run_url=request.run_url,
                )
            )
            delivery_status = str(getattr(delivery_result, "status", "") or "")
            if delivery_status not in {
                "completed",
                "notification_reconciled",
                "completion_repaired",
                "success_marker_skip",
            }:
                if delivery_status == "lock_held_skip":
                    delivery_status = "delivery_lock_held"
                elif (
                    not delivery_status
                    or delivery_status
                    not in FAILED_SCHEDULED_SELL_AI_BRIEF_DELIVERY_STATUSES
                ):
                    delivery_status = "delivery_failed"
                return ScheduledSellAiBriefGenerationResult(
                    status=delivery_status,
                    session_date=session_date,
                    sell_storage_key=sell_storage_key,
                )
            sell_ai_brief_storage_key = str(
                getattr(delivery_result, "storage_key", "") or ""
            ).strip()
            generation_payload: dict[str, object] = {
                "scope": scope,
                "sessionDate": session_date,
                "sellStorageKey": sell_storage_key,
                "sellAiBriefStorageKey": sell_ai_brief_storage_key,
                "qualityStatus": quality_status or "PASS",
                "runnerRole": request.runner_role,
                "scheduledTick": request.scheduled_tick,
                "attemptId": request.attempt_id or "",
                "runUrl": request.run_url,
            }
            self._state_store.upsert_marker(
                key=_state_key("generation", scope=scope, session_date=session_date),
                payload=generation_payload,
                ttl_seconds=_SUCCESS_TTL_SECONDS,
                now=now,
            )
            status = "completed"
            if quality_status == "WARN":
                status = "completed_review_required"
                self._state_store.upsert_marker(
                    key=_state_key(
                        "review-required",
                        scope=scope,
                        session_date=session_date,
                    ),
                    payload={**generation_payload, "reviewRequired": True},
                    ttl_seconds=_SUCCESS_TTL_SECONDS,
                    now=now,
                )
            return ScheduledSellAiBriefGenerationResult(
                status=status,
                session_date=session_date,
                sell_storage_key=sell_storage_key,
                sell_ai_brief_storage_key=sell_ai_brief_storage_key or None,
            )
        finally:
            self._state_store.release_lock(lock_key, owner_token=owner_token)

    def _renew_generation_lock(self, lock_key: str, *, owner_token: str) -> bool:
        return self._state_store.renew_lock(
            lock_key,
            owner_token=owner_token,
            ttl_seconds=_GENERATION_LOCK_TTL_SECONDS,
        ) and self._state_store.check_ownership(
            lock_key,
            owner_token=owner_token,
        )


__all__ = [
    "FAILED_SCHEDULED_SELL_AI_BRIEF_GENERATION_STATUSES",
    "ScheduledSellAiBriefGenerationRequest",
    "ScheduledSellAiBriefGenerationResult",
    "ScheduledSellAiBriefGenerationRunner",
]
