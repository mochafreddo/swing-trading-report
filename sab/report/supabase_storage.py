from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests  # type: ignore[import-untyped]

from ..env_loader import env_flag
from .storage_key import (
    REPORT_RUN_TYPE_PATTERN,
    build_report_storage_key,
    normalize_report_run_type,
)

_DEFAULT_BUCKET = "reports"
_MAX_DUPLICATE_INDEX = 999
_REPORT_INDEX_UPSERT_RETRY_ATTEMPTS = 3
_REPORT_INDEX_UPSERT_RETRY_BASE_SECONDS = 0.2
_REPORT_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
_REPORT_KEY_PATTERN = re.compile(
    rf"\d{{4}}/\d{{2}}/\d{{4}}-\d{{2}}-\d{{2}}(?:-(\d+))?\.{REPORT_RUN_TYPE_PATTERN}\.json$"
)


class SupabaseStorageError(RuntimeError):
    """Raised when Supabase Storage upload fails."""


class SupabaseStorageConfigError(SupabaseStorageError):
    """Raised when required Supabase Storage config is missing."""


class SupabaseStorageConflictError(SupabaseStorageError):
    """Raised when object path already exists in the bucket."""


class SupabaseReportIndexError(SupabaseStorageError):
    """Raised when report-index upsert fails after object upload."""

    def __init__(
        self,
        message: str,
        *,
        storage_key: str,
        cleanup_failed: bool = False,
    ) -> None:
        super().__init__(message)
        self.storage_key = storage_key
        self.cleanup_failed = cleanup_failed


@dataclass(frozen=True)
class SupabaseStorageConfig:
    url: str
    service_role_key: str
    bucket: str = _DEFAULT_BUCKET
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class _HttpResponseData:
    status_code: int
    text: str


def _is_github_actions() -> bool:
    return os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true"


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
    except ValueError, json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_upload_mode(
    *,
    github_actions: bool,
    upload_flag: bool,
    force: bool = False,
) -> tuple[bool, bool]:
    required = github_actions or force
    enabled = required or upload_flag
    return required, enabled


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


def _resolve_storage_config(
    *,
    url_raw: str | None,
    secret_key_raw: str | None,
    legacy_service_role_raw: str | None,
    bucket_raw: str,
    required: bool,
) -> SupabaseStorageConfig | None:
    key_raw = secret_key_raw or legacy_service_role_raw

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


def _load_storage_config(*, required: bool) -> SupabaseStorageConfig | None:
    return _resolve_storage_config(
        url_raw=_env_value("SUPABASE_URL"),
        secret_key_raw=_env_value("SUPABASE_SECRET_KEY"),
        legacy_service_role_raw=_env_value("SUPABASE_SERVICE_ROLE_KEY"),
        bucket_raw=_env_value("SUPABASE_REPORTS_BUCKET") or _DEFAULT_BUCKET,
        required=required,
    )


def _extract_report_date_from_filename(*, filename: str, today: dt.date) -> dt.date:
    match = _REPORT_DATE_PATTERN.search(filename)
    if not match:
        return today
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
        return today


def _extract_report_date(local_path: str) -> dt.date:
    return _extract_report_date_from_filename(
        filename=Path(local_path).name,
        today=dt.date.today(),
    )


def _auth_headers(config: SupabaseStorageConfig) -> dict[str, str]:
    return {
        "apikey": config.service_role_key,
        "authorization": f"Bearer {config.service_role_key}",
    }


def _response_message(*, status_code: int, text: str) -> str:
    trimmed_text = text.strip()
    if trimmed_text:
        return trimmed_text
    return f"HTTP {status_code}"


