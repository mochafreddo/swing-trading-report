from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pytest
from sab.report.supabase_storage import (
    SupabaseStorageConfig,
    SupabaseStorageConfigError,
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
    ) -> None:
        self._get_responses = list(get_responses)
        self._post_responses = list(post_responses)
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []

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


def test_upload_report_artifact_adds_suffix_when_key_exists(tmp_path: Path) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(200), _FakeResponse(404)],
        post_responses=[_FakeResponse(200)],
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
    assert session.post_calls[0]["headers"]["content-type"] == "application/json"


def test_upload_report_artifact_uses_base_key_when_available(tmp_path: Path) -> None:
    report_path = tmp_path / "2026-02-13.sell.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    session = _FakeSession(
        get_responses=[_FakeResponse(404)],
        post_responses=[_FakeResponse(201)],
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
        post_responses=[_FakeResponse(201)],
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


def test_maybe_upload_report_artifact_requires_supabase_env_on_github_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "2026-02-13.buy.json"
    report_path.write_text('{"schema":"sab.report.v1"}', encoding="utf-8")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(SupabaseStorageConfigError):
        maybe_upload_report_artifact(
            artifact_path=report_path.as_posix(),
            run_type="buy",
            logger=logging.getLogger("test"),
        )
