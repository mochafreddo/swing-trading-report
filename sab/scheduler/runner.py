from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import threading
import unicodedata
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import Protocol
from urllib.parse import quote, urlencode, urlparse
from zoneinfo import ZoneInfo

import requests  # type: ignore[import-untyped]

from .. import ai_brief_url_safety as url_safety
from ..ai_brief import run_ai_brief
from ..ai_brief_eval import evaluate_ai_brief_recommendation_report
from ..ai_brief_eval_common import parse_iso_offset_datetime
from ..ai_brief_source_chain import parse_source_provider_chain
from ..ai_brief_sources import (
    SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
    SOURCE_PROVIDER_BENZINGA_NEWS,
    SOURCE_PROVIDER_FINNHUB,
    SOURCE_PROVIDER_HTTP_JSON,
    SOURCE_PROVIDER_MARKETAUX_NEWS,
    SOURCE_PROVIDER_NAVER_NEWS,
    SOURCE_PROVIDER_NONE,
    SOURCE_PROVIDER_POLYGON_NEWS,
)
from ..data.trading_sessions import is_trading_session
from ..entry import run_entry
from ..env_loader import suppress_config_env_keys
from ..report.ai_brief_report import validate_ai_brief_artifact
from ..report.ai_brief_skip_report import (
    AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
    write_ai_brief_skip_report,
)
from ..report.notification_text import (
    build_ai_brief_slack_summary_text,
    build_ai_brief_telegram_report_text,
    split_telegram_message_text,
)
from ..report.session_state import resolve_run_session_state_map
from ..report.supabase_storage import (
    SupabaseStorageConfig,
    _auth_headers,
    _load_storage_config,
    suppress_report_uploads,
    upload_report_artifact,
)
from ..scan import run_scan
from .holdings import (
    SupabaseHoldingsExportConfig,
    export_active_holdings_snapshot,
)
from .schedule_policy import (
    is_within_role_window as _policy_is_within_role_window,
)
from .schedule_policy import (
    market_zone,
    require_role_window,
    role_deadline_at,
    role_window,
    role_window_end_grace,
)
from .state import (
    RuntimeStateEntry,
    RuntimeStateLockClaim,
    SchedulerStateError,
    SupabaseRuntimeStateClient,
    build_scheduler_state_key,
)

_LOCK_TTL_SECONDS = 25 * 60
_LOCK_RENEW_INTERVAL_SECONDS = 5 * 60
_NOTIFICATION_CLAIM_TTL_SECONDS = 10 * 60
_LATE_ALERT_CLAIM_TTL_SECONDS = 10 * 60
_SKIP_ARTIFACT_CLAIM_TTL_SECONDS = 10 * 60
_SUCCESS_TTL_SECONDS = 48 * 60 * 60
_ATTEMPT_TTL_SECONDS = 7 * 24 * 60 * 60
_PIPELINE_RUNNER_ROLES = {"local-primary", "local-retry", "github-fallback"}
_NON_PIPELINE_RUNNER_ROLES = {"monitor-only", "cutoff-alert"}
_SUPPORTED_RUNNER_ROLES = _PIPELINE_RUNNER_ROLES | _NON_PIPELINE_RUNNER_ROLES
_SCHEDULED_PIPELINE_SUPPRESSED_ENV_KEYS = ("HOLDINGS_FILE",)
_SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE = "none"
_SCHEDULED_SOURCE_API_URL_ORIGIN_NONE = "none"
_SCHEDULED_SOURCE_PROVIDER_ORIGIN_REQUEST = "request"
_SCHEDULED_SOURCE_PROVIDER_ORIGIN_ENV_MARKET = "env_market"
_SCHEDULED_SOURCE_PROVIDER_ORIGIN_ENV_GLOBAL = "env_global"
_SCHEDULED_SOURCE_PROVIDER_ORIGIN_API_URL_MARKET = "api_url_market"
_SCHEDULED_SOURCE_PROVIDER_ORIGIN_API_URL_GLOBAL = "api_url_global"
_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE = "none"
_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_MARKET = "env_market"
_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_GLOBAL = "env_global"
_SCHEDULED_SOURCE_API_URL_ORIGIN_ENV_MARKET = "env_market"
_SCHEDULED_SOURCE_API_URL_ORIGIN_ENV_GLOBAL = "env_global"
_SCHEDULED_SOURCE_API_URL_ALLOWED_SCHEMES = frozenset({"https"})
_ALLOWED_SCHEDULED_SOURCE_PROVIDERS = frozenset(
    {
        SOURCE_PROVIDER_NONE,
        SOURCE_PROVIDER_HTTP_JSON,
        SOURCE_PROVIDER_FINNHUB,
        SOURCE_PROVIDER_POLYGON_NEWS,
        SOURCE_PROVIDER_ALPHA_VANTAGE_NEWS,
        SOURCE_PROVIDER_MARKETAUX_NEWS,
        SOURCE_PROVIDER_BENZINGA_NEWS,
        SOURCE_PROVIDER_NAVER_NEWS,
    }
)
_FAILED_STATUSES = {
    "attempt_marker_failed",
    "guard_failed",
    "guard_failed_before_upload",
    "guard_failed_before_notification",
    "pipeline_failed",
    "upload_failed",
    "artifact_marker_failed",
    "artifact_marker_invalid",
    "entry_failure_artifact_claim_held",
    "late_alert_send_failed",
    "late_alert_sent_marker_failed",
    "lock_lost_before_upload",
    "skip_artifact_upload_failed",
    "source_config_invalid",
    "unsupported_runner_role",
}
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GuardSnapshot:
    trading_session: bool
    session_state: str
    session_date: str
    local_time: str


@dataclass(frozen=True)
class ScheduledAiBriefRequest:
    market: str
    schedule_role: str
    runner_role: str
    scheduled_tick: str
    attempt_id: str | None = None
    dry_run: bool = False
    run_url: str = ""
    source_provider: str | None = None
    model_provider: str = "openai"


@dataclass(frozen=True)
class ScheduledAiBriefResult:
    status: str
    session_date: str | None = None
    storage_key: str | None = None


@dataclass(frozen=True)
class ScheduledPipelineResult:
    ai_brief_report_path: str


@dataclass(frozen=True)
class _MainLockLease:
    lock_key: str
    owner_token: str


@dataclass(frozen=True)
class _NotificationClaimLease:
    claim_key: str
    owner_token: str


@dataclass(frozen=True)
class _ScheduledRunContext:
    now: dt.datetime
    market: str
    schedule_role: str
    runner_role: str
    guard: GuardSnapshot
    session_date: str
    attempt_id: str
    model_deadline_at: dt.datetime | None


@dataclass(frozen=True)
class _ScheduledSourceContext:
    source_provider: str | None
    source_provider_origin: str
    source_provider_chain: tuple[str, ...] | None
    source_provider_chain_origin: str
    source_api_url: str | None
    source_api_url_origin: str
    source_api_url_configured: bool


class _ScheduledSourceConfigError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        source_context: _ScheduledSourceContext,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.source_context = source_context


class _SkipArtifactClaimHeld(RuntimeError):
    """Raised when another runner is already persisting the skip artifact."""


class SchedulerStateStore(Protocol):
    def preflight(self) -> None: ...

    def get_entry(self, key: str) -> RuntimeStateEntry | None: ...

    def list_entries(
        self, *, prefix: str, limit: int = 20
    ) -> list[RuntimeStateEntry]: ...

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

    def renew_lock(self, key: str, *, owner_token: str, ttl_seconds: int) -> bool: ...

    def check_ownership(self, key: str, *, owner_token: str) -> bool: ...


class SchedulerPipeline(Protocol):
    def run(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
        model_deadline_remaining_seconds: float | None = None,
        model_deadline_at: dt.datetime | None = None,
        source_api_url: str | None = None,
        source_provider_chain: tuple[str, ...] | None = None,
    ) -> ScheduledPipelineResult: ...


class SchedulerStorage(Protocol):
    def upload_ai_brief(self, report_path: str, *, report_date: str) -> str: ...

    def upload_entry_report(self, report_path: str, *, report_date: str) -> str: ...

    def upload_ai_brief_skip(self, report_path: str, *, report_date: str) -> str: ...

    def download_json(self, storage_key: str) -> dict[str, object]: ...

    def list_ai_brief_report_index(self, *, report_date: str) -> list[str]: ...


class SchedulerNotifier(Protocol):
    def require_telegram(self) -> None: ...

    def send_schedule(self, *, report: dict[str, object], storage_key: str) -> None: ...

    def send_late_alert(self, *, reason: str, context: dict[str, object]) -> None: ...


def _normalize_market(market: str) -> str:
    normalized = str(market or "").strip().upper()
    if normalized not in {"KR", "US"}:
        raise ValueError("market must be KR or US")
    return normalized