def _is_not_found_response(*, status_code: int, text: str) -> bool:
    if status_code == 404:
        return True
    if status_code != 400:
        return False

    trimmed_text = text.strip()
    if not trimmed_text:
        return False
    try:
        payload = json.loads(trimmed_text)
    except ValueError:
        lowered = trimmed_text.lower()
        return "not_found" in lowered or "not found" in lowered

    code = payload.get("code")
    if isinstance(code, str) and code.lower() == "not_found":
        return True
    message = payload.get("message")
    return isinstance(message, str) and "not found" in message.lower()


def _is_conflict_response(*, status_code: int, text: str) -> bool:
    if status_code == 409:
        return True
    if status_code != 400:
        return False
    lowered = text.lower()
    return "duplicate" in lowered or "already exists" in lowered


def _response_to_data(response: requests.Response) -> _HttpResponseData:
    return _HttpResponseData(status_code=response.status_code, text=response.text)


def _storage_info_request(
    *,
    config: SupabaseStorageConfig,
    key: str,
    session: requests.Session,
) -> _HttpResponseData:
    quoted_key = quote(key, safe="/")
    url = f"{config.url}/storage/v1/object/info/{config.bucket}/{quoted_key}"
    response = session.get(
        url,
        headers=_auth_headers(config),
        timeout=config.timeout_seconds,
    )
    return _response_to_data(response)


def _storage_upload_request(
    *,
    config: SupabaseStorageConfig,
    key: str,
    payload: bytes,
    session: requests.Session,
) -> _HttpResponseData:
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
    return _response_to_data(response)


def _report_index_upsert_request(
    *,
    config: SupabaseStorageConfig,
    row: dict[str, object],
    session: requests.Session,
) -> _HttpResponseData:
    url = f"{config.url}/rest/v1/report_index?on_conflict=report_key"
    headers = {
        **_auth_headers(config),
        "content-type": "application/json",
        "prefer": "resolution=merge-duplicates,return=minimal",
    }
    response = session.post(
        url,
        headers=headers,
        data=json.dumps([row], ensure_ascii=False).encode("utf-8"),
        timeout=config.timeout_seconds,
    )
    return _response_to_data(response)


def _storage_delete_request(
    *,
    config: SupabaseStorageConfig,
    key: str,
    session: requests.Session,
) -> _HttpResponseData:
    quoted_key = quote(key, safe="/")
    url = f"{config.url}/storage/v1/object/{config.bucket}/{quoted_key}"
    response = session.delete(
        url,
        headers=_auth_headers(config),
        timeout=config.timeout_seconds,
    )
    return _response_to_data(response)


def _decode_report_json_object(*, payload: bytes, local_path: str) -> dict[str, object]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupabaseStorageError(
            f"report artifact '{local_path}' is not a valid JSON object"
        ) from exc
    if not isinstance(decoded, dict):
        raise SupabaseStorageError(
            f"report artifact '{local_path}' is not a valid JSON object"
        )
    return decoded


