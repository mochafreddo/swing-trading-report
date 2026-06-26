from __future__ import annotations

import re
from typing import Final

__all__ = ["build_scheduled_state_key"]

_ALLOWED_PIPELINES: Final = frozenset({"scan", "sell", "ai-brief"})
_ALLOWED_SCOPES: Final = frozenset({"KR", "US", "MIXED"})
_UNSAFE_TOKEN_CHARS: Final = frozenset({":", "\n", "\r", "/", "\\"})
_SAFE_TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_.-]+$")


def _normalize_safe_token(value: str, *, field_name: str, lower: bool = False) -> str:
    raw_text = str(value or "")
    if any(char in raw_text for char in _UNSAFE_TOKEN_CHARS) or any(
        char.isspace() and char != " " for char in raw_text
    ):
        raise ValueError(f"{field_name} contains unsafe characters")
    text = raw_text.strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    if not _SAFE_TOKEN_RE.fullmatch(text):
        raise ValueError(f"{field_name} contains unsafe characters")
    return text.lower() if lower else text


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

    normalized_kind = _normalize_safe_token(kind, field_name="kind", lower=True)
    normalized_scope = _normalize_safe_token(scope, field_name="scope").upper()
    if normalized_scope not in _ALLOWED_SCOPES:
        raise ValueError("scope must be KR, US, or MIXED")
    if normalized_pipeline == "ai-brief" and normalized_scope == "MIXED":
        raise ValueError("ai-brief scope must be KR or US")
    has_runner_role = runner_role is not None
    has_attempt_id = attempt_id is not None
    if has_runner_role != has_attempt_id:
        raise ValueError("runner_role and attempt_id must be provided together")
    if (has_runner_role or has_attempt_id) and normalized_kind != "attempt":
        raise ValueError(
            "runner_role and attempt_id are only supported for attempt markers"
        )

    parts = [
        f"scheduled-{normalized_pipeline}",
        normalized_kind,
        normalized_scope,
        _normalize_safe_token(session_date, field_name="session_date"),
    ]
    if runner_role is not None:
        parts.append(_normalize_safe_token(runner_role, field_name="runner_role"))
    if attempt_id is not None:
        parts.append(_normalize_safe_token(attempt_id, field_name="attempt_id"))
    return ":".join(parts)