def _normalize_role(role: str, *, field_name: str) -> str:
    normalized = str(role or "").strip().lower()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_source_provider(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _scheduled_env_source_provider_candidate(*, market: str) -> tuple[str | None, str]:
    market_provider = _normalize_optional_source_provider(
        _optional_env(f"AI_BRIEF_SOURCE_PROVIDER_{market}")
    )
    if market_provider:
        return market_provider, _SCHEDULED_SOURCE_PROVIDER_ORIGIN_ENV_MARKET

    global_provider = _normalize_optional_source_provider(
        _optional_env("AI_BRIEF_SOURCE_PROVIDER")
    )
    if global_provider:
        return global_provider, _SCHEDULED_SOURCE_PROVIDER_ORIGIN_ENV_GLOBAL

    return None, _SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE


def _scheduled_source_provider_chain_candidate(
    *,
    market: str,
) -> tuple[tuple[str, ...] | None, str]:
    market_chain = _optional_env(f"AI_BRIEF_SOURCE_PROVIDER_CHAIN_{market}")
    if market_chain:
        return (
            _parse_scheduled_source_provider_chain(
                market_chain,
                origin=_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_MARKET,
            ),
            _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_MARKET,
        )

    global_chain = _optional_env("AI_BRIEF_SOURCE_PROVIDER_CHAIN")
    if global_chain:
        return (
            _parse_scheduled_source_provider_chain(
                global_chain,
                origin=_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_GLOBAL,
            ),
            _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_GLOBAL,
        )

    return None, _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE


def _parse_scheduled_source_provider_chain(
    value: str,
    *,
    origin: str,
) -> tuple[str, ...]:
    try:
        return parse_source_provider_chain(value)
    except ValueError as exc:
        raise _ScheduledSourceConfigError(
            "scheduled AI brief source provider chain is invalid",
            error_code="invalid_source_provider_chain",
            source_context=_ScheduledSourceContext(
                source_provider=None,
                source_provider_origin=_SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE,
                source_provider_chain=("unsupported",),
                source_provider_chain_origin=origin,
                source_api_url=None,
                source_api_url_origin=_SCHEDULED_SOURCE_API_URL_ORIGIN_NONE,
                source_api_url_configured=False,
            ),
        ) from exc


def _scheduled_source_api_url_candidate(*, market: str) -> tuple[str | None, str]:
    market_api_url = _optional_env(f"AI_BRIEF_SOURCE_API_URL_{market}")
    if market_api_url:
        return market_api_url, _SCHEDULED_SOURCE_API_URL_ORIGIN_ENV_MARKET

    global_api_url = _optional_env("AI_BRIEF_SOURCE_API_URL")
    if global_api_url:
        return global_api_url, _SCHEDULED_SOURCE_API_URL_ORIGIN_ENV_GLOBAL

    return None, _SCHEDULED_SOURCE_API_URL_ORIGIN_NONE


def _source_provider_origin_for_api_url_origin(source_api_url_origin: str) -> str:
    if source_api_url_origin == _SCHEDULED_SOURCE_API_URL_ORIGIN_ENV_MARKET:
        return _SCHEDULED_SOURCE_PROVIDER_ORIGIN_API_URL_MARKET
    if source_api_url_origin == _SCHEDULED_SOURCE_API_URL_ORIGIN_ENV_GLOBAL:
        return _SCHEDULED_SOURCE_PROVIDER_ORIGIN_API_URL_GLOBAL
    return _SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE


def _validate_scheduled_source_api_url(value: str) -> None:
    text = url_safety.validate_url(
        value,
        field_name="scheduled source API URL",
        allowed_schemes=_SCHEDULED_SOURCE_API_URL_ALLOWED_SCHEMES,
    )
    parsed = urlparse(text)
    url_safety.validated_url_port(parsed, field_name="scheduled source API URL")
    aliases = url_safety.hostname_aliases(parsed.hostname or "")
    if any(url_safety.is_blocked_hostname(alias) for alias in aliases):
        raise ValueError(
            "scheduled source API URL must not target local or private hosts"
        )


def _resolve_scheduled_source_context(
    *,
    market: str,
    source_provider: str | None,
) -> _ScheduledSourceContext:
    request_provider = _normalize_optional_source_provider(source_provider)
    resolved_api_url, api_url_origin = _scheduled_source_api_url_candidate(
        market=market
    )

    if request_provider:
        source_context = _ScheduledSourceContext(
            source_provider=request_provider,
            source_provider_origin=_SCHEDULED_SOURCE_PROVIDER_ORIGIN_REQUEST,
            source_provider_chain=None,
            source_provider_chain_origin=_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE,
            source_api_url=resolved_api_url
            if request_provider == SOURCE_PROVIDER_HTTP_JSON
            else None,
            source_api_url_origin=api_url_origin
            if request_provider == SOURCE_PROVIDER_HTTP_JSON
            else _SCHEDULED_SOURCE_API_URL_ORIGIN_NONE,
            source_api_url_configured=bool(resolved_api_url)
            if request_provider == SOURCE_PROVIDER_HTTP_JSON
            else False,
        )
        _validate_scheduled_source_context(source_context)
        return source_context

    resolved_chain, chain_origin = _scheduled_source_provider_chain_candidate(
        market=market
    )
    if resolved_chain:
        source_context = _ScheduledSourceContext(
            source_provider=None,
            source_provider_origin=_SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE,
            source_provider_chain=resolved_chain,
            source_provider_chain_origin=chain_origin,
            source_api_url=resolved_api_url
            if SOURCE_PROVIDER_HTTP_JSON in resolved_chain
            else None,
            source_api_url_origin=api_url_origin
            if SOURCE_PROVIDER_HTTP_JSON in resolved_chain
            else _SCHEDULED_SOURCE_API_URL_ORIGIN_NONE,
            source_api_url_configured=bool(resolved_api_url)
            if SOURCE_PROVIDER_HTTP_JSON in resolved_chain
            else False,
        )
        _validate_scheduled_source_context(source_context)
        return source_context

    resolved_provider, provider_origin = _scheduled_env_source_provider_candidate(
        market=market
    )

    if resolved_provider:
        source_context = _ScheduledSourceContext(
            source_provider=resolved_provider,
            source_provider_origin=provider_origin,
            source_provider_chain=None,
            source_provider_chain_origin=_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE,
            source_api_url=resolved_api_url
            if resolved_provider == SOURCE_PROVIDER_HTTP_JSON
            else None,
            source_api_url_origin=api_url_origin
            if resolved_provider == SOURCE_PROVIDER_HTTP_JSON
            else _SCHEDULED_SOURCE_API_URL_ORIGIN_NONE,
            source_api_url_configured=bool(resolved_api_url)
            if resolved_provider == SOURCE_PROVIDER_HTTP_JSON
            else False,
        )
        _validate_scheduled_source_context(source_context)
        return source_context

    if resolved_api_url:
        source_context = _ScheduledSourceContext(
            source_provider=SOURCE_PROVIDER_HTTP_JSON,
            source_provider_origin=_source_provider_origin_for_api_url_origin(
                api_url_origin
            ),
            source_provider_chain=None,
            source_provider_chain_origin=_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE,
            source_api_url=resolved_api_url,
            source_api_url_origin=api_url_origin,
            source_api_url_configured=True,
        )
        _validate_scheduled_source_context(source_context)
        return source_context

    return _ScheduledSourceContext(
        source_provider=None,
        source_provider_origin=_SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE,
        source_provider_chain=None,
        source_provider_chain_origin=_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE,
        source_api_url=None,
        source_api_url_origin=_SCHEDULED_SOURCE_API_URL_ORIGIN_NONE,
        source_api_url_configured=False,
    )


def _validate_scheduled_source_context(
    source_context: _ScheduledSourceContext,
) -> None:
    provider = source_context.source_provider
    chain = source_context.source_provider_chain
    if chain is not None:
        if set(chain) - _ALLOWED_SCHEDULED_SOURCE_PROVIDERS:
            raise _ScheduledSourceConfigError(
                "unsupported scheduled AI brief source provider",
                error_code="unsupported_source_provider",
                source_context=source_context,
            )
        if SOURCE_PROVIDER_HTTP_JSON not in chain:
            return
        if not source_context.source_api_url:
            raise _ScheduledSourceConfigError(
                "scheduled source provider chain with http-json requires source API URL",
                error_code="missing_source_api_url",
                source_context=source_context,
            )
        try:
            _validate_scheduled_source_api_url(source_context.source_api_url)
        except ValueError as exc:
            raise _ScheduledSourceConfigError(
                "scheduled source API URL is invalid",
                error_code="invalid_source_api_url",
                source_context=source_context,
            ) from exc
        return

    if provider not in _ALLOWED_SCHEDULED_SOURCE_PROVIDERS:
        raise _ScheduledSourceConfigError(
            "unsupported scheduled AI brief source provider",
            error_code="unsupported_source_provider",
            source_context=source_context,
        )
    if provider != SOURCE_PROVIDER_HTTP_JSON:
        return
    if not source_context.source_api_url:
        raise _ScheduledSourceConfigError(
            "scheduled source_provider=http-json requires source API URL",
            error_code="missing_source_api_url",
            source_context=source_context,
        )
    try:
        _validate_scheduled_source_api_url(source_context.source_api_url)
    except ValueError as exc:
        raise _ScheduledSourceConfigError(
            "scheduled source API URL is invalid",
            error_code="invalid_source_api_url",
            source_context=source_context,
        ) from exc


def _scheduled_source_provider_for_log(
    source_context: _ScheduledSourceContext,
) -> str:
    provider = source_context.source_provider
    if not provider:
        return SOURCE_PROVIDER_NONE
    if provider not in _ALLOWED_SCHEDULED_SOURCE_PROVIDERS:
        return "unsupported"
    return provider


def _scheduled_source_provider_chain_for_log(
    source_context: _ScheduledSourceContext,
) -> str:
    chain = source_context.source_provider_chain
    if not chain:
        return SOURCE_PROVIDER_NONE
    if set(chain) - _ALLOWED_SCHEDULED_SOURCE_PROVIDERS:
        return "unsupported"
    return ",".join(chain)


def _local_zone(market: str) -> ZoneInfo:
    return market_zone(market)


def _is_within_role_window(
    *, market: str, schedule_role: str, now: dt.datetime
) -> bool:
    return _policy_is_within_role_window(
        market=market,
        schedule_role=schedule_role,
        now=now,
    )


def _guard_allows_pipeline(guard: GuardSnapshot) -> bool:
    return guard.trading_session and guard.session_state == "PRE_OPEN"


def _guard_context(
    *, market: str, session_date: str, guard: GuardSnapshot
) -> dict[str, object]:
    return {
        "market": market,
        "sessionDate": session_date,
        "sessionState": guard.session_state,
        "tradingSession": guard.trading_session,
        "localTime": guard.local_time,
    }


def _with_alert_run_context(
    context: dict[str, object],
    *,
    schedule_role: str | None = None,
    runner_role: str | None = None,
    attempt_id: str | None = None,
) -> dict[str, object]:
    enriched = dict(context)
    if schedule_role is not None:
        enriched["scheduleRole"] = schedule_role
    if runner_role is not None:
        enriched["runnerRole"] = runner_role
    if attempt_id is not None:
        enriched["attemptId"] = attempt_id
    return enriched


def _late_alert_sent_key(*, market: str, session_date: str, reason: str) -> str:
    return (
        build_scheduler_state_key(
            kind="late-alert:sent",
            market=market,
            session_date=session_date,
        )
        + f":{reason}"
    )


def _scheduled_entry_failure_artifact_key(*, market: str, session_date: str) -> str:
    return build_scheduler_state_key(
        kind="entry-failure-artifact",
        market=market,
        session_date=session_date,
    )


class _EntryFailureArtifactClaimHeld:
    pass


_ENTRY_FAILURE_ARTIFACT_CLAIM_HELD = _EntryFailureArtifactClaimHeld()


def _runner_origin(runner_role: str) -> str:
    if runner_role.startswith("local-"):
        return "local"
    if runner_role.startswith("github-"):
        return "github"
    return "monitor"


def _attempt_prefix(
    *, market: str, session_date: str, runner_role: str | None = None
) -> str:
    base = f"scheduled-ai-brief:attempt:{market}:{session_date}"
    return f"{base}:{runner_role}:" if runner_role else f"{base}:"


def _runtime_state_storage_key(entry: RuntimeStateEntry | None) -> str | None:
    if entry is None:
        return None
    storage_key = str(entry.state_payload.get("storageKey") or "").strip()
    return storage_key or None


def _runtime_state_entry_report_storage_key(
    entry: RuntimeStateEntry | None,
) -> str | None:
    if entry is None:
        return None
    storage_key = str(
        entry.state_payload.get("entryReportStorageKey")
        or entry.state_payload.get("storageKey")
        or ""
    ).strip()
    return storage_key or None


def _parse_artifact_generated_at(value: object) -> dt.datetime | None:
    try:
        return parse_iso_offset_datetime(value, field_name="generated_at")
    except ValueError:
        return None


def _is_generated_during_scheduled_window(
    *, market: str, session_date: str, generated_at: object
) -> bool:
    parsed = _parse_artifact_generated_at(generated_at)
    if parsed is None:
        return False
    local_generated_at = parsed.astimezone(_local_zone(market))
    if local_generated_at.date().isoformat() != session_date:
        return False

    primary_window = require_role_window(market, "local-primary")
    cutoff_window = require_role_window(market, "cutoff-alert")
    fallback_window = role_window(market, "github-fallback")
    start_at = dt.datetime.combine(
        local_generated_at.date(),
        primary_window.start,
        tzinfo=local_generated_at.tzinfo,
    )
    end_at = dt.datetime.combine(
        local_generated_at.date(),
        cutoff_window.start,
        tzinfo=local_generated_at.tzinfo,
    )
    if fallback_window is not None:
        fallback_end_at = dt.datetime.combine(
            local_generated_at.date(),
            fallback_window.end,
            tzinfo=local_generated_at.tzinfo,
        ) + role_window_end_grace(market, "github-fallback")
        end_at = max(end_at, fallback_end_at)
    return start_at <= local_generated_at < end_at


def _is_scheduled_artifact_for_session(
    report: dict[str, object],
    *,
    market: str,
    session_date: str,
    report_date: str,
) -> bool:
    if str(report.get("market") or "").strip().upper() != market:
        return False
    if str(report.get("report_date") or "").strip() != report_date:
        return False
    return _is_generated_during_scheduled_window(
        market=market,
        session_date=session_date,
        generated_at=report.get("generated_at"),
    )


def build_attempt_id(
    *,
    scheduled_tick: str,
    started_at: dt.datetime,
    suffix: str | None = None,
) -> str:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=dt.UTC)
    utc_started_at = started_at.astimezone(dt.UTC)
    base = f"{scheduled_tick}-{utc_started_at.strftime('%Y%m%dT%H%M%SZ')}"
    return f"{base}-{suffix}" if suffix else base


def _default_guard_snapshot(market: str, now: dt.datetime) -> GuardSnapshot:
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    zone = _local_zone(market)
    local_now = now.astimezone(zone)
    session_state = resolve_run_session_state_map(
        markets=[market],
        data_dir="data",
        now=now,
    ).get(market, "AFTER_CLOSE")
    trading_session = is_trading_session(
        local_now.date(),
        market=market,
        data_dir="data",
    )
    return GuardSnapshot(
        trading_session=trading_session,
        session_state=session_state,
        session_date=local_now.date().isoformat(),
        local_time=local_now.isoformat(),
    )


def _state_payload(
    *,
    market: str,
    session_date: str,
    schedule_role: str,
    runner_role: str,
    scheduled_tick: str,
    attempt_id: str,
    run_url: str,
    runner: str,
    started_at: dt.datetime,
) -> dict[str, object]:
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=dt.UTC)
    return {
        "market": market,
        "sessionDate": session_date,
        "scheduleRole": schedule_role,
        "runnerRole": runner_role,
        "runner": runner,
        "scheduledTick": scheduled_tick,
        "attemptId": attempt_id,
        "runUrl": run_url,
        "startedAt": started_at.astimezone(dt.UTC).replace(microsecond=0).isoformat(),
    }


class _MainLockRenewer:
    def __init__(
        self,
        *,
        state_store: SchedulerStateStore,
        lock_key: str,
        owner_token: str,
        ttl_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._state_store = state_store
        self._lock_key = lock_key
        self._owner_token = owner_token
        self._ttl_seconds = ttl_seconds
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._interval_seconds <= 0:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="sab-scheduled-ai-brief-lock-renewer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                renewed = self._state_store.renew_lock(
                    self._lock_key,
                    owner_token=self._owner_token,
                    ttl_seconds=self._ttl_seconds,
                )
            except Exception as exc:
                _LOGGER.warning(
                    "scheduled AI brief main lock renewal failed: %s",
                    exc,
                )
                continue
            if not renewed:
                _LOGGER.warning("scheduled AI brief main lock renewal lost ownership")
                return


