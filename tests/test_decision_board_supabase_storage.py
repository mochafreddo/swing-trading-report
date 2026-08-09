from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sab.report.decision_board import (
    DecisionBoardIdempotencyConflictError,
    build_decision_board_storage_key,
    write_decision_board_report,
)
from sab.report.supabase_storage import (
    SupabaseReportIndexError,
    SupabaseStorageConfig,
    upload_decision_board_report,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "decision_board"


class _Response:
    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        content: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")


class _Session:
    def __init__(
        self,
        *,
        posts: list[_Response],
        gets: list[_Response] | None = None,
        deletes: list[_Response] | None = None,
    ) -> None:
        self._posts = list(posts)
        self._gets = list(gets or [])
        self._deletes = list(deletes or [])
        self.post_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: bytes,
        timeout: float,
    ) -> _Response:
        self.post_calls.append(
            {"url": url, "headers": headers, "data": data, "timeout": timeout}
        )
        assert self._posts, f"unexpected POST {url}"
        return self._posts.pop(0)

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        self.get_calls.append({"url": url, "headers": headers, "timeout": timeout})
        assert self._gets, f"unexpected GET {url}"
        return self._gets.pop(0)

    def delete(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> _Response:
        self.delete_calls.append({"url": url, "headers": headers, "timeout": timeout})
        assert self._deletes, f"unexpected DELETE {url}"
        return self._deletes.pop(0)


def _report(name: str = "published-entry.json") -> dict[str, Any]:
    value = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _local_report(tmp_path: Path, report: dict[str, Any]) -> tuple[Path, str]:
    path = write_decision_board_report(report, report_dir=tmp_path)
    return path, build_decision_board_storage_key(report)


def _index_row(
    report: dict[str, Any], key: str, *, bucket: str = "reports"
) -> dict[str, object]:
    return {
        "bucket_id": bucket,
        "report_key": key,
        "report_type": "decision-board",
        "report_date": key.split("/", 2)[2].split(".", 1)[0],
        "duplicate_index": 0,
        "generated_at": None,
        "summary": None,
        "tickers": [],
        "tickers_hydrated": False,
        "run_kind": report["run_kind"],
        "run_id": report["run_id"],
        "idempotency_key": report["idempotency_key"],
        "decision_created_at": report["created_at"],
    }


def _config() -> SupabaseStorageConfig:
    return SupabaseStorageConfig(
        url="https://project.supabase.co",
        service_role_key="server-secret",
        bucket="reports",
    )


def _authoritative_response(row: dict[str, object]) -> _Response:
    return _Response(200, text=json.dumps([row]))


def test_new_object_upload_derives_safe_index_row_from_validated_bytes(
    tmp_path: Path,
) -> None:
    report = _report()
    report["metadata"] = {
        "account": "PRIVATE-ACCOUNT",
        "trigger": "PRIVATE-TRIGGER",
        "ticker": "PRIVATE-TICKER",
    }
    local_path, key = _local_report(tmp_path, report)
    row = _index_row(report, key)
    session = _Session(
        posts=[_Response(201), _Response(201)],
        gets=[_authoritative_response(row)],
    )

    uploaded = upload_decision_board_report(
        local_path=local_path,
        storage_key=key,
        config=_config(),
        session=session,  # type: ignore[arg-type]
    )

    assert uploaded == key
    storage_call, index_call = session.post_calls
    assert storage_call["data"] == local_path.read_bytes()
    assert storage_call["headers"]["x-upsert"] == "false"  # type: ignore[index]
    assert "on_conflict=bucket_id,report_type,run_kind,idempotency_key" in str(
        index_call["url"]
    )
    assert json.loads(index_call["data"])[0] == row  # type: ignore[arg-type]
    exposed = key.encode() + index_call["data"]  # type: ignore[operator]
    for sentinel in (b"PRIVATE-ACCOUNT", b"PRIVATE-TRIGGER", b"PRIVATE-TICKER"):
        assert sentinel not in exposed
    assert session.delete_calls == []


def test_equal_existing_object_repairs_index_without_reupload_or_delete(
    tmp_path: Path,
) -> None:
    report = _report()
    local_path, key = _local_report(tmp_path, report)
    row = _index_row(report, key)
    session = _Session(
        posts=[_Response(409, text="already exists"), _Response(201)],
        gets=[
            _Response(200, content=local_path.read_bytes()),
            _authoritative_response(row),
        ],
    )

    assert (
        upload_decision_board_report(
            local_path=local_path,
            storage_key=key,
            config=_config(),
            session=session,  # type: ignore[arg-type]
        )
        == key
    )
    assert len(session.post_calls) == 2
    assert "/storage/v1/object/reports/" in str(session.get_calls[0]["url"])
    assert session.delete_calls == []


def test_mismatched_existing_object_is_typed_conflict_and_never_indexes(
    tmp_path: Path,
) -> None:
    local_path, key = _local_report(tmp_path, _report())
    session = _Session(
        posts=[_Response(409, text="already exists")],
        gets=[_Response(200, content=b"different bytes")],
    )

    with pytest.raises(DecisionBoardIdempotencyConflictError):
        upload_decision_board_report(
            local_path=local_path,
            storage_key=key,
            config=_config(),
            session=session,  # type: ignore[arg-type]
        )

    assert len(session.post_calls) == 1
    assert session.delete_calls == []


@pytest.mark.parametrize("pre_existing", [False, True])
def test_index_failure_rolls_back_only_a_newly_uploaded_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pre_existing: bool,
) -> None:
    import sab.report.supabase_storage as storage

    monkeypatch.setattr(storage, "_REPORT_INDEX_UPSERT_RETRY_BASE_SECONDS", 0)
    local_path, key = _local_report(tmp_path, _report())
    storage_response = (
        _Response(409, text="already exists") if pre_existing else _Response(201)
    )
    session = _Session(
        posts=[
            storage_response,
            *[_Response(500, text="index down") for _ in range(3)],
        ],
        gets=(
            [_Response(200, content=local_path.read_bytes())] if pre_existing else []
        ),
        deletes=[] if pre_existing else [_Response(204)],
    )

    with pytest.raises(SupabaseReportIndexError, match="index down") as exc:
        upload_decision_board_report(
            local_path=local_path,
            storage_key=key,
            config=_config(),
            session=session,  # type: ignore[arg-type]
        )

    assert exc.value.storage_key == key
    assert not exc.value.cleanup_failed
    assert len(session.delete_calls) == (0 if pre_existing else 1)


