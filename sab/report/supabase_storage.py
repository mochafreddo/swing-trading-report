from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests  # type: ignore[import-untyped]

from .storage_key import build_report_storage_key

_DEFAULT_BUCKET = "reports"
_MAX_DUPLICATE_INDEX = 999


class SupabaseStorageError(RuntimeError):
    """Raised when Supabase Storage upload fails."""


class SupabaseStorageConfigError(SupabaseStorageError):
    """Raised when required Supabase Storage config is missing."""


class SupabaseStorageConflictError(SupabaseStorageError):
    """Raised when object path already exists in the bucket."""


@dataclass(frozen=True)
class SupabaseStorageConfig:
    url: str
    service_role_key: str
    bucket: str = _DEFAULT_BUCKET
    timeout_seconds: float = 10.0


def _is_github_actions() -> bool:
    return os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true"


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_value(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    return value


def _decode_jwt_payload(token: str) -> dict[str, object] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None

    payload_part = parts[1]
    padding = "=" * (-len(payload_part) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(payload_part + padding)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_supabase_api_key(*, key: str, source_name: str) -> None:
    if key.startswith("sb_publishable_"):
        raise SupabaseStorageConfigError(
            f"{source_name} is a publishable key. "
            "Use SUPABASE_SECRET_KEY (recommended) or legacy SUPABASE_SERVICE_ROLE_KEY."
        )

    payload = _decode_jwt_payload(key)
    if payload is None:
        return

    role = payload.get("role")
    if isinstance(role, str) and role.strip().lower() == "anon":
        raise SupabaseStorageConfigError(
            f"{source_name} has role=anon. "
            "Use SUPABASE_SECRET_KEY (recommended) or legacy SUPABASE_SERVICE_ROLE_KEY."
        )


def _load_storage_config(*, required: bool) -> SupabaseStorageConfig | None:
    url_raw = _env_value("SUPABASE_URL")
    secret_key_raw = _env_value("SUPABASE_SECRET_KEY")
    legacy_service_role_raw = _env_value("SUPABASE_SERVICE_ROLE_KEY")
    key_raw = secret_key_raw or legacy_service_role_raw
    bucket_raw = os.getenv("SUPABASE_REPORTS_BUCKET") or _DEFAULT_BUCKET

    if not url_raw or not key_raw:
        if required:
            raise SupabaseStorageConfigError(
                "SUPABASE_URL and one of SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY "
                "must be set for report upload"
            )
        return None

    source_name = (
        "SUPABASE_SECRET_KEY"
        if secret_key_raw is not None
        else "SUPABASE_SERVICE_ROLE_KEY"
    )
    _validate_supabase_api_key(key=key_raw, source_name=source_name)

    return SupabaseStorageConfig(
        url=url_raw.rstrip("/"),
        service_role_key=key_raw,
        bucket=bucket_raw,
    )


def _extract_report_date(local_path: str) -> dt.date:
    filename = Path(local_path).name
    match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if not match:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
        return dt.date.today()


def _auth_headers(config: SupabaseStorageConfig) -> dict[str, str]:
    return {
        "apikey": config.service_role_key,
        "authorization": f"Bearer {config.service_role_key}",
    }


def _response_message(response: requests.Response) -> str:
    text = response.text.strip()
    if text:
        return text
    return f"HTTP {response.status_code}"


def _is_not_found_response(response: requests.Response) -> bool:
    if response.status_code == 404:
        return True
    if response.status_code != 400:
        return False

    text = response.text.strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except ValueError:
        lowered = text.lower()
        return "not_found" in lowered or "not found" in lowered

    code = payload.get("code")
    if isinstance(code, str) and code.lower() == "not_found":
        return True
    message = payload.get("message")
    return isinstance(message, str) and "not found" in message.lower()


def _object_exists(
    *,
    config: SupabaseStorageConfig,
    key: str,
    session: requests.Session,
) -> bool:
    quoted_key = quote(key, safe="/")
    url = f"{config.url}/storage/v1/object/info/{config.bucket}/{quoted_key}"
    response = session.get(
        url,
        headers=_auth_headers(config),
        timeout=config.timeout_seconds,
    )
    if response.status_code == 200:
        return True
    if _is_not_found_response(response):
        return False
    raise SupabaseStorageError(
        f"failed to check existing object '{key}': {_response_message(response)}"
    )


def _is_conflict_response(response: requests.Response) -> bool:
    if response.status_code in {409}:
        return True
    if response.status_code != 400:
        return False
    lowered = response.text.lower()
    return "duplicate" in lowered or "already exists" in lowered


def _upload_json_payload(
    *,
    config: SupabaseStorageConfig,
    key: str,
    payload: bytes,
    session: requests.Session,
) -> None:
    quoted_key = quote(key, safe="/")
    url = f"{config.url}/storage/v1/object/{config.bucket}/{quoted_key}"
    headers = {
        **_auth_headers(config),
        "content-type": "application/json",
        "x-upsert": "false",
    }
    response = session.post(
        url,
        headers=headers,
        data=payload,
        timeout=config.timeout_seconds,
    )
    if response.status_code in {200, 201}:
        return
    if _is_conflict_response(response):
        raise SupabaseStorageConflictError(f"report object already exists for '{key}'")
    raise SupabaseStorageError(
        f"failed to upload report object '{key}': {_response_message(response)}"
    )


def upload_report_artifact(
    *,
    local_path: str,
    run_type: str,
    report_date: dt.date,
    config: SupabaseStorageConfig,
    session: requests.Session | None = None,
) -> str:
    payload = Path(local_path).read_bytes()

    active_session = session or requests.Session()
    should_close_session = session is None
    try:
        for duplicate_index in range(_MAX_DUPLICATE_INDEX + 1):
            key = build_report_storage_key(
                report_date=report_date,
                run_type=run_type,
                duplicate_index=duplicate_index,
            )
            if _object_exists(config=config, key=key, session=active_session):
                continue

            try:
                _upload_json_payload(
                    config=config,
                    key=key,
                    payload=payload,
                    session=active_session,
                )
            except SupabaseStorageConflictError:
                # Handle a race where another process uploads the same key after
                # our existence check and before upload.
                continue
            return key

        raise SupabaseStorageError(
            "failed to resolve report storage key: duplicate index exhausted"
        )
    finally:
        if should_close_session:
            active_session.close()


def maybe_upload_report_artifact(
    *,
    artifact_path: str,
    run_type: str,
    logger: logging.Logger,
) -> str | None:
    required = _is_github_actions()
    enabled = required or _env_flag("SAB_UPLOAD_REPORTS", default=False)
    if not enabled:
        return None

    config = _load_storage_config(required=required)
    if config is None:
        logger.info(
            "Supabase report upload skipped: "
            "SUPABASE_URL and SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY not set"
        )
        return None

    report_date = _extract_report_date(artifact_path)
    try:
        return upload_report_artifact(
            local_path=artifact_path,
            run_type=run_type,
            report_date=report_date,
            config=config,
        )
    except SupabaseStorageError:
        if required:
            raise
        logger.exception("Supabase report upload skipped due to upload error")
        return None


__all__ = [
    "SupabaseStorageConfig",
    "SupabaseStorageConfigError",
    "SupabaseStorageError",
    "maybe_upload_report_artifact",
    "upload_report_artifact",
]