class ScheduledAiBriefRunner:
    def __init__(
        self,
        *,
        state_store: SchedulerStateStore,
        pipeline: SchedulerPipeline,
        storage: SchedulerStorage,
        notifier: SchedulerNotifier,
        now_fn: Callable[[], dt.datetime] | None = None,
        guard_resolver: Callable[[str, dt.datetime], GuardSnapshot] | None = None,
        lock_renew_interval_seconds: float | None = None,
    ) -> None:
        self._state_store = state_store
        self._pipeline = pipeline
        self._storage = storage
        self._notifier = notifier
        self._now_fn = now_fn or (lambda: dt.datetime.now(dt.UTC))
        self._guard_resolver = guard_resolver or _default_guard_snapshot
        self._lock_renew_interval_seconds = (
            _LOCK_RENEW_INTERVAL_SECONDS
            if lock_renew_interval_seconds is None
            else lock_renew_interval_seconds
        )

    def _resolve_run_context(
        self, request: ScheduledAiBriefRequest
    ) -> _ScheduledRunContext | ScheduledAiBriefResult:
        now = self._now_fn()
        market = _normalize_market(request.market)
        schedule_role = _normalize_role(
            request.schedule_role, field_name="schedule_role"
        )
        runner_role = _normalize_role(request.runner_role, field_name="runner_role")
        if not _is_within_role_window(
            market=market, schedule_role=schedule_role, now=now
        ):
            return ScheduledAiBriefResult(status="off_window_noop")

        guard = self._guard_resolver(market, now)
        session_date = guard.session_date
        if runner_role not in _SUPPORTED_RUNNER_ROLES:
            _LOGGER.error(
                "scheduled AI brief unsupported runner role "
                "market=%s schedule_role=%s runner_role=%s",
                market,
                schedule_role,
                runner_role,
            )
            return ScheduledAiBriefResult(
                status="unsupported_runner_role",
                session_date=session_date,
            )
        attempt_id = request.attempt_id or build_attempt_id(
            scheduled_tick=request.scheduled_tick,
            started_at=now,
            suffix=f"pid{os.getpid()}-{uuid.uuid4().hex[:8]}",
        )
        deadline_at = role_deadline_at(
            market=market, schedule_role=schedule_role, now=now
        )
        return _ScheduledRunContext(
            now=now,
            market=market,
            schedule_role=schedule_role,
            runner_role=runner_role,
            guard=guard,
            session_date=session_date,
            attempt_id=attempt_id,
            model_deadline_at=deadline_at,
        )

    def run(self, request: ScheduledAiBriefRequest) -> ScheduledAiBriefResult:
        run_context = self._resolve_run_context(request)
        if isinstance(run_context, ScheduledAiBriefResult):
            return run_context

        now = run_context.now
        market = run_context.market
        schedule_role = run_context.schedule_role
        runner_role = run_context.runner_role
        guard = run_context.guard
        session_date = run_context.session_date
        attempt_id = run_context.attempt_id
        model_deadline_at = run_context.model_deadline_at

        self._state_store.preflight()
        if request.dry_run:
            return ScheduledAiBriefResult(status="dry_run", session_date=session_date)
        if not guard.trading_session:
            return self._handle_non_trading_guard(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                guard=guard,
                run_url=request.run_url,
            )

        if runner_role in _PIPELINE_RUNNER_ROLES:
            attempt_result = self._record_pipeline_attempt_marker(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                scheduled_tick=request.scheduled_tick,
                attempt_id=attempt_id,
                run_url=request.run_url,
                now=now,
            )
            if attempt_result is not None:
                return attempt_result

        success_key = build_scheduler_state_key(
            kind="success", market=market, session_date=session_date
        )
        if self._state_store.get_entry(success_key) is not None:
            return ScheduledAiBriefResult(
                status="success_marker_skip",
                session_date=session_date,
            )

        artifact_key = build_scheduler_state_key(
            kind="artifact", market=market, session_date=session_date
        )
        artifact_result = self._reconcile_existing_or_repaired_artifact(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            run_url=request.run_url,
            now=now,
            artifact_key=artifact_key,
        )
        if artifact_result is not None:
            return artifact_result

        return self._dispatch_ready_run(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            run_url=request.run_url,
            source_provider=request.source_provider,
            model_provider=request.model_provider,
            guard=guard,
            artifact_key=artifact_key,
            now=now,
            model_deadline_at=model_deadline_at,
        )

    def _claim_main_lock(
        self,
        *,
        market: str,
        session_date: str,
        runner_role: str,
        attempt_id: str,
        now: dt.datetime,
    ) -> _MainLockLease | ScheduledAiBriefResult:
        owner_token = f"{attempt_id}-{uuid.uuid4().hex}"
        lock_key = build_scheduler_state_key(
            kind="lock", market=market, session_date=session_date
        )
        claim = self._state_store.claim_lock(
            key=lock_key,
            owner_token=owner_token,
            ttl_seconds=_LOCK_TTL_SECONDS,
            now=now,
            payload={
                "attemptId": attempt_id,
                "market": market,
                "sessionDate": session_date,
                "runnerRole": runner_role,
            },
        )
        if not getattr(claim, "acquired", False):
            return ScheduledAiBriefResult(
                status="lock_held_skip",
                session_date=session_date,
            )
        return _MainLockLease(lock_key=lock_key, owner_token=owner_token)

    def _claim_schedule_notification(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
    ) -> _NotificationClaimLease | ScheduledAiBriefResult:
        claim_key = build_scheduler_state_key(
            kind="notification:claim",
            market=market,
            session_date=session_date,
        )
        owner_token = f"{attempt_id}-notification-{uuid.uuid4().hex}"
        claim = self._state_store.claim_lock(
            key=claim_key,
            owner_token=owner_token,
            ttl_seconds=_NOTIFICATION_CLAIM_TTL_SECONDS,
            payload={
                "attemptId": attempt_id,
                "market": market,
                "sessionDate": session_date,
                "runnerRole": runner_role,
                "scheduleRole": schedule_role,
                "channel": "telegram",
                "notificationType": "schedule",
            },
        )
        if not getattr(claim, "acquired", False):
            return ScheduledAiBriefResult(
                status="notification_claim_held",
                session_date=session_date,
            )
        return _NotificationClaimLease(
            claim_key=claim_key,
            owner_token=owner_token,
        )

    def _handle_non_trading_guard(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        guard: GuardSnapshot,
        run_url: str,
    ) -> ScheduledAiBriefResult:
        if runner_role not in _PIPELINE_RUNNER_ROLES:
            return ScheduledAiBriefResult(
                status="guard_noop", session_date=session_date
            )

        success_key = build_scheduler_state_key(
            kind="success", market=market, session_date=session_date
        )
        if self._state_store.get_entry(success_key) is not None:
            return ScheduledAiBriefResult(
                status="success_marker_skip",
                session_date=session_date,
            )

        artifact_key = build_scheduler_state_key(
            kind="artifact", market=market, session_date=session_date
        )
        artifact_entry = self._state_store.get_entry(artifact_key)
        if artifact_entry is not None:
            return self._reconcile_notification(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                artifact_entry=artifact_entry,
                require_main_lock=False,
                main_lock_key=None,
                main_owner_token=None,
            )

        return self._persist_runtime_guard_skip_result(
            market=market,
            session_date=session_date,
            guard=guard,
            run_url=run_url,
            success_status="guard_noop",
        )

    def _dispatch_ready_run(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        source_provider: str | None,
        model_provider: str,
        guard: GuardSnapshot,
        artifact_key: str,
        now: dt.datetime,
        model_deadline_at: dt.datetime | None,
    ) -> ScheduledAiBriefResult:
        _LOGGER.info(
            "scheduled AI brief dispatch resolved "
            "market=%s session_date=%s schedule_role=%s runner_role=%s "
            "attempt_id=%s",
            market,
            session_date,
            schedule_role,
            runner_role,
            attempt_id,
        )
        if runner_role == "monitor-only":
            return self._monitor_local_primary(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                now=now,
            )
        if runner_role == "cutoff-alert":
            return self._handle_cutoff_alert(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                now=now,
            )
        if not _guard_allows_pipeline(guard):
            return self._handle_pre_open_guard_failure(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                run_url=run_url,
                guard=guard,
                now=now,
            )
        try:
            source_context = _resolve_scheduled_source_context(
                market=market,
                source_provider=source_provider,
            )
        except _ScheduledSourceConfigError as exc:
            self._log_source_config_invalid(
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                error=exc,
            )
            return ScheduledAiBriefResult(
                status="source_config_invalid",
                session_date=session_date,
            )
        self._log_source_context_resolved(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            source_context=source_context,
        )
        return self._start_locked_pipeline(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            run_url=run_url,
            source_provider=source_context.source_provider,
            source_provider_chain=source_context.source_provider_chain,
            source_api_url=source_context.source_api_url,
            model_provider=model_provider,
            artifact_key=artifact_key,
            now=now,
            model_deadline_at=model_deadline_at,
        )

    def _log_source_context_resolved(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        source_context: _ScheduledSourceContext,
    ) -> None:
        _LOGGER.info(
            "scheduled AI brief source context resolved "
            "market=%s session_date=%s schedule_role=%s runner_role=%s "
            "attempt_id=%s source_provider=%s source_provider_origin=%s "
            "source_provider_chain=%s source_provider_chain_origin=%s "
            "source_api_url_configured=%s source_api_url_origin=%s",
            market,
            session_date,
            schedule_role,
            runner_role,
            attempt_id,
            _scheduled_source_provider_for_log(source_context),
            source_context.source_provider_origin,
            _scheduled_source_provider_chain_for_log(source_context),
            source_context.source_provider_chain_origin,
            source_context.source_api_url_configured,
            source_context.source_api_url_origin,
            extra={
                "event": "scheduled_ai_brief_source_context_resolved",
                "status": "success",
                "market": market,
                "session_date": session_date,
                "schedule_role": schedule_role,
                "runner_role": runner_role,
                "attempt_id": attempt_id,
                "source_provider": _scheduled_source_provider_for_log(source_context),
                "source_provider_origin": source_context.source_provider_origin,
                "source_provider_chain": _scheduled_source_provider_chain_for_log(
                    source_context
                ),
                "source_provider_chain_origin": (
                    source_context.source_provider_chain_origin
                ),
                "source_api_url_configured": source_context.source_api_url_configured,
                "source_api_url_origin": source_context.source_api_url_origin,
            },
        )

    def _log_source_config_invalid(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        error: _ScheduledSourceConfigError,
    ) -> None:
        source_context = error.source_context
        _LOGGER.error(
            "scheduled AI brief source config invalid "
            "market=%s session_date=%s schedule_role=%s runner_role=%s "
            "attempt_id=%s error_code=%s source_provider=%s "
            "source_provider_origin=%s source_provider_chain=%s "
            "source_provider_chain_origin=%s source_api_url_configured=%s "
            "source_api_url_origin=%s",
            market,
            session_date,
            schedule_role,
            runner_role,
            attempt_id,
            error.error_code,
            _scheduled_source_provider_for_log(source_context),
            source_context.source_provider_origin,
            _scheduled_source_provider_chain_for_log(source_context),
            source_context.source_provider_chain_origin,
            source_context.source_api_url_configured,
            source_context.source_api_url_origin,
            extra={
                "event": "scheduled_ai_brief_source_config_invalid",
                "status": "failed",
                "market": market,
                "session_date": session_date,
                "schedule_role": schedule_role,
                "runner_role": runner_role,
                "attempt_id": attempt_id,
                "error_code": error.error_code,
                "error_type": type(error).__name__,
                "source_provider": _scheduled_source_provider_for_log(source_context),
                "source_provider_origin": source_context.source_provider_origin,
                "source_provider_chain": _scheduled_source_provider_chain_for_log(
                    source_context
                ),
                "source_provider_chain_origin": (
                    source_context.source_provider_chain_origin
                ),
                "source_api_url_configured": source_context.source_api_url_configured,
                "source_api_url_origin": source_context.source_api_url_origin,
                "retryable": False,
            },
        )

    def _handle_cutoff_alert(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        now: dt.datetime,
    ) -> ScheduledAiBriefResult:
        late_alert_status = self._send_late_alert_once(
            market=market,
            session_date=session_date,
            reason="cutoff_missing_ai_brief",
            context={
                "market": market,
                "sessionDate": session_date,
                "scheduleRole": schedule_role,
                "runnerRole": runner_role,
                "attemptId": attempt_id,
            },
            now=now,
        )
        return ScheduledAiBriefResult(
            status=late_alert_status,
            session_date=session_date,
        )

    def _handle_pre_open_guard_failure(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        guard: GuardSnapshot,
        now: dt.datetime,
    ) -> ScheduledAiBriefResult:
        _LOGGER.warning(
            "scheduled AI brief pre-open guard blocked pipeline "
            "market=%s session_date=%s schedule_role=%s runner_role=%s "
            "attempt_id=%s session_state=%s trading_session=%s",
            market,
            session_date,
            schedule_role,
            runner_role,
            attempt_id,
            guard.session_state,
            guard.trading_session,
        )
        return self._persist_runtime_guard_skip_result(
            market=market,
            session_date=session_date,
            guard=guard,
            run_url=run_url,
            success_status="guard_failed",
            alert_reason="pre_open_guard_failed",
            alert_context=_guard_context(
                market=market,
                session_date=session_date,
                guard=guard,
            ),
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            now=now,
        )

    def _start_locked_pipeline(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        source_provider: str | None,
        source_provider_chain: tuple[str, ...] | None,
        source_api_url: str | None,
        model_provider: str,
        artifact_key: str,
        now: dt.datetime,
        model_deadline_at: dt.datetime | None,
    ) -> ScheduledAiBriefResult:
        self._notifier.require_telegram()
        main_lock = self._claim_main_lock(
            market=market,
            session_date=session_date,
            runner_role=runner_role,
            attempt_id=attempt_id,
            now=now,
        )
        if isinstance(main_lock, ScheduledAiBriefResult):
            return main_lock
        return self._run_locked_pipeline(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            run_url=run_url,
            source_provider=source_provider,
            source_provider_chain=source_provider_chain,
            source_api_url=source_api_url,
            model_provider=model_provider,
            lock_key=main_lock.lock_key,
            owner_token=main_lock.owner_token,
            artifact_key=artifact_key,
            now=now,
            model_deadline_at=model_deadline_at,
        )

    def _run_locked_pipeline(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        source_provider: str | None,
        source_provider_chain: tuple[str, ...] | None = None,
        source_api_url: str | None = None,
        model_provider: str,
        lock_key: str,
        owner_token: str,
        artifact_key: str,
        now: dt.datetime,
        model_deadline_at: dt.datetime | None,
    ) -> ScheduledAiBriefResult:
        lock_renewer = _MainLockRenewer(
            state_store=self._state_store,
            lock_key=lock_key,
            owner_token=owner_token,
            ttl_seconds=_LOCK_TTL_SECONDS,
            interval_seconds=self._lock_renew_interval_seconds,
        )
        lock_renewer.start()
        pipeline_result: ScheduledPipelineResult | None = None
        pipeline_error: Exception | None = None
        try:
            pipeline_result = self._pipeline.run(
                market=market,
                session_date=session_date,
                report_date=session_date,
                source_provider=source_provider,
                source_api_url=source_api_url,
                source_provider_chain=source_provider_chain,
                model_provider=model_provider,
                dry_run=False,
                model_deadline_at=model_deadline_at,
            )
        except Exception as err:
            pipeline_error = err

        try:
            if pipeline_error is not None:
                return self._handle_locked_pipeline_exception(
                    market=market,
                    session_date=session_date,
                    attempt_id=attempt_id,
                    lock_key=lock_key,
                    owner_token=owner_token,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    error=pipeline_error,
                )
            if pipeline_result is None:
                return self._handle_locked_pipeline_failure(
                    market=market,
                    session_date=session_date,
                    attempt_id=attempt_id,
                    lock_key=lock_key,
                    owner_token=owner_token,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    reason="pipeline_failed",
                )

            pre_upload_result = self._handle_locked_pipeline_upload_precheck(
                market=market,
                session_date=session_date,
                run_url=run_url,
                lock_key=lock_key,
                owner_token=owner_token,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
            )
            if pre_upload_result is not None:
                return pre_upload_result

            try:
                storage_key = self._storage.upload_ai_brief(
                    pipeline_result.ai_brief_report_path,
                    report_date=session_date,
                )
            except Exception:
                _LOGGER.exception(
                    "scheduled AI brief upload failed "
                    "market=%s session_date=%s schedule_role=%s runner_role=%s "
                    "attempt_id=%s report_path=%s",
                    market,
                    session_date,
                    schedule_role,
                    runner_role,
                    attempt_id,
                    pipeline_result.ai_brief_report_path,
                )
                return self._handle_locked_pipeline_failure(
                    market=market,
                    session_date=session_date,
                    attempt_id=attempt_id,
                    lock_key=lock_key,
                    owner_token=owner_token,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    reason="upload_failed",
                )
            artifact_result = self._record_uploaded_ai_brief_artifact(
                artifact_key=artifact_key,
                storage_key=storage_key,
                market=market,
                session_date=session_date,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                run_url=run_url,
                lock_key=lock_key,
                owner_token=owner_token,
                now=now,
            )
            if artifact_result is not None:
                return artifact_result
            if not self._state_store.check_ownership(lock_key, owner_token=owner_token):
                return ScheduledAiBriefResult(
                    status="artifact_uploaded_notification_deferred",
                    session_date=session_date,
                    storage_key=storage_key,
                )

            try:
                result = self._reconcile_notification(
                    market=market,
                    session_date=session_date,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    attempt_id=attempt_id,
                    artifact_entry=RuntimeStateEntry(
                        state_key=artifact_key,
                        state_payload={"storageKey": storage_key},
                        expires_at="",
                    ),
                    require_main_lock=True,
                    main_lock_key=lock_key,
                    main_owner_token=owner_token,
                )
            finally:
                lock_renewer.stop()
                self._state_store.release_lock(lock_key, owner_token=owner_token)
            if result.status == "notification_reconciled":
                return ScheduledAiBriefResult(
                    status="completed",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            return result
        finally:
            lock_renewer.stop()

    def _handle_locked_pipeline_exception(
        self,
        *,
        market: str,
        session_date: str,
        attempt_id: str,
        lock_key: str,
        owner_token: str,
        schedule_role: str,
        runner_role: str,
        error: Exception,
    ) -> ScheduledAiBriefResult:
        failure_is_scheduled_entry, failure_context = (
            _scheduled_entry_failure_diagnostic(error)
        )
        failure_alert_reason = "pipeline_failed"
        if failure_is_scheduled_entry:
            failure_alert_reason = _SCHEDULED_ENTRY_FAILURE_ALERT_REASON
            entry_report_upload_path = _scheduled_entry_failure_upload_path(error)
            if entry_report_upload_path is not None:
                try:
                    entry_report_upload = (
                        self._upload_scheduled_entry_failure_report_once(
                            market=market,
                            session_date=session_date,
                            schedule_role=schedule_role,
                            runner_role=runner_role,
                            attempt_id=attempt_id,
                            lock_key=lock_key,
                            owner_token=owner_token,
                            report_path=entry_report_upload_path,
                        )
                    )
                except Exception:
                    _LOGGER.exception(
                        "scheduled entry failure report upload failed "
                        "market=%s session_date=%s schedule_role=%s "
                        "runner_role=%s attempt_id=%s report_path=%s",
                        market,
                        session_date,
                        schedule_role,
                        runner_role,
                        attempt_id,
                        entry_report_upload_path,
                    )
                    failure_context["entryReportUploadStatus"] = "failed"
                else:
                    if isinstance(entry_report_upload, ScheduledAiBriefResult):
                        self._log_locked_pipeline_exception(
                            market=market,
                            session_date=session_date,
                            schedule_role=schedule_role,
                            runner_role=runner_role,
                            attempt_id=attempt_id,
                            error=error,
                        )
                        return entry_report_upload
                    if isinstance(entry_report_upload, _EntryFailureArtifactClaimHeld):
                        self._log_locked_pipeline_exception(
                            market=market,
                            session_date=session_date,
                            schedule_role=schedule_role,
                            runner_role=runner_role,
                            attempt_id=attempt_id,
                            error=error,
                        )
                        self._state_store.release_lock(
                            lock_key,
                            owner_token=owner_token,
                        )
                        return ScheduledAiBriefResult(
                            status="entry_failure_artifact_claim_held",
                            session_date=session_date,
                        )
                    elif entry_report_upload is not None:
                        failure_context["entryReportStorageKey"] = entry_report_upload

        self._log_locked_pipeline_exception(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            error=error,
        )
        return self._handle_locked_pipeline_failure(
            market=market,
            session_date=session_date,
            attempt_id=attempt_id,
            lock_key=lock_key,
            owner_token=owner_token,
            schedule_role=schedule_role,
            runner_role=runner_role,
            reason="pipeline_failed",
            alert_reason=failure_alert_reason,
            failure_context=failure_context,
        )

    def _log_locked_pipeline_exception(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        error: Exception,
    ) -> None:
        safe_log_message = _scheduled_entry_failure_log_message(error)
        if safe_log_message is None:
            _LOGGER.error(
                "scheduled AI brief pipeline failed "
                "market=%s session_date=%s schedule_role=%s runner_role=%s "
                "attempt_id=%s",
                market,
                session_date,
                schedule_role,
                runner_role,
                attempt_id,
                exc_info=(type(error), error, error.__traceback__),
            )
            return

        _LOGGER.error(
            "scheduled AI brief pipeline failed "
            "market=%s session_date=%s schedule_role=%s runner_role=%s "
            "attempt_id=%s error_type=%s error=%s",
            market,
            session_date,
            schedule_role,
            runner_role,
            attempt_id,
            type(error).__name__,
            safe_log_message,
            exc_info=_scheduled_entry_failure_exc_info(error, safe_log_message),
        )

    def _record_scheduled_entry_failure_artifact_marker(
        self,
        *,
        artifact_key: str,
        storage_key: str,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        report_path: str,
        now: dt.datetime,
    ) -> None:
        self._state_store.upsert_marker(
            key=artifact_key,
            payload={
                "storageKey": storage_key,
                "market": market,
                "sessionDate": session_date,
                "reportDate": session_date,
                "entryReportPath": report_path,
                "reason": _SCHEDULED_ENTRY_FAILURE_ALERT_REASON,
                "scheduleRole": schedule_role,
                "runnerRole": runner_role,
                "attemptId": attempt_id,
            },
            ttl_seconds=_SUCCESS_TTL_SECONDS,
            now=now,
        )

    def _upload_scheduled_entry_failure_report_once(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        lock_key: str,
        owner_token: str,
        report_path: str,
    ) -> str | ScheduledAiBriefResult | _EntryFailureArtifactClaimHeld | None:
        if not self._state_store.renew_lock(
            lock_key,
            owner_token=owner_token,
            ttl_seconds=_LOCK_TTL_SECONDS,
        ):
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
            )
        if not self._state_store.check_ownership(lock_key, owner_token=owner_token):
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
            )
        artifact_key = _scheduled_entry_failure_artifact_key(
            market=market,
            session_date=session_date,
        )
        existing_storage_key = _runtime_state_storage_key(
            self._state_store.get_entry(artifact_key)
        )
        if existing_storage_key:
            return existing_storage_key
        sent_storage_key = _runtime_state_entry_report_storage_key(
            self._state_store.get_entry(
                _late_alert_sent_key(
                    market=market,
                    session_date=session_date,
                    reason=_SCHEDULED_ENTRY_FAILURE_ALERT_REASON,
                )
            )
        )
        if sent_storage_key:
            return sent_storage_key

        claim_key = build_scheduler_state_key(
            kind="entry-failure-artifact:claim",
            market=market,
            session_date=session_date,
        )
        claim_owner_token = f"entry-failure-artifact-{uuid.uuid4().hex}"
        now = self._now_fn()
        claim = self._state_store.claim_lock(
            key=claim_key,
            owner_token=claim_owner_token,
            ttl_seconds=_LATE_ALERT_CLAIM_TTL_SECONDS,
            now=now,
            payload={
                "market": market,
                "sessionDate": session_date,
                "reason": _SCHEDULED_ENTRY_FAILURE_ALERT_REASON,
                "scheduleRole": schedule_role,
                "runnerRole": runner_role,
                "attemptId": attempt_id,
            },
        )
        if not getattr(claim, "acquired", False):
            existing_storage_key = _runtime_state_storage_key(
                self._state_store.get_entry(artifact_key)
            )
            if existing_storage_key:
                return existing_storage_key
            return _ENTRY_FAILURE_ARTIFACT_CLAIM_HELD

        try:
            existing_storage_key = _runtime_state_storage_key(
                self._state_store.get_entry(artifact_key)
            )
            if existing_storage_key:
                return existing_storage_key
            if not self._state_store.renew_lock(
                lock_key,
                owner_token=owner_token,
                ttl_seconds=_LOCK_TTL_SECONDS,
            ):
                return ScheduledAiBriefResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )
            if not self._state_store.check_ownership(
                lock_key,
                owner_token=owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )
            storage_key = self._storage.upload_entry_report(
                report_path,
                report_date=session_date,
            )
            if not self._state_store.check_ownership(
                lock_key,
                owner_token=owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            try:
                self._record_scheduled_entry_failure_artifact_marker(
                    artifact_key=artifact_key,
                    storage_key=storage_key,
                    market=market,
                    session_date=session_date,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    attempt_id=attempt_id,
                    report_path=report_path,
                    now=now,
                )
            except Exception:
                _LOGGER.exception(
                    "scheduled entry failure artifact marker failed "
                    "market=%s session_date=%s schedule_role=%s "
                    "runner_role=%s attempt_id=%s storage_key=%s report_path=%s",
                    market,
                    session_date,
                    schedule_role,
                    runner_role,
                    attempt_id,
                    storage_key,
                    report_path,
                )
            return storage_key
        finally:
            self._state_store.release_lock(claim_key, owner_token=claim_owner_token)

    def _handle_locked_pipeline_failure(
        self,
        *,
        market: str,
        session_date: str,
        attempt_id: str,
        lock_key: str,
        owner_token: str,
        reason: str,
        schedule_role: str | None = None,
        runner_role: str | None = None,
        storage_key: str | None = None,
        alert_reason: str | None = None,
        failure_context: dict[str, object] | None = None,
    ) -> ScheduledAiBriefResult:
        context: dict[str, object] = {
            "market": market,
            "sessionDate": session_date,
            "attemptId": attempt_id,
        }
        if schedule_role is not None:
            context["scheduleRole"] = schedule_role
        if runner_role is not None:
            context["runnerRole"] = runner_role
        if storage_key is not None:
            context["storageKey"] = storage_key
        if failure_context:
            context.update(failure_context)
        if not self._state_store.renew_lock(
            lock_key,
            owner_token=owner_token,
            ttl_seconds=_LOCK_TTL_SECONDS,
        ) or not self._state_store.check_ownership(lock_key, owner_token=owner_token):
            self._state_store.release_lock(lock_key, owner_token=owner_token)
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
                storage_key=storage_key,
            )
        try:
            late_alert_status = self._send_late_alert_once(
                market=market,
                session_date=session_date,
                reason=alert_reason or reason,
                context=context,
                now=self._now_fn(),
                main_lock_key=lock_key,
                main_owner_token=owner_token,
            )
        finally:
            self._state_store.release_lock(lock_key, owner_token=owner_token)
        if late_alert_status == "lock_lost_before_upload":
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
                storage_key=storage_key,
            )
        return ScheduledAiBriefResult(
            status=reason,
            session_date=session_date,
            storage_key=storage_key,
        )

    def _handle_locked_pipeline_upload_precheck(
        self,
        *,
        market: str,
        session_date: str,
        run_url: str,
        lock_key: str,
        owner_token: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
    ) -> ScheduledAiBriefResult | None:
        if not self._state_store.renew_lock(
            lock_key,
            owner_token=owner_token,
            ttl_seconds=_LOCK_TTL_SECONDS,
        ):
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
            )
        if not self._state_store.check_ownership(lock_key, owner_token=owner_token):
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
            )

        pre_upload_guard = self._guard_resolver(market, self._now_fn())
        if _guard_allows_pipeline(pre_upload_guard):
            return None

        try:
            skip_result = self._persist_runtime_guard_skip(
                market=market,
                session_date=session_date,
                guard=pre_upload_guard,
                run_url=run_url,
                main_lock_key=lock_key,
                main_owner_token=owner_token,
            )
            if isinstance(skip_result, ScheduledAiBriefResult):
                self._state_store.release_lock(lock_key, owner_token=owner_token)
                return skip_result
            skip_key = skip_result
        except _SkipArtifactClaimHeld:
            self._state_store.release_lock(lock_key, owner_token=owner_token)
            return ScheduledAiBriefResult(
                status="skip_artifact_claim_held",
                session_date=session_date,
            )
        except Exception:
            try:
                self._send_late_alert_once(
                    market=market,
                    session_date=session_date,
                    reason="pre_upload_guard_failed",
                    context=_with_alert_run_context(
                        _guard_context(
                            market=market,
                            session_date=session_date,
                            guard=pre_upload_guard,
                        ),
                        schedule_role=schedule_role,
                        runner_role=runner_role,
                        attempt_id=attempt_id,
                    ),
                    now=self._now_fn(),
                    main_lock_key=lock_key,
                    main_owner_token=owner_token,
                )
            finally:
                self._state_store.release_lock(lock_key, owner_token=owner_token)
            return ScheduledAiBriefResult(
                status="skip_artifact_upload_failed",
                session_date=session_date,
            )

        if not self._state_store.check_ownership(lock_key, owner_token=owner_token):
            self._state_store.release_lock(lock_key, owner_token=owner_token)
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
                storage_key=skip_key,
            )
        try:
            late_alert_status = self._send_late_alert_once(
                market=market,
                session_date=session_date,
                reason="pre_upload_guard_failed",
                context=_with_alert_run_context(
                    _guard_context(
                        market=market,
                        session_date=session_date,
                        guard=pre_upload_guard,
                    ),
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    attempt_id=attempt_id,
                ),
                now=self._now_fn(),
                main_lock_key=lock_key,
                main_owner_token=owner_token,
            )
        finally:
            self._state_store.release_lock(lock_key, owner_token=owner_token)
        if late_alert_status == "lock_lost_before_upload":
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
                storage_key=skip_key,
            )
        return ScheduledAiBriefResult(
            status="guard_failed_before_upload",
            session_date=session_date,
            storage_key=skip_key,
        )

    def _record_pipeline_attempt_marker(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        scheduled_tick: str,
        attempt_id: str,
        run_url: str,
        now: dt.datetime,
    ) -> ScheduledAiBriefResult | None:
        try:
            self._state_store.upsert_marker(
                key=build_scheduler_state_key(
                    kind="attempt",
                    market=market,
                    session_date=session_date,
                    runner_role=runner_role,
                    attempt_id=attempt_id,
                ),
                payload=_state_payload(
                    market=market,
                    session_date=session_date,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    scheduled_tick=scheduled_tick,
                    attempt_id=attempt_id,
                    run_url=run_url,
                    runner=_runner_origin(runner_role),
                    started_at=now,
                ),
                ttl_seconds=_ATTEMPT_TTL_SECONDS,
                now=now,
            )
        except Exception:
            return ScheduledAiBriefResult(
                status="attempt_marker_failed",
                session_date=session_date,
            )
        return None

    def _record_ai_brief_artifact_marker(
        self,
        *,
        artifact_key: str,
        storage_key: str,
        market: str,
        session_date: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        now: dt.datetime,
    ) -> None:
        self._state_store.upsert_marker(
            key=artifact_key,
            payload={
                "storageKey": storage_key,
                "market": market,
                "sessionDate": session_date,
                "reportDate": session_date,
                "runner": _runner_origin(runner_role),
                "attemptId": attempt_id,
                "runUrl": run_url,
            },
            ttl_seconds=_SUCCESS_TTL_SECONDS,
            now=now,
        )

    def _record_uploaded_ai_brief_artifact(
        self,
        *,
        artifact_key: str,
        storage_key: str,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        lock_key: str,
        owner_token: str,
        now: dt.datetime,
    ) -> ScheduledAiBriefResult | None:
        if not self._state_store.check_ownership(lock_key, owner_token=owner_token):
            self._state_store.release_lock(lock_key, owner_token=owner_token)
            return ScheduledAiBriefResult(
                status="lock_lost_before_upload",
                session_date=session_date,
                storage_key=storage_key,
            )
        try:
            self._record_ai_brief_artifact_marker(
                artifact_key=artifact_key,
                storage_key=storage_key,
                market=market,
                session_date=session_date,
                runner_role=runner_role,
                attempt_id=attempt_id,
                run_url=run_url,
                now=now,
            )
        except Exception:
            _LOGGER.exception(
                "scheduled AI brief artifact marker failed "
                "market=%s session_date=%s schedule_role=%s runner_role=%s "
                "attempt_id=%s storage_key=%s",
                market,
                session_date,
                schedule_role,
                runner_role,
                attempt_id,
                storage_key,
            )
            return self._handle_locked_pipeline_failure(
                market=market,
                session_date=session_date,
                attempt_id=attempt_id,
                lock_key=lock_key,
                owner_token=owner_token,
                schedule_role=schedule_role,
                runner_role=runner_role,
                reason="artifact_marker_failed",
                storage_key=storage_key,
            )
        return None

    def _persist_runtime_guard_skip_result(
        self,
        *,
        market: str,
        session_date: str,
        guard: GuardSnapshot,
        run_url: str,
        success_status: str,
        alert_reason: str | None = None,
        alert_context: dict[str, object] | None = None,
        schedule_role: str | None = None,
        runner_role: str | None = None,
        attempt_id: str | None = None,
        now: dt.datetime | None = None,
    ) -> ScheduledAiBriefResult:
        try:
            skip_key = self._persist_runtime_guard_skip(
                market=market,
                session_date=session_date,
                guard=guard,
                run_url=run_url,
            )
            if isinstance(skip_key, ScheduledAiBriefResult):
                return skip_key
        except _SkipArtifactClaimHeld:
            return ScheduledAiBriefResult(
                status="skip_artifact_claim_held",
                session_date=session_date,
            )
        except Exception:
            if alert_reason is not None:
                self._send_late_alert_once(
                    market=market,
                    session_date=session_date,
                    reason=alert_reason,
                    context=_with_alert_run_context(
                        alert_context
                        or _guard_context(
                            market=market,
                            session_date=session_date,
                            guard=guard,
                        ),
                        schedule_role=schedule_role,
                        runner_role=runner_role,
                        attempt_id=attempt_id,
                    ),
                    now=now or self._now_fn(),
                )
            return ScheduledAiBriefResult(
                status="skip_artifact_upload_failed",
                session_date=session_date,
            )

        if alert_reason is not None:
            self._send_late_alert_once(
                market=market,
                session_date=session_date,
                reason=alert_reason,
                context=_with_alert_run_context(
                    alert_context
                    or _guard_context(
                        market=market,
                        session_date=session_date,
                        guard=guard,
                    ),
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    attempt_id=attempt_id,
                ),
                now=now or self._now_fn(),
            )
        return ScheduledAiBriefResult(
            status=success_status,
            session_date=session_date,
            storage_key=skip_key,
        )

    def _reconcile_existing_or_repaired_artifact(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        now: dt.datetime,
        artifact_key: str | None = None,
    ) -> ScheduledAiBriefResult | None:
        artifact_key = artifact_key or build_scheduler_state_key(
            kind="artifact", market=market, session_date=session_date
        )
        artifact_entry = self._state_store.get_entry(artifact_key)
        if artifact_entry is None:
            artifact_entry = self._repair_artifact_marker_from_report_index(
                market=market,
                session_date=session_date,
                report_date=session_date,
                artifact_key=artifact_key,
                schedule_role=schedule_role,
                runner_role=runner_role,
                attempt_id=attempt_id,
                run_url=run_url,
                now=now,
            )
        if artifact_entry is None:
            return None
        return self._reconcile_notification(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
            artifact_entry=artifact_entry,
            require_main_lock=False,
            main_lock_key=None,
            main_owner_token=None,
        )

    def _persist_runtime_guard_skip(
        self,
        *,
        market: str,
        session_date: str,
        guard: GuardSnapshot,
        run_url: str,
        main_lock_key: str | None = None,
        main_owner_token: str | None = None,
    ) -> str | ScheduledAiBriefResult:
        skip_artifact_key = build_scheduler_state_key(
            kind="skip-artifact",
            market=market,
            session_date=session_date,
        )
        existing_storage_key = _runtime_state_storage_key(
            self._state_store.get_entry(skip_artifact_key)
        )
        if existing_storage_key:
            return existing_storage_key

        claim_key = build_scheduler_state_key(
            kind="skip-artifact:claim",
            market=market,
            session_date=session_date,
        )
        owner_token = f"skip-artifact-{uuid.uuid4().hex}"
        now = self._now_fn()
        claim = self._state_store.claim_lock(
            key=claim_key,
            owner_token=owner_token,
            ttl_seconds=_SKIP_ARTIFACT_CLAIM_TTL_SECONDS,
            now=now,
            payload={
                "market": market,
                "sessionDate": session_date,
                "skipState": AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
            },
        )
        if not getattr(claim, "acquired", False):
            existing_storage_key = _runtime_state_storage_key(
                self._state_store.get_entry(skip_artifact_key)
            )
            if existing_storage_key:
                return existing_storage_key
            raise _SkipArtifactClaimHeld("skip artifact claim is held")

        try:
            existing_storage_key = _runtime_state_storage_key(
                self._state_store.get_entry(skip_artifact_key)
            )
            if existing_storage_key:
                return existing_storage_key
            if (
                main_lock_key is not None
                and main_owner_token is not None
                and not self._owns_main_lock(
                    main_lock_key=main_lock_key,
                    main_owner_token=main_owner_token,
                )
            ):
                return ScheduledAiBriefResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                )
            report_path = write_ai_brief_skip_report(
                report_dir="reports",
                market=market,
                session_date=session_date,
                session_state=guard.session_state,
                expected_state="PRE_OPEN",
                trading_session=guard.trading_session,
                local_time=guard.local_time,
                run_url=run_url,
                source="scheduled-runtime-guard",
                now=now,
            )
            storage_key = self._storage.upload_ai_brief_skip(
                report_path,
                report_date=session_date,
            )
            if (
                main_lock_key is not None
                and main_owner_token is not None
                and not self._owns_main_lock(
                    main_lock_key=main_lock_key,
                    main_owner_token=main_owner_token,
                )
            ):
                return ScheduledAiBriefResult(
                    status="lock_lost_before_upload",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            self._record_runtime_guard_skip_marker(
                skip_artifact_key=skip_artifact_key,
                storage_key=storage_key,
                market=market,
                session_date=session_date,
                run_url=run_url,
                now=now,
            )
            return storage_key
        except Exception as exc:
            _LOGGER.exception(
                "scheduled AI brief skip artifact upload failed: %s",
                exc,
            )
            raise
        finally:
            self._state_store.release_lock(claim_key, owner_token=owner_token)

    def _record_runtime_guard_skip_marker(
        self,
        *,
        skip_artifact_key: str,
        storage_key: str,
        market: str,
        session_date: str,
        run_url: str,
        now: dt.datetime,
    ) -> None:
        self._state_store.upsert_marker(
            key=skip_artifact_key,
            payload={
                "storageKey": storage_key,
                "market": market,
                "sessionDate": session_date,
                "skipState": AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
                "skipReason": "runtime_guard_skipped",
                "runUrl": run_url,
            },
            ttl_seconds=_SUCCESS_TTL_SECONDS,
            now=now,
        )

    def _handle_notification_guard_failure(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        guard: GuardSnapshot,
        storage_key: str,
        main_lock_key: str | None = None,
        main_owner_token: str | None = None,
    ) -> ScheduledAiBriefResult:
        context = _with_alert_run_context(
            _guard_context(market=market, session_date=session_date, guard=guard),
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
        )
        context["storageKey"] = storage_key
        late_alert_status = self._send_late_alert_once(
            market=market,
            session_date=session_date,
            reason="pre_notification_guard_failed",
            context=context,
            now=self._now_fn(),
            main_lock_key=main_lock_key,
            main_owner_token=main_owner_token,
        )
        if late_alert_status == "lock_lost_before_upload":
            return ScheduledAiBriefResult(
                status="artifact_uploaded_notification_deferred",
                session_date=session_date,
                storage_key=storage_key,
            )
        return ScheduledAiBriefResult(
            status="guard_failed_before_notification",
            session_date=session_date,
            storage_key=storage_key,
        )

    def _reconcile_notification(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        artifact_entry: RuntimeStateEntry,
        require_main_lock: bool,
        main_lock_key: str | None,
        main_owner_token: str | None,
    ) -> ScheduledAiBriefResult:
        if require_main_lock and not self._owns_main_lock(
            main_lock_key=main_lock_key,
            main_owner_token=main_owner_token,
        ):
            return ScheduledAiBriefResult(
                status="artifact_uploaded_notification_deferred",
                session_date=session_date,
            )

        sent_key = build_scheduler_state_key(
            kind="notification:sent",
            market=market,
            session_date=session_date,
        )
        sent_entry = self._state_store.get_entry(sent_key)
        if sent_entry is not None:
            if require_main_lock and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="artifact_uploaded_notification_deferred",
                    session_date=session_date,
                    storage_key=_runtime_state_storage_key(sent_entry),
                )
            self._state_store.upsert_marker(
                key=build_scheduler_state_key(
                    kind="success", market=market, session_date=session_date
                ),
                payload={"market": market, "sessionDate": session_date},
                ttl_seconds=_SUCCESS_TTL_SECONDS,
            )
            return ScheduledAiBriefResult(
                status="completion_repaired",
                session_date=session_date,
            )

        self._notifier.require_telegram()
        storage_key = _runtime_state_storage_key(artifact_entry)
        if not storage_key:
            return ScheduledAiBriefResult(
                status="artifact_marker_invalid",
                session_date=session_date,
            )
        notification_claim = self._claim_schedule_notification(
            market=market,
            session_date=session_date,
            schedule_role=schedule_role,
            runner_role=runner_role,
            attempt_id=attempt_id,
        )
        if isinstance(notification_claim, ScheduledAiBriefResult):
            return notification_claim
        try:
            if require_main_lock and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="artifact_uploaded_notification_deferred",
                    session_date=session_date,
                    storage_key=storage_key,
                )

            pre_notification_guard = self._guard_resolver(market, self._now_fn())
            if not _guard_allows_pipeline(pre_notification_guard):
                return self._handle_notification_guard_failure(
                    market=market,
                    session_date=session_date,
                    schedule_role=schedule_role,
                    runner_role=runner_role,
                    attempt_id=attempt_id,
                    guard=pre_notification_guard,
                    storage_key=storage_key,
                    main_lock_key=main_lock_key if require_main_lock else None,
                    main_owner_token=(main_owner_token if require_main_lock else None),
                )
            report = self._storage.download_json(storage_key)
            validate_ai_brief_artifact(report, now=dt.datetime.now(dt.UTC))
            if not _is_scheduled_artifact_for_session(
                report,
                market=market,
                session_date=session_date,
                report_date=session_date,
            ):
                return ScheduledAiBriefResult(
                    status="artifact_marker_invalid",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            if require_main_lock and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="artifact_uploaded_notification_deferred",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            self._notifier.send_schedule(report=report, storage_key=storage_key)
            if require_main_lock and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="artifact_uploaded_notification_deferred",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            self._state_store.upsert_marker(
                key=sent_key,
                payload={
                    "market": market,
                    "sessionDate": session_date,
                    "storageKey": storage_key,
                    "attemptId": attempt_id,
                },
                ttl_seconds=_SUCCESS_TTL_SECONDS,
            )
            if require_main_lock and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return ScheduledAiBriefResult(
                    status="artifact_uploaded_notification_deferred",
                    session_date=session_date,
                    storage_key=storage_key,
                )
            self._state_store.upsert_marker(
                key=build_scheduler_state_key(
                    kind="success", market=market, session_date=session_date
                ),
                payload={
                    "market": market,
                    "sessionDate": session_date,
                    "storageKey": storage_key,
                    "attemptId": attempt_id,
                },
                ttl_seconds=_SUCCESS_TTL_SECONDS,
            )
            return ScheduledAiBriefResult(
                status="notification_reconciled",
                session_date=session_date,
                storage_key=storage_key,
            )
        finally:
            self._state_store.release_lock(
                notification_claim.claim_key,
                owner_token=notification_claim.owner_token,
            )

    def _owns_main_lock(
        self,
        *,
        main_lock_key: str | None,
        main_owner_token: str | None,
    ) -> bool:
        if not main_lock_key or not main_owner_token:
            return False
        return self._state_store.check_ownership(
            main_lock_key,
            owner_token=main_owner_token,
        )

    def _monitor_local_primary(
        self,
        *,
        market: str,
        session_date: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        now: dt.datetime,
    ) -> ScheduledAiBriefResult:
        attempt_entries = self._state_store.list_entries(
            prefix=_attempt_prefix(
                market=market,
                session_date=session_date,
                runner_role="local-primary",
            ),
            limit=10,
        )
        if attempt_entries:
            return ScheduledAiBriefResult(
                status="monitor_local_primary_started",
                session_date=session_date,
            )

        lock_key = build_scheduler_state_key(
            kind="lock", market=market, session_date=session_date
        )
        if self._state_store.get_entry(lock_key) is not None:
            return ScheduledAiBriefResult(
                status="monitor_local_primary_lock_active",
                session_date=session_date,
            )

        self._send_late_alert_once(
            market=market,
            session_date=session_date,
            reason="local_primary_missing",
            context={
                "market": market,
                "sessionDate": session_date,
                "scheduleRole": schedule_role,
                "runnerRole": runner_role,
                "attemptId": attempt_id,
            },
            now=now,
        )
        return ScheduledAiBriefResult(
            status="monitor_local_primary_missing",
            session_date=session_date,
        )

    def _repair_artifact_marker_from_report_index(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        artifact_key: str,
        schedule_role: str,
        runner_role: str,
        attempt_id: str,
        run_url: str,
        now: dt.datetime,
    ) -> RuntimeStateEntry | None:
        for storage_key in self._storage.list_ai_brief_report_index(
            report_date=report_date
        ):
            try:
                report = self._storage.download_json(storage_key)
                validate_ai_brief_artifact(report, now=now)
            except Exception:
                continue
            if not _is_scheduled_artifact_for_session(
                report,
                market=market,
                session_date=session_date,
                report_date=report_date,
            ):
                continue

            payload = {
                "storageKey": storage_key,
                "market": market,
                "sessionDate": session_date,
                "reportDate": report_date,
                "runner": _runner_origin(runner_role),
                "scheduleRole": schedule_role,
                "attemptId": attempt_id,
                "runUrl": run_url,
                "verifiedGeneratedAt": report.get("generated_at"),
                "repairedAt": now.replace(microsecond=0).isoformat(),
                "repairedFromReportIndex": True,
            }
            self._state_store.upsert_marker(
                key=artifact_key,
                payload=payload,
                ttl_seconds=_SUCCESS_TTL_SECONDS,
                now=now,
            )
            return RuntimeStateEntry(
                state_key=artifact_key,
                state_payload=payload,
                expires_at="",
            )
        return None

    def _send_late_alert_once(
        self,
        *,
        market: str,
        session_date: str,
        reason: str,
        context: dict[str, object],
        now: dt.datetime,
        main_lock_key: str | None = None,
        main_owner_token: str | None = None,
    ) -> str:
        sent_key = _late_alert_sent_key(
            market=market,
            session_date=session_date,
            reason=reason,
        )
        if self._state_store.get_entry(sent_key) is not None:
            return "late_alert_already_sent"

        claim_key = (
            build_scheduler_state_key(
                kind="late-alert:claim",
                market=market,
                session_date=session_date,
            )
            + f":{reason}"
        )
        owner_token = f"{reason}-{uuid.uuid4().hex}"
        claim = self._state_store.claim_lock(
            key=claim_key,
            owner_token=owner_token,
            ttl_seconds=_LATE_ALERT_CLAIM_TTL_SECONDS,
            now=now,
            payload={
                "market": market,
                "sessionDate": session_date,
                "reason": reason,
            },
        )
        if not getattr(claim, "acquired", False):
            return "late_alert_claim_held"
        try:
            if self._state_store.get_entry(sent_key) is not None:
                return "late_alert_already_sent"
            if (
                main_lock_key is not None or main_owner_token is not None
            ) and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return "lock_lost_before_upload"
            try:
                self._notifier.require_telegram()
                self._notifier.send_late_alert(reason=reason, context=context)
            except Exception:
                _LOGGER.exception(
                    "scheduled AI brief late alert delivery failed "
                    "market=%s session_date=%s reason=%s context=%s",
                    market,
                    session_date,
                    reason,
                    context,
                )
                return "late_alert_send_failed"
            if (
                main_lock_key is not None or main_owner_token is not None
            ) and not self._owns_main_lock(
                main_lock_key=main_lock_key,
                main_owner_token=main_owner_token,
            ):
                return "lock_lost_before_upload"
            try:
                self._state_store.upsert_marker(
                    key=sent_key,
                    payload={
                        **context,
                        "market": market,
                        "sessionDate": session_date,
                        "reason": reason,
                    },
                    ttl_seconds=_SUCCESS_TTL_SECONDS,
                    now=now,
                )
            except Exception:
                _LOGGER.exception(
                    "scheduled AI brief late alert sent marker failed "
                    "market=%s session_date=%s reason=%s",
                    market,
                    session_date,
                    reason,
                )
                return "late_alert_sent_marker_failed"
            return "late_alert_sent"
        finally:
            self._state_store.release_lock(claim_key, owner_token=owner_token)


_SCHEDULED_ENTRY_FAILURE_ALERT_REASON = "scheduled_entry_failed"
_SCHEDULED_ENTRY_FAILURE_TOKEN = "scheduled entry failed"
_SCHEDULED_ENTRY_TRACEBACK_REDACTION = "<redacted scheduled entry exception>"
_SCHEDULED_ENTRY_FAILURE_TOKEN_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])scheduled[^A-Za-z0-9]*entry[^A-Za-z0-9]*failed(?![A-Za-z0-9])"
)
_SCHEDULED_ENTRY_FAILURE_PREFIX = (
    f"{_SCHEDULED_ENTRY_FAILURE_TOKEN} (entry_report_path="
)
_SCHEDULED_ENTRY_FAILURE_SUFFIX = ")"
_ENTRY_REPORT_JSON_SUFFIX = ".entry.json"
_SCHEDULED_ENTRY_FAILURE_SENTINELS = frozenset({"not produced", "unsafe"})
_SCHEDULED_ENTRY_FAILURE_LOG_PREFIXES = (
    _SCHEDULED_ENTRY_FAILURE_PREFIX,
    f"wrapper: {_SCHEDULED_ENTRY_FAILURE_PREFIX}",
    f"entry wrapper: {_SCHEDULED_ENTRY_FAILURE_PREFIX}",
)
_ENTRY_REPORT_PATH_LABEL_PATTERN = re.compile(r"entry_report_path\s*=", re.IGNORECASE)
_ENTRY_REPORT_PATH_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._/-])"
    r"(?:file:/*|[A-Za-z]:[\\/]|\\\\[^\\/\r\n]+[\\/]|/|~/|\./|\.\./|reports[\\/])"
    r"[^\r\n]*?\.entry\.json(?:[^\s\r\n]*)?",
    re.IGNORECASE,
)
_SAFE_ENTRY_REPORT_PATH_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-/"
)
_ENTRY_REPORT_PATH_SLASH_LIKE_CHARS = frozenset(
    {
        "\u2044",  # fraction slash
        "\u2215",  # division slash
        "\u2216",  # set minus
        "\u2571",  # box drawings light diagonal upper right to lower left
        "\u29f8",  # big solidus
        "\uff0f",  # fullwidth solidus
    }
)


