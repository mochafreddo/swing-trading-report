from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest
import sab.report.supabase_storage as supabase_storage
from sab.report.supabase_storage import (
    SupabaseReportIndexError,
    SupabaseStorageConfig,
    SupabaseStorageConfigError,
    SupabaseStorageError,
    maybe_upload_report_artifact,
    upload_report_artifact,
)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(
        self,
        *,
        get_responses: list[_FakeResponse],
        post_responses: list[_FakeResponse],
        delete_responses: list[_FakeResponse] | None = None,
    ) -> None:
        self._get_responses = list(get_responses)
        self._post_responses = list(post_responses)
        self._delete_responses = list(delete_responses or [])
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def get(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _FakeResponse:
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        if not self._get_responses:
            raise AssertionError("unexpected GET request")
        return self._get_responses.pop(0)

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: bytes,
        timeout: float,
    ) -> _FakeResponse:
        self.post_calls.append(
            {
                "url": url,
                "headers": headers,
                "data": data,
                "timeout": timeout,
            }
        )
        if not self._post_responses:
            raise AssertionError("unexpected POST request")
        return self._post_responses.pop(0)

    def delete(
        self, url: str, *, headers: dict[str, str], timeout: float
    ) -> _FakeResponse:
        self.delete_calls.append({"url": url, "headers": headers, "timeout": timeout})
        if not self._delete_responses:
            raise AssertionError("unexpected DELETE request")
        return self._delete_responses.pop(0)


def test_is_not_found_response_classifies_expected_statuses() -> None:
    assert supabase_storage._is_not_found_response(status_code=404, text="")
    assert supabase_storage._is_not_found_response(
        status_code=400,
        text='{"code":"not_found","message":"The resource was not found"}',
    )
    assert supabase_storage._is_not_found_response(
        status_code=400,
        text="Resource not found",
    )
    assert not supabase_storage._is_not_found_response(
        status_code=400,
        text='{"code":"invalid_request","message":"bad request"}',
    )
    assert not supabase_storage._is_not_found_response(
        status_code=500,
        text="internal error",
    )


def test_is_conflict_response_classifies_expected_statuses() -> None:
    assert supabase_storage._is_conflict_response(status_code=409, text="")
    assert supabase_storage._is_conflict_response(
        status_code=400,
        text="duplicate key",
    )
    assert supabase_storage._is_conflict_response(
        status_code=400,
        text="already exists",
    )
    assert not supabase_storage._is_conflict_response(
        status_code=400,
        text="invalid payload",
    )
    assert not supabase_storage._is_conflict_response(
        status_code=500,
        text="internal error",
    )


def test_resolve_storage_config_prefers_secret_key() -> None:
    config = supabase_storage._resolve_storage_config(
        url_raw="https://example.supabase.co/",
        secret_key_raw="sb_secret_server_key",
        legacy_service_role_raw="legacy-key",
        bucket_raw="reports",
        required=True,
    )

    assert config is not None
    assert config.service_role_key == "sb_secret_server_key"
    assert config.url == "https://example.supabase.co"


def test_resolve_storage_config_uses_legacy_key_when_secret_is_missing() -> None:
    config = supabase_storage._resolve_storage_config(
        url_raw="https://example.supabase.co",
        secret_key_raw=None,
        legacy_service_role_raw="legacy-key",
        bucket_raw="reports",
        required=True,
    )

    assert config is not None
    assert config.service_role_key == "legacy-key"


def test_resolve_storage_config_requires_env_when_required() -> None:
    with pytest.raises(SupabaseStorageConfigError):
        supabase_storage._resolve_storage_config(
            url_raw=None,
            secret_key_raw=None,
            legacy_service_role_raw=None,
            bucket_raw="reports",
            required=True,
        )


def test_resolve_storage_config_returns_none_when_not_required() -> None:
    config = supabase_storage._resolve_storage_config(
        url_raw=None,
        secret_key_raw=None,
        legacy_service_role_raw=None,
        bucket_raw="reports",
        required=False,
    )
    assert config is None


def test_extract_report_date_from_filename_falls_back_to_today() -> None:
    today = date(2026, 2, 14)

    assert (
        supabase_storage._extract_report_date_from_filename(
            filename="buy-report.json",
            today=today,
        )
        == today
    )
    assert (
        supabase_storage._extract_report_date_from_filename(
            filename="2026-99-99.buy.json",
            today=today,
        )
        == today
    )


def test_extract_report_date_from_filename_reads_valid_date() -> None:
    parsed = supabase_storage._extract_report_date_from_filename(
        filename="prefix-2026-02-13.buy.json",
        today=date(2026, 2, 14),
    )
    assert parsed == date(2026, 2, 13)


