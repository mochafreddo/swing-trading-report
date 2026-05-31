from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from ..ai_brief_eval_common import ALLOWED_MARKETS, parse_iso_offset_datetime
from ..utils.atomic_io import advisory_path_lock, atomic_write_json
from .paths import ensure_dir, next_report_path

_ARTIFACT_SCHEMA = "sab.ai_brief_skip.v1"
_REPORT_TYPE = "ai_brief_skip"

AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED = "RUNTIME_GUARD_SKIPPED"
AI_BRIEF_SKIP_REASON_AFTER_PRE_OPEN_WINDOW = "scheduled_run_after_pre_open_window"
AI_BRIEF_SKIP_REASON_NON_TRADING_SESSION = "non_trading_session"
AI_BRIEF_SKIP_REASON_SESSION_STATE_MISMATCH = "session_state_mismatch"

_AI_BRIEF_SKIP_STATES = frozenset({AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED})
_AI_BRIEF_SKIP_REASONS = frozenset(
    {
        AI_BRIEF_SKIP_REASON_AFTER_PRE_OPEN_WINDOW,
        AI_BRIEF_SKIP_REASON_NON_TRADING_SESSION,
        AI_BRIEF_SKIP_REASON_SESSION_STATE_MISMATCH,
    }
)


class AiBriefSkipValidationError(ValueError):
    """Raised when an AI Brief skip artifact violates the JSON contract."""


def _offset_iso(now: dt.datetime | None = None) -> str:
    if now is None:
        aware = dt.datetime.now().astimezone()
    elif now.tzinfo is None:
        local_tz = dt.datetime.now().astimezone().tzinfo or dt.UTC
        aware = now.replace(tzinfo=local_tz)
    else:
        aware = now
    return aware.replace(microsecond=0).isoformat(timespec="seconds")


def _parse_offset_datetime(value: object, *, field_name: str) -> dt.datetime:
    try:
        return parse_iso_offset_datetime(
            value,
            field_name=field_name,
            empty_message=f"{field_name} must be an offset datetime",
        )
    except ValueError as exc:
        raise AiBriefSkipValidationError(str(exc)) from exc


def _require_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = str(payload.get(field_name) or "").strip()
    if not value:
        raise AiBriefSkipValidationError(f"{field_name} is required")
    return value


def _validate_calendar_date(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    try:
        return dt.date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise AiBriefSkipValidationError(
            f"{field_name} must be a valid YYYY-MM-DD date"
        ) from exc


def _infer_skip_reason(
    *,
    session_state: str,
    expected_state: str,
    trading_session: bool,
) -> str:
    if not trading_session:
        return AI_BRIEF_SKIP_REASON_NON_TRADING_SESSION
    if (
        expected_state.strip().upper() == "PRE_OPEN"
        and session_state.strip().upper() == "INTRADAY"
    ):
        return AI_BRIEF_SKIP_REASON_AFTER_PRE_OPEN_WINDOW
    return AI_BRIEF_SKIP_REASON_SESSION_STATE_MISMATCH


def validate_ai_brief_skip_artifact(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != _ARTIFACT_SCHEMA:
        raise AiBriefSkipValidationError(f"schema must be {_ARTIFACT_SCHEMA!r}")
    if payload.get("type") != _REPORT_TYPE:
        raise AiBriefSkipValidationError(f"type must be {_REPORT_TYPE!r}")

    _parse_offset_datetime(payload.get("generated_at"), field_name="generated_at")
    report_date = _validate_calendar_date(
        payload.get("report_date"), field_name="report_date"
    )
    session_date = _validate_calendar_date(
        payload.get("session_date"), field_name="session_date"
    )
    if report_date != session_date:
        raise AiBriefSkipValidationError("report_date must match session_date")

    market = str(payload.get("market") or "").strip().upper()
    if market not in ALLOWED_MARKETS:
        raise AiBriefSkipValidationError(
            f"market must be one of {sorted(ALLOWED_MARKETS)}"
        )

    skip_state = str(payload.get("skip_state") or "").strip()
    if skip_state not in _AI_BRIEF_SKIP_STATES:
        raise AiBriefSkipValidationError(
            f"skip_state must be one of {sorted(_AI_BRIEF_SKIP_STATES)}"
        )
    skip_reason = str(payload.get("skip_reason") or "").strip()
    if skip_reason not in _AI_BRIEF_SKIP_REASONS:
        raise AiBriefSkipValidationError(
            f"skip_reason must be one of {sorted(_AI_BRIEF_SKIP_REASONS)}"
        )

    _require_text(payload, "session_state")
    _require_text(payload, "expected_state")
    _require_text(payload, "local_time")
    _require_text(payload, "source")
    if not isinstance(payload.get("trading_session"), bool):
        raise AiBriefSkipValidationError("trading_session must be a boolean")
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise AiBriefSkipValidationError("summary must be an object")


def write_ai_brief_skip_report(
    *,
    report_dir: str,
    market: str,
    session_date: str,
    session_state: str,
    expected_state: str,
    trading_session: bool,
    local_time: str,
    run_url: str,
    source: str,
    now: dt.datetime | None = None,
) -> str:
    ensure_dir(report_dir)
    normalized_session_date = _validate_calendar_date(
        session_date, field_name="session_date"
    )
    normalized_market = market.strip().upper()
    generated_at = _offset_iso(now)
    normalized_session_state = session_state.strip().upper()
    normalized_expected_state = expected_state.strip().upper()
    skip_reason = _infer_skip_reason(
        session_state=normalized_session_state,
        expected_state=normalized_expected_state,
        trading_session=trading_session,
    )
    summary = {
        "skip_state": AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
        "skip_reason": skip_reason,
        "session_state": normalized_session_state,
        "expected_state": normalized_expected_state,
        "trading_session": trading_session,
    }
    payload: dict[str, Any] = {
        "schema": _ARTIFACT_SCHEMA,
        "type": _REPORT_TYPE,
        "generated_at": generated_at,
        "report_date": normalized_session_date,
        "market": normalized_market,
        "skip_state": AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
        "skip_reason": skip_reason,
        "session_date": normalized_session_date,
        "session_state": normalized_session_state,
        "expected_state": normalized_expected_state,
        "trading_session": trading_session,
        "local_time": local_time.strip(),
        "run_url": run_url.strip(),
        "source": source.strip(),
        "summary": summary,
    }
    validate_ai_brief_skip_artifact(payload)

    lock_path = f"{report_dir}/.ai-brief-skip.report.lock"
    with advisory_path_lock(lock_path):
        out_path = next_report_path(
            report_dir,
            normalized_session_date,
            "ai-brief-skip",
        )
        atomic_write_json(out_path, payload, ensure_ascii=False, indent=2)

    return out_path


__all__ = [
    "AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED",
    "AiBriefSkipValidationError",
    "validate_ai_brief_skip_artifact",
    "write_ai_brief_skip_report",
]