class _ScheduledEntryStepError(RuntimeError):
    def __init__(self, entry_report_path: str) -> None:
        normalized = _strip_scheduled_entry_failure_log_boundaries(entry_report_path)
        normalized_lower = normalized.lower()
        prefix = _SCHEDULED_ENTRY_FAILURE_PREFIX
        if normalized_lower.startswith(prefix) and normalized.endswith(
            _SCHEDULED_ENTRY_FAILURE_SUFFIX
        ):
            entry_report_path = normalized[
                len(prefix) : -len(_SCHEDULED_ENTRY_FAILURE_SUFFIX)
            ]
        self.entry_report_path = entry_report_path
        super().__init__(
            f"scheduled entry failed (entry_report_path={entry_report_path})"
        )


def _scheduled_entry_failure_context_from_report_path(
    report_path: str,
) -> dict[str, object]:
    if report_path in _SCHEDULED_ENTRY_FAILURE_SENTINELS:
        return {
            "failureDetail": "scheduled entry failed",
            "entryReportPath": report_path,
        }
    if not _is_safe_entry_report_path(report_path):
        return {}
    return {
        "failureDetail": "scheduled entry failed",
        "entryReportPath": report_path,
    }


def _scheduled_entry_failure_diagnostic(
    error: Exception,
) -> tuple[bool, dict[str, object]]:
    for current in _iter_exception_diagnostic_errors(error):
        if not isinstance(current, _ScheduledEntryStepError):
            continue
        report_path = current.entry_report_path
        context = _scheduled_entry_failure_context_from_report_path(report_path)
        if context:
            return True, context
        return True, {}
    return False, {}


