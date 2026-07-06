from __future__ import annotations

import re
from typing import Final

__all__ = ["build_scheduled_state_key"]

_ALLOWED_PIPELINES: Final = frozenset({"scan", "sell", "ai-brief"})
_ALLOWED_SCOPES: Final = frozenset({"KR", "US", "MIXED"})
_ALLOWED_MULTI_SEGMENT_KINDS: Final = frozenset(
    {
        ("notification", "blocked-sent"),
        ("notification", "claim"),
        ("notification", "sent"),
    }
)
_UNSAFE_TOKEN_CHARS: Final = frozenset({":", "\n", "\r", "/", "\\"})
_SAFE_TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_.-]+$")


def _normalize_safe_token(value: str, *, field_name: str, lower: bool = False) -> str:
    raw_text = str(value or "")
    if not raw_text:
        raise ValueError(f"{field_name} must not be blank")
    if any(char in raw_text for char in _UNSAFE_TOKEN_CHARS) or not (
        _SAFE_TOKEN_RE.fullmatch(raw_text)
    ):
        raise ValueError(f"{field_name} contains unsafe characters")
    return raw_text.lower() if lower else raw_text


def _normalize_kind_parts(kind: str) -> tuple[str, ...]:
    raw_text = str(kind or "")
    if ":" not in raw_text:
        return (_normalize_safe_token(raw_text, field_name="kind", lower=True),)

    parts = tuple(
        _normalize_safe_token(part, field_name="kind", lower=True)
        for part in raw_text.split(":")
    )
    if parts not in _ALLOWED_MULTI_SEGMENT_KINDS:
        raise ValueError("kind contains unsafe characters")
    return parts


def build_scheduled_state_key(
    *,
    pipeline: str,
    kind: str,
    scope: str,
    session_date: str,
    runner_role: str | None = None,
    attempt_id: str | None = None,
) -> str:
    normalized_pipeline = _normalize_safe_token(
        pipeline, field_name="pipeline", lower=True
    )
    if normalized_pipeline not in _ALLOWED_PIPELINES:
        raise ValueError("pipeline must be scan, sell, or ai-brief")

    normalized_kind_parts = _normalize_kind_parts(kind)
    normalized_kind = ":".join(normalized_kind_parts)
    normalized_scope = _normalize_safe_token(scope, field_name="scope").upper()
    if normalized_scope not in _ALLOWED_SCOPES:
        raise ValueError("scope must be KR, US, or MIXED")
    if normalized_pipeline == "ai-brief" and normalized_scope == "MIXED":
        raise ValueError("ai-brief scope must be KR or US")
    has_runner_role = runner_role is not None
    has_attempt_id = attempt_id is not None
    if has_runner_role != has_attempt_id:
        raise ValueError("runner_role and attempt_id must be provided together")
    if normalized_kind == "attempt" and not (has_runner_role and has_attempt_id):
        raise ValueError("attempt markers require runner_role and attempt_id")
    if (has_runner_role or has_attempt_id) and normalized_kind != "attempt":
        raise ValueError(
            "runner_role and attempt_id are only supported for attempt markers"
        )

    parts = [
        f"scheduled-{normalized_pipeline}",
        *normalized_kind_parts,
        normalized_scope,
        _normalize_safe_token(session_date, field_name="session_date"),
    ]
    if runner_role is not None:
        parts.append(_normalize_safe_token(runner_role, field_name="runner_role"))
    if attempt_id is not None:
        parts.append(_normalize_safe_token(attempt_id, field_name="attempt_id"))
    return ":".join(parts)
