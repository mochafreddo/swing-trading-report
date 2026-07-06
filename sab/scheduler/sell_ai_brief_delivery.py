from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..report.notification_text import build_sell_ai_brief_telegram_report_text
from ..report.sell_ai_brief_report import validate_sell_ai_brief_artifact
from .generic_state import build_scheduled_state_key
from .state import RuntimeStateEntry, RuntimeStateLockClaim

_SUCCESS_TTL_SECONDS = 48 * 60 * 60
_ATTEMPT_TTL_SECONDS = 48 * 60 * 60
_MAIN_LOCK_TTL_SECONDS = 30 * 60
_NOTIFICATION_CLAIM_TTL_SECONDS = 10 * 60
_ALLOWED_SCOPES = frozenset({"KR", "US", "MIXED"})


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

    def release_lock(self, key: str, *, owner_token: str) -> bool: ...


class _Storage(Protocol):
    def upload_sell_ai_brief(self, report_path: str, *, report_date: str) -> str: ...

    def download_json(self, storage_key: str) -> dict[str, Any]: ...


class _Notifier(Protocol):
    def send_schedule(
        self,
        *,
        report: dict[str, Any],
        storage_key: str,
        text: str,
    ) -> None: ...


@dataclass(frozen=True)
class ScheduledSellAiBriefDeliveryRequest:
    sell_ai_brief_report_path: str
    scope: str = "MIXED"
    session_date: str = ""
    runner_role: str = "local-primary"
    scheduled_tick: str = "manual"
    attempt_id: str | None = None
    run_url: str = ""
    dry_run: bool = False


@dataclass(frozen=True)
class ScheduledSellAiBriefDeliveryResult:
    status: str
    session_date: str
    storage_key: str | None = None


@dataclass(frozen=True)
class _NotificationClaim:
    key: str
    owner_token: str


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "").strip().upper()
    if normalized not in _ALLOWED_SCOPES:
        raise ValueError("scope must be KR, US, or MIXED")
    return normalized


def _state_key(
    kind: str,
    *,
    scope: str,
    session_date: str,
    runner_role: str | None = None,
    attempt_id: str | None = None,
) -> str:
    if kind != "attempt":
        runner_role = None
        attempt_id = None
    return build_scheduled_state_key(
        pipeline="sell",
        kind=kind,
        scope=scope,
        session_date=session_date,
        runner_role=runner_role,
        attempt_id=attempt_id,
    )


def _storage_key(entry: RuntimeStateEntry | None) -> str | None:
    if entry is None:
        return None
    storage_key = str(entry.state_payload.get("storageKey") or "").strip()
    return storage_key or None


def _load_report_date(report_path: str) -> str:
    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sell_ai_brief_report_path must contain a JSON object")
    report_date = str(payload.get("report_date") or "").strip()
    if not report_date:
        raise ValueError("sell AI brief report_date is required")
    return report_date


def _load_local_report(report_path: str) -> dict[str, Any]:
    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sell_ai_brief_report_path must contain a JSON object")
    return payload