def test_resolve_storage_key_and_upload_retries_on_conflict() -> None:
    report_date = date(2026, 2, 13)
    candidate_keys = list(
        supabase_storage._iter_candidate_storage_keys(
            report_date=report_date,
            run_type="buy",
            max_duplicate_index=2,
        )
    )

    exists_calls: list[str] = []
    upload_calls: list[str] = []

    def _fake_exists(key: str) -> bool:
        exists_calls.append(key)
        return False

    def _fake_upload(key: str) -> None:
        upload_calls.append(key)
        if len(upload_calls) == 1:
            raise supabase_storage.SupabaseStorageConflictError("race")

    resolved = supabase_storage._resolve_storage_key_and_upload(
        candidate_keys=candidate_keys,
        object_exists=_fake_exists,
        upload_payload=_fake_upload,
    )

    assert resolved == "2026/02/2026-02-13-1.buy.json"
    assert exists_calls == candidate_keys[:2]
    assert upload_calls == candidate_keys[:2]


def test_resolve_storage_key_and_upload_raises_when_candidates_exhausted() -> None:
    with pytest.raises(SupabaseStorageError, match="duplicate index exhausted"):
        supabase_storage._resolve_storage_key_and_upload(
            candidate_keys=["k0", "k1"],
            object_exists=lambda _key: True,
            upload_payload=lambda _key: None,
        )


def test_iter_candidate_storage_keys_rejects_negative_max_duplicate_index() -> None:
    with pytest.raises(ValueError, match="max_duplicate_index"):
        list(
            supabase_storage._iter_candidate_storage_keys(
                report_date=date(2026, 2, 13),
                run_type="buy",
                max_duplicate_index=-1,
            )
        )