def test_new_object_index_failure_surfaces_rollback_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sab.report.supabase_storage as storage

    monkeypatch.setattr(storage, "_REPORT_INDEX_UPSERT_RETRY_BASE_SECONDS", 0)
    local_path, key = _local_report(tmp_path, _report())
    session = _Session(
        posts=[_Response(201), *[_Response(500, text="index down") for _ in range(3)]],
        deletes=[_Response(500, text="delete down")],
    )

    with pytest.raises(SupabaseReportIndexError, match="rollback delete failed") as exc:
        upload_decision_board_report(
            local_path=local_path,
            storage_key=key,
            config=_config(),
            session=session,  # type: ignore[arg-type]
        )

    assert exc.value.cleanup_failed


def test_authoritative_index_row_mismatch_fails_closed_without_overwrite(
    tmp_path: Path,
) -> None:
    report = _report()
    local_path, key = _local_report(tmp_path, report)
    wrong = _index_row(report, key)
    wrong["report_key"] = "different-safe-key"
    session = _Session(
        posts=[_Response(409, text="already exists"), _Response(201)],
        gets=[
            _Response(200, content=local_path.read_bytes()),
            _authoritative_response(wrong),
        ],
    )

    with pytest.raises(DecisionBoardIdempotencyConflictError):
        upload_decision_board_report(
            local_path=local_path,
            storage_key=key,
            config=_config(),
            session=session,  # type: ignore[arg-type]
        )
    assert session.delete_calls == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report, key: (report, key.replace(".entry.", ".holding.")),
        lambda report, key: ({**report, "run_id": "different-run"}, key),
        lambda report, key: ({**report, "created_at": "2026-08-06T01:00:05"}, key),
    ],
)
def test_payload_or_key_mismatch_is_rejected_before_network(
    tmp_path: Path,
    mutation: Any,
) -> None:
    report = _report()
    local_path, key = _local_report(tmp_path, report)
    changed, supplied_key = mutation(copy.deepcopy(report), key)
    if changed != report:
        local_path.write_text(
            json.dumps(
                changed, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            encoding="utf-8",
        )
    session = _Session(posts=[])

    with pytest.raises(ValueError):
        upload_decision_board_report(
            local_path=local_path,
            storage_key=supplied_key,
            config=_config(),
            session=session,  # type: ignore[arg-type]
        )

    assert session.post_calls == []
    assert session.get_calls == []