def _scheduled_entry_failure_upload_path(error: Exception) -> str | None:
    for current in _iter_exception_diagnostic_errors(error):
        if not isinstance(current, _ScheduledEntryStepError):
            continue
        report_path = current.entry_report_path
        if _is_safe_entry_report_path(report_path):
            return report_path
    return None


def _iter_exception_diagnostic_errors(error: BaseException) -> list[BaseException]:
    errors: list[BaseException] = []
    pending: deque[BaseException] = deque([error])
    seen: set[int] = set()
    while pending:
        current = pending.popleft()
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        errors.append(current)

        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None and not current.__suppress_context__:
            pending.append(current.__context__)
    return errors


def _iter_exception_diagnostic_messages(error: BaseException) -> list[str]:
    messages: list[str] = []
    for current in _iter_exception_diagnostic_errors(error):
        message = str(current)
        if message:
            messages.append(message)
        for note in getattr(current, "__notes__", ()):
            note_text = str(note)
            if note_text:
                messages.append(note_text)
    return messages


def _is_scheduled_entry_failure_log_boundary_char(char: str) -> bool:
    category = unicodedata.category(char)
    return char.isspace() or category.startswith("C") or category.startswith("Z")


def _strip_scheduled_entry_failure_log_boundaries(message: str) -> str:
    start = 0
    end = len(message)
    while start < end and _is_scheduled_entry_failure_log_boundary_char(message[start]):
        start += 1
    while end > start and _is_scheduled_entry_failure_log_boundary_char(
        message[end - 1]
    ):
        end -= 1
    return message[start:end]