def test_upload_report_artifact_adds_suffix_when_key_exists(tmp_path: Path) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(200), _FakeResponse(404)],
        post_responses=[_FakeResponse(200), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="buy",
        report_date=date(2026, 2, 13),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/02/2026-02-13-1.buy.json"
    first_headers = session.post_calls[0]["headers"]
    assert isinstance(first_headers, dict)
    assert first_headers["content-type"] == "application/json"
    second_url = session.post_calls[1]["url"]
    assert isinstance(second_url, str)
    assert second_url.endswith("/rest/v1/report_index?on_conflict=report_key")


def test_upload_report_artifact_uses_base_key_when_available(tmp_path: Path) -> None:
    report_path = tmp_path / "2026-02-13.sell.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[_FakeResponse(201), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="sell",
        report_date=date(2026, 2, 13),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/02/2026-02-13.sell.json"


def test_upload_report_artifact_normalizes_report_type_for_index_row(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[_FakeResponse(201), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type=" BUY ",
        report_date=date(2026, 2, 13),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/02/2026-02-13.buy.json"
    index_payload = session.post_calls[1]["data"]
    assert isinstance(index_payload, bytes)
    assert b'"report_type": "buy"' in index_payload


def test_upload_report_artifact_treats_400_not_found_as_missing(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[
            _FakeResponse(
                400,
                '{"httpStatusCode":400,"code":"not_found","message":"The resource was not found"}',
            )
        ],
        post_responses=[_FakeResponse(201), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="buy",
        report_date=date(2026, 2, 13),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/02/2026-02-13.buy.json"


@pytest.mark.parametrize("payload", ["{bad json", '["not", "object"]'])
def test_upload_report_artifact_rejects_invalid_report_json_before_network(
    tmp_path: Path,
    payload: str,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text(payload, encoding="utf-8")

    session = _FakeSession(get_responses=[], post_responses=[])
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    with pytest.raises(SupabaseStorageError, match="valid JSON object"):
        upload_report_artifact(
            local_path=report_path.as_posix(),
            run_type="buy",
            report_date=date(2026, 2, 13),
            config=config,
            session=session,  # type: ignore[arg-type]
        )

    assert session.get_calls == []
    assert session.post_calls == []
    assert session.delete_calls == []


def test_upload_report_artifact_indexes_tickers_from_candidates_fallback(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text(
        '{"schema":"sab.report.v1","candidates":[{"ticker":"AAPL.US"},{"ticker":"MSFT.US"}]}',
        encoding="utf-8",
    )

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[_FakeResponse(201), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="buy",
        report_date=date(2026, 2, 13),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/02/2026-02-13.buy.json"
    index_payload = session.post_calls[1]["data"]
    assert isinstance(index_payload, bytes)
    assert b'"tickers": ["AAPL.US", "MSFT.US"]' in index_payload
    assert b'"tickers_hydrated": true' in index_payload


def test_upload_report_artifact_indexes_ai_brief_tickers(tmp_path: Path) -> None:
    report_path = tmp_path / "2026-05-05.ai-brief.json"
    report_path.write_text(
        (
            '{"schema":"sab.ai_brief.v1","type":"ai_brief",'
            '"eligible_tickers":["AAPL.NAS","MSFT.NAS"],'
            '"recommendations":[{"ticker":"AAPL.NAS"}],'
            '"excluded_candidates":[{"ticker":"MSFT.NAS"}],'
            '"summary":{"recommendation_count":1}}'
        ),
        encoding="utf-8",
    )

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[_FakeResponse(201), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="ai-brief",
        report_date=date(2026, 5, 5),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/05/2026-05-05.ai-brief.json"
    index_payload = session.post_calls[1]["data"]
    assert isinstance(index_payload, bytes)
    assert b'"report_type": "ai-brief"' in index_payload
    assert b'"summary": {"recommendation_count": 1}' in index_payload
    assert b'"tickers": ["AAPL.NAS", "MSFT.NAS"]' in index_payload


def test_upload_report_artifact_indexes_ai_brief_skip_artifact(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-05-05.ai-brief-skip.json"
    report_path.write_text(
        (
            '{"schema":"sab.ai_brief_skip.v1","type":"ai_brief_skip",'
            '"generated_at":"2026-05-05T08:40:00+00:00",'
            '"summary":{"skip_reason":"non_trading_session"}}'
        ),
        encoding="utf-8",
    )

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[_FakeResponse(201), _FakeResponse(201)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="ai-brief-skip",
        report_date=date(2026, 5, 5),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/05/2026-05-05.ai-brief-skip.json"
    index_payload = session.post_calls[1]["data"]
    assert isinstance(index_payload, bytes)
    assert b'"report_type": "ai-brief-skip"' in index_payload
    assert b'"summary": {"skip_reason": "non_trading_session"}' in index_payload
    assert b'"tickers": []' in index_payload


def test_upload_report_artifact_raises_index_error_when_upsert_fails(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[
            _FakeResponse(201),
            _FakeResponse(500, "index down"),
            _FakeResponse(500, "index down"),
            _FakeResponse(500, "index down"),
        ],
        delete_responses=[_FakeResponse(200)],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    with pytest.raises(SupabaseReportIndexError, match="index down") as exc_info:
        upload_report_artifact(
            local_path=report_path.as_posix(),
            run_type="buy",
            report_date=date(2026, 2, 13),
            config=config,
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.storage_key == "2026/02/2026-02-13.buy.json"
    assert not exc_info.value.cleanup_failed
    assert len(session.delete_calls) == 1


def test_upload_report_artifact_retries_index_upsert_on_server_error(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[
            _FakeResponse(201),
            _FakeResponse(500, "index transient 1"),
            _FakeResponse(502, "index transient 2"),
            _FakeResponse(201),
        ],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    key = upload_report_artifact(
        local_path=report_path.as_posix(),
        run_type="buy",
        report_date=date(2026, 2, 13),
        config=config,
        session=session,  # type: ignore[arg-type]
    )

    assert key == "2026/02/2026-02-13.buy.json"
    assert len(session.post_calls) == 4
    assert session.delete_calls == []


def test_upload_report_artifact_marks_cleanup_failed_when_rollback_delete_fails(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[
            _FakeResponse(201),
            _FakeResponse(500, "index down"),
            _FakeResponse(500, "index down"),
            _FakeResponse(500, "index down"),
        ],
        delete_responses=[_FakeResponse(500, "delete down")],
    )
    config = SupabaseStorageConfig(
        url="https://example.supabase.co",
        service_role_key="service-key",
        bucket="reports",
    )

    with pytest.raises(SupabaseReportIndexError, match="rollback delete failed") as exc:
        upload_report_artifact(
            local_path=report_path.as_posix(),
            run_type="buy",
            report_date=date(2026, 2, 13),
            config=config,
            session=session,  # type: ignore[arg-type]
        )

    assert exc.value.storage_key == "2026/02/2026-02-13.buy.json"
    assert exc.value.cleanup_failed
    assert len(session.delete_calls) == 1


def test_maybe_upload_report_artifact_skips_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("SAB_UPLOAD_REPORTS", raising=False)

    uploaded = maybe_upload_report_artifact(
        artifact_path=report_path.as_posix(),
        run_type="buy",
        logger=logging.getLogger("test"),
    )
    assert uploaded is None


def test_maybe_upload_report_artifact_skips_on_local_opt_in_upload_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("SAB_UPLOAD_REPORTS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_server_key")

    def _fake_upload(
        *,
        local_path: str,
        run_type: str,
        report_date: date,
        config: SupabaseStorageConfig,
    ) -> str:
        del local_path, run_type, report_date, config
        raise SupabaseStorageError("upload failed")

    monkeypatch.setattr(
        "sab.report.supabase_storage.upload_report_artifact", _fake_upload
    )

    uploaded = maybe_upload_report_artifact(
        artifact_path=report_path.as_posix(),
        run_type="buy",
        logger=logging.getLogger("test"),
    )

    assert uploaded is None


def test_maybe_upload_report_artifact_returns_none_on_local_index_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("SAB_UPLOAD_REPORTS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_server_key")

    def _fake_upload(
        *,
        local_path: str,
        run_type: str,
        report_date: date,
        config: SupabaseStorageConfig,
    ) -> str:
        del local_path, run_type, report_date, config
        raise SupabaseReportIndexError(
            "index down",
            storage_key="2026/02/2026-02-13.buy.json",
        )

    monkeypatch.setattr(
        "sab.report.supabase_storage.upload_report_artifact", _fake_upload
    )

    uploaded = maybe_upload_report_artifact(
        artifact_path=report_path.as_posix(),
        run_type="buy",
        logger=logging.getLogger("test"),
    )

    assert uploaded is None


def test_maybe_upload_report_artifact_raises_on_github_actions_index_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_server_key")

    def _fake_upload(
        *,
        local_path: str,
        run_type: str,
        report_date: date,
        config: SupabaseStorageConfig,
    ) -> str:
        del local_path, run_type, report_date, config
        raise SupabaseReportIndexError(
            "index down",
            storage_key="2026/02/2026-02-13.buy.json",
        )

    monkeypatch.setattr(
        "sab.report.supabase_storage.upload_report_artifact", _fake_upload
    )

    with pytest.raises(SupabaseReportIndexError, match="index down"):
        maybe_upload_report_artifact(
            artifact_path=report_path.as_posix(),
            run_type="buy",
            logger=logging.getLogger("test"),
        )


def test_maybe_upload_report_artifact_raises_on_local_index_error_when_cleanup_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("SAB_UPLOAD_REPORTS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_server_key")

    def _fake_upload(
        *,
        local_path: str,
        run_type: str,
        report_date: date,
        config: SupabaseStorageConfig,
    ) -> str:
        del local_path, run_type, report_date, config
        raise SupabaseReportIndexError(
            "index down; rollback delete failed: delete down",
            storage_key="2026/02/2026-02-13.buy.json",
            cleanup_failed=True,
        )

    monkeypatch.setattr(
        "sab.report.supabase_storage.upload_report_artifact", _fake_upload
    )

    with pytest.raises(SupabaseReportIndexError, match="rollback delete failed"):
        maybe_upload_report_artifact(
            artifact_path=report_path.as_posix(),
            run_type="buy",
            logger=logging.getLogger("test"),
        )


def test_maybe_upload_report_artifact_requires_supabase_env_on_github_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(SupabaseStorageConfigError):
        maybe_upload_report_artifact(
            artifact_path=report_path.as_posix(),
            run_type="buy",
            logger=logging.getLogger("test"),
        )


def test_maybe_upload_report_artifact_prefers_supabase_secret_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_server_key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "legacy-service-role-key")

    captured: dict[str, str] = {}

    def _fake_upload(
        *,
        local_path: str,
        run_type: str,
        report_date: date,
        config: SupabaseStorageConfig,
    ) -> str:
        del local_path, run_type, report_date
        captured["key"] = config.service_role_key
        return "2026/02/2026-02-13.buy.json"

    monkeypatch.setattr(
        "sab.report.supabase_storage.upload_report_artifact", _fake_upload
    )

    uploaded = maybe_upload_report_artifact(
        artifact_path=report_path.as_posix(),
        run_type="buy",
        logger=logging.getLogger("test"),
    )

    assert uploaded == "2026/02/2026-02-13.buy.json"
    assert captured["key"] == "sb_secret_server_key"


def test_maybe_upload_report_artifact_rejects_publishable_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_publishable_test_key")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(SupabaseStorageConfigError, match="publishable"):
        maybe_upload_report_artifact(
            artifact_path=report_path.as_posix(),
            run_type="buy",
            logger=logging.getLogger("test"),
        )