class ScheduledSellAiBriefDeliveryRunner:
    def __init__(
        self,
        *,
        state_store: _StateStore,
        storage: _Storage,
        notifier: _Notifier,
        now_fn: Any | None = None,
    ) -> None:
        self._state_store = state_store
        self._storage = storage
        self._notifier = notifier
        self._now_fn = now_fn or (lambda: dt.datetime.now(dt.UTC))

    def run(
        self,
        request: ScheduledSellAiBriefDeliveryRequest,
    ) -> ScheduledSellAiBriefDeliveryResult:
        scope = _normalize_scope(request.scope)
        session_date = str(request.session_date or "").strip() or _load_report_date(
            request.sell_ai_brief_report_path
        )

        if request.dry_run:
            return ScheduledSellAiBriefDeliveryResult(
                status="dry_run",
                session_date=session_date,
            )

        success_key = _state_key("success", scope=scope, session_date=session_date)
        success_entry = self._state_store.get_entry(success_key)
        if success_entry is not None:
            return ScheduledSellAiBriefDeliveryResult(
                status="success_marker_skip",
                session_date=session_date,
                storage_key=_storage_key(success_entry),
            )

        artifact_entry = self._state_store.get_entry(
            _state_key("artifact", scope=scope, session_date=session_date)
        )
        if artifact_entry is not None:
            return self._reconcile_notification(
                request=request,
                scope=scope,
                session_date=session_date,
                artifact_entry=artifact_entry,
            )

        return self._upload_and_deliver(
            request=request,
            scope=scope,
            session_date=session_date,
        )

    def _upload_and_deliver(
        self,
        *,
        request: ScheduledSellAiBriefDeliveryRequest,
        scope: str,
        session_date: str,
    ) -> ScheduledSellAiBriefDeliveryResult:
        now = self._now_fn()
        attempt_id = (
            request.attempt_id or f"{request.scheduled_tick}-{uuid.uuid4().hex}"
        )
        self._state_store.upsert_marker(
            key=_state_key(
                "attempt",
                scope=scope,
                session_date=session_date,
                runner_role=request.runner_role,
                attempt_id=attempt_id,
            ),
            payload={
                "scope": scope,
                "sessionDate": session_date,
                "runnerRole": request.runner_role,
                "scheduledTick": request.scheduled_tick,
                "attemptId": attempt_id,
                "runUrl": request.run_url,
            },
            ttl_seconds=_ATTEMPT_TTL_SECONDS,
            now=now,
        )

        lock_key = _state_key("lock", scope=scope, session_date=session_date)
        owner_token = f"{attempt_id}-main-{uuid.uuid4().hex}"
        claim = self._state_store.claim_lock(
            key=lock_key,
            owner_token=owner_token,
            ttl_seconds=_MAIN_LOCK_TTL_SECONDS,
            now=now,
            payload={
                "scope": scope,
                "sessionDate": session_date,
                "runnerRole": request.runner_role,
                "scheduledTick": request.scheduled_tick,
                "attemptId": attempt_id,
            },
        )
        if not getattr(claim, "acquired", False):
            return ScheduledSellAiBriefDeliveryResult(
                status="lock_held_skip",
                session_date=session_date,
            )

        try:
            if not self._owns_lock(lock_key, owner_token):
                return ScheduledSellAiBriefDeliveryResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )
            try:
                report = _load_local_report(request.sell_ai_brief_report_path)
                validate_sell_ai_brief_artifact(report, now=now)
            except ValueError:
                return ScheduledSellAiBriefDeliveryResult(
                    status="artifact_invalid",
                    session_date=session_date,
                )

            if not self._owns_lock(lock_key, owner_token):
                return ScheduledSellAiBriefDeliveryResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )
            try:
                storage_key = self._storage.upload_sell_ai_brief(
                    request.sell_ai_brief_report_path,
                    report_date=session_date,
                )
            except Exception:
                return ScheduledSellAiBriefDeliveryResult(
                    status="upload_failed",
                    session_date=session_date,
                )

            if not self._owns_lock(lock_key, owner_token):
                return ScheduledSellAiBriefDeliveryResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                    storage_key=storage_key,
                )

            payload: dict[str, object] = {
                "scope": scope,
                "sessionDate": session_date,
                "reportDate": session_date,
                "storageKey": storage_key,
                "runnerRole": request.runner_role,
                "scheduledTick": request.scheduled_tick,
                "attemptId": attempt_id,
                "runUrl": request.run_url,
            }
            self._state_store.upsert_marker(
                key=_state_key("artifact", scope=scope, session_date=session_date),
                payload=payload,
                ttl_seconds=_SUCCESS_TTL_SECONDS,
                now=now,
            )

            notification_status = self._send_notification(
                request=request,
                scope=scope,
                session_date=session_date,
                report=report,
                storage_key=storage_key,
                lock_key=lock_key,
                owner_token=owner_token,
                payload=payload,
            )
            if notification_status != "completed":
                return ScheduledSellAiBriefDeliveryResult(
                    status=notification_status,
                    session_date=session_date,
                    storage_key=storage_key,
                )
            return ScheduledSellAiBriefDeliveryResult(
                status="completed",
                session_date=session_date,
                storage_key=storage_key,
            )
        finally:
            self._state_store.release_lock(lock_key, owner_token=owner_token)

    def _owns_lock(self, lock_key: str, owner_token: str) -> bool:
        entry = self._state_store.get_entry(lock_key)
        if entry is None:
            return False
        return entry.state_payload.get("ownerToken") == owner_token

    def _send_notification(
        self,
        *,
        request: ScheduledSellAiBriefDeliveryRequest,
        scope: str,
        session_date: str,
        report: dict[str, Any],
        storage_key: str,
        lock_key: str,
        owner_token: str,
        payload: dict[str, object],
    ) -> str:
        claim = self._claim_notification(
            request=request,
            scope=scope,
            session_date=session_date,
            storage_key=storage_key,
        )
        if claim is None:
            return "notification_claim_held"

        send_started = False
        delivery_completed = False
        try:
            if not self._owns_lock(lock_key, owner_token):
                return "lock_lost_before_upload"
            text = build_sell_ai_brief_telegram_report_text(
                report=report,
                run_url=request.run_url,
                storage_key=storage_key,
            )
            send_started = True
            self._notifier.send_schedule(
                report=report,
                storage_key=storage_key,
                text=text,
            )
            if not self._owns_lock(lock_key, owner_token):
                return "lock_lost_before_upload"
            try:
                self._state_store.upsert_marker(
                    key=_state_key(
                        "notification:sent",
                        scope=scope,
                        session_date=session_date,
                    ),
                    payload=payload,
                    ttl_seconds=_SUCCESS_TTL_SECONDS,
                )
            except Exception:
                return "notification_sent_marker_failed"
            if not self._owns_lock(lock_key, owner_token):
                return "lock_lost_before_upload"
            self._state_store.upsert_marker(
                key=_state_key("success", scope=scope, session_date=session_date),
                payload=payload,
                ttl_seconds=_SUCCESS_TTL_SECONDS,
            )
            delivery_completed = True
            return "completed"
        finally:
            if not send_started or delivery_completed:
                self._state_store.release_lock(
                    claim.key,
                    owner_token=claim.owner_token,
                )

    def _reconcile_notification(
        self,
        *,
        request: ScheduledSellAiBriefDeliveryRequest,
        scope: str,
        session_date: str,
        artifact_entry: RuntimeStateEntry,
    ) -> ScheduledSellAiBriefDeliveryResult:
        storage_key = _storage_key(artifact_entry)
        if storage_key is None:
            return ScheduledSellAiBriefDeliveryResult(
                status="artifact_marker_invalid",
                session_date=session_date,
            )

        claim = self._claim_notification(
            request=request,
            scope=scope,
            session_date=session_date,
            storage_key=storage_key,
        )
        if claim is None:
            return ScheduledSellAiBriefDeliveryResult(
                status="notification_claim_held",
                session_date=session_date,
                storage_key=storage_key,
            )

        send_started = False
        delivery_completed = False
        try:
            report = self._storage.download_json(storage_key)
            validate_sell_ai_brief_artifact(report, now=self._now_fn())
            text = build_sell_ai_brief_telegram_report_text(
                report=report,
                run_url=request.run_url,
                storage_key=storage_key,
            )
            send_started = True
            self._notifier.send_schedule(
                report=report,
                storage_key=storage_key,
                text=text,
            )
            payload: dict[str, object] = {
                "scope": scope,
                "sessionDate": session_date,
                "storageKey": storage_key,
                "scheduledTick": request.scheduled_tick,
            }
            if request.attempt_id:
                payload["attemptId"] = request.attempt_id
            self._state_store.upsert_marker(
                key=_state_key(
                    "notification:sent",
                    scope=scope,
                    session_date=session_date,
                ),
                payload=payload,
                ttl_seconds=_SUCCESS_TTL_SECONDS,
            )
            self._state_store.upsert_marker(
                key=_state_key("success", scope=scope, session_date=session_date),
                payload=payload,
                ttl_seconds=_SUCCESS_TTL_SECONDS,
            )
            delivery_completed = True
            return ScheduledSellAiBriefDeliveryResult(
                status="notification_reconciled",
                session_date=session_date,
                storage_key=storage_key,
            )
        finally:
            if not send_started or delivery_completed:
                self._state_store.release_lock(
                    claim.key,
                    owner_token=claim.owner_token,
                )

    def _claim_notification(
        self,
        *,
        request: ScheduledSellAiBriefDeliveryRequest,
        scope: str,
        session_date: str,
        storage_key: str,
    ) -> _NotificationClaim | None:
        claim_key = _state_key(
            "notification:claim",
            scope=scope,
            session_date=session_date,
        )
        attempt_token = request.attempt_id or request.scheduled_tick or "manual"
        owner_token = f"{attempt_token}-notification-{uuid.uuid4().hex}"
        claim = self._state_store.claim_lock(
            key=claim_key,
            owner_token=owner_token,
            ttl_seconds=_NOTIFICATION_CLAIM_TTL_SECONDS,
            payload={
                "scope": scope,
                "sessionDate": session_date,
                "runnerRole": request.runner_role,
                "scheduledTick": request.scheduled_tick,
                "storageKey": storage_key,
                "channel": "telegram",
                "notificationType": "schedule",
            },
        )
        if not getattr(claim, "acquired", False):
            return None
        return _NotificationClaim(key=claim_key, owner_token=owner_token)


__all__ = [
    "ScheduledSellAiBriefDeliveryRequest",
    "ScheduledSellAiBriefDeliveryResult",
    "ScheduledSellAiBriefDeliveryRunner",
]