def _normalize_log_char_for_entry_report_detection(char: str) -> str:
    normalized = unicodedata.normalize("NFKC", char)
    return "".join(
        "/"
        if normalized_char in _ENTRY_REPORT_PATH_SLASH_LIKE_CHARS
        else normalized_char
        for normalized_char in normalized
    )


def _normalized_text_with_original_offsets(message: str) -> tuple[str, list[int]]:
    normalized_parts: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(message):
        normalized_char = _normalize_log_char_for_entry_report_detection(char)
        normalized_parts.append(normalized_char)
        offsets.extend([index] * len(normalized_char))
    return "".join(normalized_parts), offsets


def _original_offset(
    offsets: list[int], normalized_offset: int, *, fallback: int
) -> int:
    if normalized_offset >= len(offsets):
        return fallback
    return offsets[normalized_offset]


def _original_end_offset(
    offsets: list[int], normalized_offset: int, *, fallback: int
) -> int:
    if normalized_offset <= 0:
        return 0
    if normalized_offset > len(offsets):
        return fallback
    return offsets[normalized_offset - 1] + 1


def _is_scheduled_entry_failure_log_message(message: str) -> bool:
    normalized, _offsets = _normalized_text_with_original_offsets(message)
    return _SCHEDULED_ENTRY_FAILURE_TOKEN_PATTERN.search(normalized) is not None