def _normalize_ticker(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    ticker = value.strip()
    return ticker if ticker else None


def _extract_tickers_from_rows(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    results: list[str] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        ticker = _normalize_ticker(row.get("ticker"))
        if ticker:
            results.append(ticker)
    return results


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        results.append(value)
    return results


def _extract_report_tickers(report: dict[str, object]) -> list[str]:
    tickers_raw = report.get("tickers")
    tickers: list[str] = []
    if isinstance(tickers_raw, list):
        for value in tickers_raw:
            ticker = _normalize_ticker(value)
            if ticker:
                tickers.append(ticker)
    if tickers:
        return _dedupe_preserve_order(tickers)

    candidates = _extract_tickers_from_rows(report.get("candidates"))
    evaluated = _extract_tickers_from_rows(report.get("evaluated"))
    entries = _extract_tickers_from_rows(report.get("entries"))
    recommendations = _extract_tickers_from_rows(report.get("recommendations"))
    excluded = _extract_tickers_from_rows(report.get("excluded_candidates"))
    vetoed = _extract_tickers_from_rows(report.get("vetoed_candidates"))
    cap_excluded = _extract_tickers_from_rows(report.get("cap_excluded_candidates"))

    eligible_raw = report.get("eligible_tickers")
    eligible: list[str] = []
    if isinstance(eligible_raw, list):
        for value in eligible_raw:
            ticker = _normalize_ticker(value)
            if ticker:
                eligible.append(ticker)

    return _dedupe_preserve_order(
        candidates
        + evaluated
        + entries
        + recommendations
        + excluded
        + vetoed
        + cap_excluded
        + eligible
    )


def _extract_duplicate_index(storage_key: str) -> int:
    match = _REPORT_KEY_PATTERN.search(storage_key)
    if not match:
        return 0
    duplicate_index_raw = match.group(1)
    if duplicate_index_raw is None:
        return 0
    try:
        duplicate_index = int(duplicate_index_raw)
    except ValueError:
        return 0
    return max(duplicate_index, 0)


def _build_report_index_row(
    *,
    storage_key: str,
    run_type: str,
    report_date: dt.date,
    report_payload: dict[str, object],
) -> dict[str, object]:
    report_type = normalize_report_run_type(run_type)
    generated_at = report_payload.get("generated_at")
    summary = report_payload.get("summary")
    tickers = _extract_report_tickers(report_payload)

    return {
        "report_key": storage_key,
        "report_type": report_type,
        "report_date": report_date.isoformat(),
        "duplicate_index": _extract_duplicate_index(storage_key),
        "generated_at": generated_at if isinstance(generated_at, str) else None,
        "summary": summary if isinstance(summary, dict) else None,
        "tickers": tickers,
        "tickers_hydrated": True,
    }


def _upsert_report_index(
    *,
    config: SupabaseStorageConfig,
    storage_key: str,
    run_type: str,
    report_date: dt.date,
    report_payload: dict[str, object],
    session: requests.Session,
) -> None:
    row = _build_report_index_row(
        storage_key=storage_key,
        run_type=run_type,
        report_date=report_date,
        report_payload=report_payload,
    )
    response: _HttpResponseData | None = None
    for attempt in range(1, _REPORT_INDEX_UPSERT_RETRY_ATTEMPTS + 1):
        response = _report_index_upsert_request(
            config=config,
            row=row,
            session=session,
        )
        if response.status_code in {200, 201, 204}:
            return
        if (
            response.status_code >= 500
            and attempt < _REPORT_INDEX_UPSERT_RETRY_ATTEMPTS
        ):
            time.sleep(_REPORT_INDEX_UPSERT_RETRY_BASE_SECONDS * attempt)
            continue
        break

    assert response is not None
    raise SupabaseReportIndexError(
        f"failed to upsert report index for '{storage_key}': "
        f"{_response_message(status_code=response.status_code, text=response.text)}",
        storage_key=storage_key,
    )


def _iter_candidate_storage_keys(
    *,
    report_date: dt.date,
    run_type: str,
    max_duplicate_index: int = _MAX_DUPLICATE_INDEX,
) -> Iterator[str]:
    if max_duplicate_index < 0:
        raise ValueError("max_duplicate_index must be >= 0")

    for duplicate_index in range(max_duplicate_index + 1):
        yield build_report_storage_key(
            report_date=report_date,
            run_type=run_type,
            duplicate_index=duplicate_index,
        )


def _resolve_storage_key_and_upload(
    *,
    candidate_keys: Iterable[str],
    object_exists: Callable[[str], bool],
    upload_payload: Callable[[str], None],
) -> str:
    for key in candidate_keys:
        if object_exists(key):
            continue
        try:
            upload_payload(key)
        except SupabaseStorageConflictError:
            # Handle a race where another process uploads the same key after
            # our existence check and before upload.
            continue
        return key
    raise SupabaseStorageError(
        "failed to resolve report storage key: duplicate index exhausted"
    )


def _object_exists(
    *,
    config: SupabaseStorageConfig,
    key: str,
    session: requests.Session,
) -> bool:
    response = _storage_info_request(config=config, key=key, session=session)
    if response.status_code == 200:
        return True
    if _is_not_found_response(status_code=response.status_code, text=response.text):
        return False
    raise SupabaseStorageError(
        f"failed to check existing object '{key}': "
        f"{_response_message(status_code=response.status_code, text=response.text)}"
    )


def _upload_json_payload(
    *,
    config: SupabaseStorageConfig,
    key: str,
    payload: bytes,
    session: requests.Session,
) -> None:
    response = _storage_upload_request(
        config=config,
        key=key,
        payload=payload,
        session=session,
    )
    if response.status_code in {200, 201}:
        return
    if _is_conflict_response(status_code=response.status_code, text=response.text):
        raise SupabaseStorageConflictError(f"report object already exists for '{key}'")
    raise SupabaseStorageError(
        f"failed to upload report object '{key}': "
        f"{_response_message(status_code=response.status_code, text=response.text)}"
    )


def _delete_uploaded_object(
    *,
    config: SupabaseStorageConfig,
    key: str,
    session: requests.Session,
) -> None:
    response = _storage_delete_request(config=config, key=key, session=session)
    if response.status_code in {200, 204}:
        return
    if _is_not_found_response(status_code=response.status_code, text=response.text):
        return
    raise SupabaseStorageError(
        f"failed to delete uploaded report object '{key}': "
        f"{_response_message(status_code=response.status_code, text=response.text)}"
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
    report_payload = _decode_report_json_object(
        payload=payload,
        local_path=local_path,
    )

    active_session = session or requests.Session()
    should_close_session = session is None
    try:

        def _exists(candidate_key: str) -> bool:
            return _object_exists(
                config=config,
                key=candidate_key,
                session=active_session,
            )

        def _upload(candidate_key: str) -> None:
            _upload_json_payload(
                config=config,
                key=candidate_key,
                payload=payload,
                session=active_session,
            )

        resolved_key = _resolve_storage_key_and_upload(
            candidate_keys=_iter_candidate_storage_keys(
                report_date=report_date,
                run_type=run_type,
            ),
            object_exists=_exists,
            upload_payload=_upload,
        )
        _upsert_report_index(
            config=config,
            storage_key=resolved_key,
            run_type=run_type,
            report_date=report_date,
            report_payload=report_payload,
            session=active_session,
        )
        return resolved_key
    except SupabaseReportIndexError as exc:
        cleanup_failed = False
        cleanup_error_message = ""
        try:
            _delete_uploaded_object(
                config=config,
                key=exc.storage_key,
                session=active_session,
            )
        except SupabaseStorageError as cleanup_exc:
            cleanup_failed = True
            cleanup_error_message = f"; rollback delete failed: {cleanup_exc}"
        raise SupabaseReportIndexError(
            f"{exc}{cleanup_error_message}",
            storage_key=exc.storage_key,
            cleanup_failed=cleanup_failed,
        ) from exc
    finally:
        if should_close_session:
            active_session.close()


def maybe_upload_report_artifact(
    *,
    artifact_path: str,
    run_type: str,
    logger: logging.Logger,
    force: bool = False,
) -> str | None:
    required, enabled = _resolve_upload_mode(
        github_actions=_is_github_actions(),
        upload_flag=env_flag("SAB_UPLOAD_REPORTS", default=False),
        force=force,
    )
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
    except SupabaseReportIndexError as exc:
        if required or exc.cleanup_failed:
            raise
        logger.warning(
            "Supabase report upload rolled back after index upsert failure: %s",
            exc,
        )
        return None
    except SupabaseStorageError:
        if required:
            raise
        logger.exception("Supabase report upload skipped due to upload error")
        return None


__all__ = [
    "SupabaseReportIndexError",
    "SupabaseStorageConfig",
    "SupabaseStorageConfigError",
    "SupabaseStorageError",
    "maybe_upload_report_artifact",
    "upload_report_artifact",
]
