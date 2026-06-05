from __future__ import annotations

import logging
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"
MAX_LOG_VALUE_LENGTH = 500
_MAX_CONTAINER_ITEMS = 20
_MAX_DEPTH = 4

_SAFE_KEY_NAMES = {
    "cache_key",
    "lock_key",
    "report_key",
    "state_key",
    "storage_key",
}
_SENSITIVE_KEY_NAMES = {
    "apikey",
    "api_key",
    "app_key",
    "app_secret",
    "authorization",
    "password",
    "secret",
    "service_role_key",
    "supabase_secret_key",
    "token",
}
_SENSITIVE_KEY_PARTS = {"password", "secret", "token"}
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)(authorization[\s:=]+bearer[\s:=]+)([^\s,'\"}]+)"),
    re.compile(
        r"(?i)(api[_-]?key|app[_-]?secret|access[_-]?token|refresh[_-]?token|password|secret)([\s:=]+)([^\s,'\"}]+)"
    ),
    re.compile(r"(?i)(sb_secret_)[A-Za-z0-9_\-]+"),
)

_BASE_LOG_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="sab",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
) | {"asctime", "message"}


def make_run_id(operation: str) -> str:
    safe_operation = re.sub(r"[^a-zA-Z0-9_-]+", "-", operation.strip().lower())
    return f"{safe_operation or 'run'}-{uuid.uuid4().hex[:12]}"


def current_run_id(operation: str, *, env_name: str = "SAB_RUN_ID") -> str:
    existing = os.getenv(env_name, "").strip()
    return existing or make_run_id(operation)


def is_sensitive_log_field(field_name: str) -> bool:
    normalized = field_name.strip().lower().replace("-", "_").replace(".", "_")
    if normalized in _SAFE_KEY_NAMES:
        return False
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    parts = {part for part in normalized.split("_") if part}
    if parts & _SENSITIVE_KEY_PARTS:
        return True
    return normalized.endswith("_key") and normalized not in _SAFE_KEY_NAMES


def sanitize_log_text(value: str) -> str:
    sanitized = value
    sanitized = _SENSITIVE_TEXT_PATTERNS[0].sub(r"\1" + REDACTED, sanitized)
    sanitized = _SENSITIVE_TEXT_PATTERNS[1].sub(r"\1\2" + REDACTED, sanitized)
    sanitized = _SENSITIVE_TEXT_PATTERNS[2].sub(r"\1" + REDACTED, sanitized)
    if len(sanitized) > MAX_LOG_VALUE_LENGTH:
        return sanitized[: MAX_LOG_VALUE_LENGTH - 1] + "..."
    return sanitized


def sanitize_log_value(field_name: str, value: Any, *, _depth: int = 0) -> Any:
    if is_sensitive_log_field(field_name):
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return sanitize_log_text(value)
    if _depth >= _MAX_DEPTH:
        return sanitize_log_text(str(value))
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_CONTAINER_ITEMS:
                sanitized["truncated"] = True
                break
            key_text = str(key)
            sanitized[key_text] = sanitize_log_value(key_text, item, _depth=_depth + 1)
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        items = [
            sanitize_log_value(field_name, item, _depth=_depth + 1)
            for item in list(value)[:_MAX_CONTAINER_ITEMS]
        ]
        if len(value) > _MAX_CONTAINER_ITEMS:
            items.append({"truncated": True})
        return items
    return sanitize_log_text(str(value))


def structured_log_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in sorted(record.__dict__.items()):
        if key in _BASE_LOG_RECORD_ATTRS or key.startswith("_"):
            continue
        fields[key] = sanitize_log_value(key, value)
    return fields