def _entry_report_label_value_end(message: str, value_start: int) -> int:
    entry_suffix_start = message.lower().find(_ENTRY_REPORT_JSON_SUFFIX, value_start)
    if entry_suffix_start >= 0:
        entry_suffix_end = entry_suffix_start + len(_ENTRY_REPORT_JSON_SUFFIX)
        value_end = message.find(_SCHEDULED_ENTRY_FAILURE_SUFFIX, entry_suffix_end)
        return len(message) if value_end < 0 else value_end

    value_end = message.find(_SCHEDULED_ENTRY_FAILURE_SUFFIX, value_start)
    return len(message) if value_end < 0 else value_end


def _redact_entry_report_path_labels(message: str) -> tuple[str, bool]:
    normalized, offsets = _normalized_text_with_original_offsets(message)
    parts: list[str] = []
    redacted = False
    cursor = 0

    for match in _ENTRY_REPORT_PATH_LABEL_PATTERN.finditer(normalized):
        label_start = _original_offset(offsets, match.start(), fallback=len(message))
        value_start = _original_offset(offsets, match.end(), fallback=len(message))
        if label_start < cursor:
            continue

        value_end = _entry_report_label_value_end(message, value_start)

        report_path = message[value_start:value_end]
        report_hint = _scheduled_entry_report_hint(report_path)
        parts.append(message[cursor:value_start])
        parts.append(report_hint)
        redacted = redacted or report_hint == "unsafe"
        cursor = value_end

    parts.append(message[cursor:])
    return "".join(parts), redacted


def _safe_entry_report_path_after_trimming_token_closers(candidate: str) -> bool:
    trimmed = candidate.rstrip(_SCHEDULED_ENTRY_FAILURE_SUFFIX)
    return trimmed != candidate and _is_safe_entry_report_path(trimmed)


def _redact_unsafe_entry_report_path_tokens(message: str) -> tuple[str, bool]:
    normalized, offsets = _normalized_text_with_original_offsets(message)
    parts: list[str] = []
    redacted = False
    cursor = 0

    for match in _ENTRY_REPORT_PATH_TOKEN_PATTERN.finditer(normalized):
        candidate_start = _original_offset(
            offsets,
            match.start(),
            fallback=len(message),
        )
        candidate_end = _original_end_offset(
            offsets,
            match.end(),
            fallback=len(message),
        )
        if candidate_start < cursor:
            continue
        candidate = message[candidate_start:candidate_end]
        if _scheduled_entry_report_hint(
            candidate
        ) != "unsafe" or _safe_entry_report_path_after_trimming_token_closers(
            candidate
        ):
            continue
        parts.append(message[cursor:candidate_start])
        parts.append("unsafe")
        redacted = True
        cursor = candidate_end

    parts.append(message[cursor:])
    return "".join(parts), redacted


def _scheduled_entry_failure_log_message_from_message(message: str) -> str | None:
    normalized = _strip_scheduled_entry_failure_log_boundaries(message)
    if not _is_scheduled_entry_failure_log_message(normalized):
        return None

    sanitized, label_redacted = _redact_entry_report_path_labels(normalized)
    sanitized, token_redacted = _redact_unsafe_entry_report_path_tokens(sanitized)
    redacted = label_redacted or token_redacted

    normalized_lower = normalized.lower()
    for prefix in _SCHEDULED_ENTRY_FAILURE_LOG_PREFIXES:
        if normalized_lower.startswith(prefix) and normalized.endswith(
            _SCHEDULED_ENTRY_FAILURE_SUFFIX
        ):
            return sanitized

    if redacted:
        if "entry_report_path=unsafe" not in sanitized:
            sanitized = f"{sanitized} entry_report_path=unsafe"
        return sanitized
    return None


def _scheduled_entry_failure_log_message(error: Exception) -> str | None:
    messages = _iter_exception_diagnostic_messages(error)
    for message in messages:
        safe_message = _scheduled_entry_failure_log_message_from_message(message)
        if safe_message is not None:
            return safe_message
    if not any(
        _is_scheduled_entry_failure_log_message(message) for message in messages
    ):
        return None
    for message in messages:
        sanitized = _redact_entry_report_path_references(message)
        if sanitized != message:
            if _is_scheduled_entry_failure_log_message(sanitized):
                return sanitized
            return f"{_SCHEDULED_ENTRY_FAILURE_TOKEN} {sanitized}"
    return None


def _redact_entry_report_path_references(message: str) -> str:
    sanitized, _token_redacted = _redact_unsafe_entry_report_path_tokens(message)
    label_sanitized, label_redacted = _redact_entry_report_path_labels(sanitized)
    return label_sanitized if label_redacted else sanitized


def _redact_scheduled_entry_traceback_message(message: str) -> str:
    redacted = _redact_entry_report_path_references(message)
    if redacted != message and _is_scheduled_entry_failure_log_message(redacted):
        return redacted
    return _SCHEDULED_ENTRY_TRACEBACK_REDACTION


def _safe_exception_traceback_message(
    error: BaseException, *, redact_entry_report_paths: bool
) -> str:
    message = str(error)
    safe_message = _scheduled_entry_failure_log_message_from_message(message)
    if safe_message is not None:
        return safe_message
    if redact_entry_report_paths:
        return _redact_scheduled_entry_traceback_message(message)
    return message


def _new_sanitized_exception_value(
    error_type: type[BaseException], message: str
) -> BaseException:
    try:
        return error_type(message)
    except Exception:
        return RuntimeError(f"{error_type.__name__}: {message}")


def _new_sanitized_exception_group(
    error_type: type[BaseException],
    message: str,
    exceptions: tuple[BaseException, ...],
) -> BaseException:
    try:
        return error_type(message, exceptions)
    except Exception:
        return BaseExceptionGroup(message, exceptions)


def _safe_exception_note(note_text: str, *, redact_entry_report_paths: bool) -> str:
    safe_note = _scheduled_entry_failure_log_message_from_message(note_text)
    if safe_note is not None:
        return safe_note
    if redact_entry_report_paths:
        return _redact_scheduled_entry_traceback_message(note_text)
    return note_text


def _clone_exception_for_sanitized_traceback(
    error: BaseException,
    seen: set[int] | None = None,
    *,
    redact_entry_report_paths: bool = False,
) -> BaseException:
    if seen is None:
        seen = set()
    error_id = id(error)
    if error_id in seen:
        return RuntimeError(f"{type(error).__name__}: <cycle>")
    seen.add(error_id)

    safe_message = _safe_exception_traceback_message(
        error,
        redact_entry_report_paths=redact_entry_report_paths,
    )
    if isinstance(error, BaseExceptionGroup):
        child_exceptions = tuple(
            _clone_exception_for_sanitized_traceback(
                child,
                seen,
                redact_entry_report_paths=redact_entry_report_paths,
            )
            for child in error.exceptions
        )
        sanitized = _new_sanitized_exception_group(
            type(error), safe_message, child_exceptions
        ).with_traceback(error.__traceback__)
    else:
        sanitized = _new_sanitized_exception_value(
            type(error), safe_message
        ).with_traceback(error.__traceback__)
    for note in getattr(error, "__notes__", ()):
        sanitized.add_note(
            _safe_exception_note(
                str(note),
                redact_entry_report_paths=redact_entry_report_paths,
            )
        )

    if error.__cause__ is not None:
        sanitized.__cause__ = _clone_exception_for_sanitized_traceback(
            error.__cause__,
            seen,
            redact_entry_report_paths=redact_entry_report_paths,
        )
    if error.__context__ is not None and not error.__suppress_context__:
        sanitized.__context__ = _clone_exception_for_sanitized_traceback(
            error.__context__,
            seen,
            redact_entry_report_paths=redact_entry_report_paths,
        )
    sanitized.__suppress_context__ = error.__suppress_context__
    return sanitized


def _scheduled_entry_failure_exc_info(
    error: Exception, safe_log_message: str
) -> tuple[type[BaseException], BaseException, TracebackType | None]:
    sanitized_error = _clone_exception_for_sanitized_traceback(
        error,
        redact_entry_report_paths=bool(safe_log_message),
    )
    return (type(error), sanitized_error, error.__traceback__)


def _is_safe_entry_report_path(report_path: str) -> bool:
    if (
        not report_path
        or "\\" in report_path
        or unicodedata.normalize("NFKC", report_path) != report_path
        or any(char not in _SAFE_ENTRY_REPORT_PATH_CHARS for char in report_path)
        or any(
            (category := unicodedata.category(char)).startswith("C")
            or category in {"Zl", "Zp"}
            for char in report_path
        )
    ):
        return False
    path = PurePosixPath(report_path)
    if report_path != path.as_posix():
        return False
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) >= 2
        and path.parts[0] == "reports"
        and path.name.endswith(".entry.json")
    )


def _scheduled_entry_report_hint(report_path: str | None) -> str:
    if report_path is None:
        return "not produced"
    if report_path in _SCHEDULED_ENTRY_FAILURE_SENTINELS:
        return report_path
    if _is_safe_entry_report_path(report_path):
        return report_path
    return "unsafe"


def _require_single_report_path(paths: list[str], *, report_type: str) -> str:
    if len(paths) != 1:
        raise RuntimeError(
            f"scheduled {report_type} step reported {len(paths)} artifact paths"
        )
    return paths[0]


@contextmanager
def _suppress_scheduled_step_side_effects() -> Iterator[None]:
    with (
        suppress_config_env_keys(_SCHEDULED_PIPELINE_SUPPRESSED_ENV_KEYS),
        suppress_report_uploads(),
    ):
        yield


class DefaultScheduledPipeline:
    def _run_scan_step(self, *, market: str, report_date: str) -> str:
        buy_report_paths: list[str] = []
        _LOGGER.info(
            "scheduled AI brief pipeline step started "
            "step=scan market=%s report_date=%s",
            market,
            report_date,
        )
        with _suppress_scheduled_step_side_effects():
            scan_status = run_scan(
                limit=None,
                watchlist_path=None,
                provider="kis",
                universe="both",
                markets=market,
                report_path_callback=buy_report_paths.append,
            )
        if scan_status != 0:
            raise RuntimeError("scheduled scan failed")
        buy_report_path = _require_single_report_path(
            buy_report_paths, report_type="buy"
        )
        _LOGGER.info(
            "scheduled AI brief pipeline step completed "
            "step=scan market=%s report_date=%s report_path=%s",
            market,
            report_date,
            buy_report_path,
        )
        return buy_report_path

    def _run_holdings_export_step(self, *, market: str, report_date: str) -> str:
        holdings_path = (
            Path("data") / "scheduler" / (f"holdings.{market}.{report_date}.yaml")
        )
        holdings_path_str = holdings_path.as_posix()
        _LOGGER.info(
            "scheduled AI brief pipeline step started "
            "step=holdings_export market=%s report_date=%s output_path=%s",
            market,
            report_date,
            holdings_path_str,
        )
        export_active_holdings_snapshot(
            output_path=holdings_path,
            config=SupabaseHoldingsExportConfig.from_env(),
        )
        _LOGGER.info(
            "scheduled AI brief pipeline step completed "
            "step=holdings_export market=%s report_date=%s output_path=%s",
            market,
            report_date,
            holdings_path_str,
        )
        return holdings_path_str

    def _run_entry_step(
        self,
        *,
        market: str,
        report_date: str,
        buy_report_path: str,
        holdings_path: str,
    ) -> str:
        entry_report_paths: list[str] = []
        _LOGGER.info(
            "scheduled AI brief pipeline step started "
            "step=entry market=%s report_date=%s buy_report_path=%s holdings_path=%s",
            market,
            report_date,
            buy_report_path,
            holdings_path,
        )
        with _suppress_scheduled_step_side_effects():
            entry_status = run_entry(
                buy_report_path=buy_report_path,
                provider="kis",
                mode="PRE_OPEN",
                market=market,
                holdings_path=holdings_path,
                upload=False,
                report_path_callback=entry_report_paths.append,
            )
        if entry_status != 0:
            report_hint = _scheduled_entry_report_hint(
                entry_report_paths[-1] if entry_report_paths else None
            )
            raise _ScheduledEntryStepError(report_hint)
        entry_report_path = _require_single_report_path(
            entry_report_paths, report_type="entry"
        )
        _LOGGER.info(
            "scheduled AI brief pipeline step completed "
            "step=entry market=%s report_date=%s report_path=%s",
            market,
            report_date,
            entry_report_path,
        )
        return entry_report_path

    def run(
        self,
        *,
        market: str,
        session_date: str,
        report_date: str,
        source_provider: str | None,
        model_provider: str,
        dry_run: bool,
        model_deadline_remaining_seconds: float | None = None,
        model_deadline_at: dt.datetime | None = None,
        source_api_url: str | None = None,
        source_provider_chain: tuple[str, ...] | None = None,
    ) -> ScheduledPipelineResult:
        del session_date, dry_run
        buy_report_path = self._run_scan_step(
            market=market,
            report_date=report_date,
        )
        holdings_path_str = self._run_holdings_export_step(
            market=market,
            report_date=report_date,
        )
        entry_guard = _default_guard_snapshot(market, dt.datetime.now(dt.UTC))
        if not _guard_allows_pipeline(entry_guard):
            raise RuntimeError("scheduled pre-open guard failed before entry")
        entry_report_path = self._run_entry_step(
            market=market,
            report_date=report_date,
            buy_report_path=buy_report_path,
            holdings_path=holdings_path_str,
        )
        ai_brief_report_paths: list[str] = []
        source_provider_chain_value = (
            ",".join(source_provider_chain) if source_provider_chain else None
        )
        _LOGGER.info(
            "scheduled AI brief pipeline step started "
            "step=ai_brief market=%s report_date=%s entry_report_path=%s "
            "source_provider=%s source_provider_chain=%s model_provider=%s",
            market,
            report_date,
            entry_report_path,
            source_provider or "",
            source_provider_chain_value or "",
            model_provider,
        )
        with _suppress_scheduled_step_side_effects():
            ai_status = run_ai_brief(
                entry_report_path=entry_report_path,
                buy_report_path=buy_report_path,
                market=market,
                model_provider=model_provider,
                model_name="fake-ai-brief-v1",
                model_deadline_remaining_seconds=model_deadline_remaining_seconds,
                model_deadline_at=model_deadline_at,
                source_provider=source_provider,
                source_provider_chain=source_provider_chain_value,
                source_api_url=source_api_url,
                report_date=report_date,
                upload=False,
                report_path_callback=ai_brief_report_paths.append,
            )
        if ai_status != 0:
            raise RuntimeError("scheduled ai-brief failed")
        ai_brief_report_path = _require_single_report_path(
            ai_brief_report_paths,
            report_type="ai-brief",
        )
        quality_result = evaluate_ai_brief_recommendation_report(
            entry_report_path=entry_report_path,
            ai_brief_report_path=ai_brief_report_path,
            market=market,
        )
        if quality_result.status == "FAIL":
            issue_summary = "; ".join(
                f"{issue.code}: {issue.message}" for issue in quality_result.issues[:3]
            )
            raise RuntimeError(
                "scheduled ai-brief quality gate failed"
                + (f": {issue_summary}" if issue_summary else "")
            )
        _LOGGER.info(
            "scheduled AI brief pipeline step completed "
            "step=ai_brief market=%s report_date=%s report_path=%s",
            market,
            report_date,
            ai_brief_report_path,
        )
        return ScheduledPipelineResult(ai_brief_report_path=ai_brief_report_path)


class DefaultScheduledStorage:
    def __init__(self, config: SupabaseStorageConfig) -> None:
        self._config = config

    @classmethod
    def from_env(cls) -> DefaultScheduledStorage:
        config = _load_storage_config(required=True)
        if config is None:
            raise SchedulerStateError("Supabase storage config is required")
        return cls(config)

    def _upload_report(
        self, report_path: str, *, report_date: str, run_type: str
    ) -> str:
        return upload_report_artifact(
            local_path=report_path,
            run_type=run_type,
            report_date=dt.date.fromisoformat(report_date),
            config=self._config,
        )

    def upload_ai_brief(self, report_path: str, *, report_date: str) -> str:
        return self._upload_report(
            report_path,
            report_date=report_date,
            run_type="ai-brief",
        )

    def upload_entry_report(self, report_path: str, *, report_date: str) -> str:
        return self._upload_report(
            report_path,
            report_date=report_date,
            run_type="entry",
        )

    def upload_ai_brief_skip(self, report_path: str, *, report_date: str) -> str:
        return self._upload_report(
            report_path,
            report_date=report_date,
            run_type="ai-brief-skip",
        )

    def download_json(self, storage_key: str) -> dict[str, object]:
        quoted_key = quote(storage_key, safe="/")
        url = f"{self._config.url}/storage/v1/object/{self._config.bucket}/{quoted_key}"
        response = requests.get(
            url,
            headers=_auth_headers(self._config),
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(f"failed to download '{storage_key}': {response.text}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"storage object '{storage_key}' must be JSON object")
        return payload

    def list_ai_brief_report_index(self, *, report_date: str) -> list[str]:
        query = urlencode(
            {
                "select": "report_key",
                "report_type": "eq.ai-brief",
                "report_date": f"eq.{report_date}",
                "order": "generated_at.desc,created_at.desc",
                "limit": "10",
            }
        )
        url = f"{self._config.url}/rest/v1/report_index?{query}"
        response = requests.get(
            url,
            headers={**_auth_headers(self._config), "Accept": "application/json"},
            timeout=self._config.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(
                "failed to list report_index ai-brief candidates: "
                f"HTTP {response.status_code} {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("report_index response must be a JSON array")

        storage_keys: list[str] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            report_key = row.get("report_key")
            if isinstance(report_key, str) and report_key.strip():
                storage_keys.append(report_key.strip())
        return storage_keys


class DefaultScheduledNotifier:
    def require_telegram(self) -> None:
        if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
            raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")

    def _post_telegram_message(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        bot_token = str(os.environ["TELEGRAM_BOT_TOKEN"])
        chat_id = str(os.environ["TELEGRAM_CHAT_ID"])
        data = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=data,
            timeout=10,
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Telegram send failed: HTTP {response.status_code}")

    def send_schedule(self, *, report: dict[str, object], storage_key: str) -> None:
        self.require_telegram()
        text = build_ai_brief_telegram_report_text(
            report=report,
            run_url=os.getenv("SAB_RUN_URL", ""),
            storage_key=storage_key,
        )
        for part in split_telegram_message_text(text):
            self._post_telegram_message(part, parse_mode="HTML")
        slack_webhook_url = str(os.getenv("SLACK_WEBHOOK_URL") or "").strip()
        if slack_webhook_url:
            slack_text = build_ai_brief_slack_summary_text(
                report=report,
                repo=os.getenv("GITHUB_REPOSITORY", "local"),
                run_url=os.getenv("SAB_RUN_URL", ""),
                storage_key=storage_key,
            )
            try:
                response = requests.post(
                    slack_webhook_url,
                    json={"text": slack_text},
                    timeout=10,
                )
                if response.status_code >= 300:
                    _LOGGER.warning(
                        "Slack webhook returned HTTP %s for scheduled AI brief",
                        response.status_code,
                    )
            except Exception as exc:
                _LOGGER.warning("Slack webhook failed for scheduled AI brief: %s", exc)

    def send_late_alert(self, *, reason: str, context: dict[str, object]) -> None:
        self.require_telegram()
        text = "\n".join(
            [
                "[SAB][ai-brief][late-alert]",
                f"reason={reason}",
                *[f"{key}={value}" for key, value in sorted(context.items())],
            ]
        )
        self._post_telegram_message(text)


def run_scheduled_ai_brief(
    *,
    request: ScheduledAiBriefRequest,
    guard_only: bool = False,
) -> int:
    now = dt.datetime.now(dt.UTC)
    market = _normalize_market(request.market)
    schedule_role = _normalize_role(request.schedule_role, field_name="schedule_role")
    if guard_only:
        return (
            0
            if _is_within_role_window(
                market=market, schedule_role=schedule_role, now=now
            )
            else 75
        )

    runner = ScheduledAiBriefRunner(
        state_store=SupabaseRuntimeStateClient.from_env(),
        pipeline=DefaultScheduledPipeline(),
        storage=DefaultScheduledStorage.from_env(),
        notifier=DefaultScheduledNotifier(),
    )
    result = runner.run(request)
    print(json.dumps({"status": result.status, "storage_key": result.storage_key}))
    return 0 if result.status not in _FAILED_STATUSES else 1


__all__ = [
    "GuardSnapshot",
    "ScheduledAiBriefRequest",
    "ScheduledAiBriefResult",
    "ScheduledAiBriefRunner",
    "ScheduledPipelineResult",
    "build_attempt_id",
    "run_scheduled_ai_brief",
]
