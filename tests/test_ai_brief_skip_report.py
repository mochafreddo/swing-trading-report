from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.report.ai_brief_skip_report import (
    AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
    AiBriefSkipValidationError,
    validate_ai_brief_skip_artifact,
    write_ai_brief_skip_report,
)


def test_write_ai_brief_skip_report_writes_runtime_guard_artifact(
    tmp_path: Path,
) -> None:
    out_path = write_ai_brief_skip_report(
        report_dir=tmp_path.as_posix(),
        market="US",
        session_date="2026-05-28",
        session_state="INTRADAY",
        expected_state="PRE_OPEN",
        trading_session=True,
        local_time="2026-05-28T09:31:00-04:00",
        run_url="https://github.com/owner/repo/actions/runs/1",
        source="scheduled-runtime-guard",
        now=datetime(2026, 5, 28, 13, 31, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))

    assert Path(out_path).name == "2026-05-28.ai-brief-skip.json"
    assert payload["schema"] == "sab.ai_brief_skip.v1"
    assert payload["type"] == "ai_brief_skip"
    assert payload["generated_at"] == "2026-05-28T13:31:00+00:00"
    assert payload["report_date"] == "2026-05-28"
    assert payload["market"] == "US"
    assert payload["skip_state"] == AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED
    assert payload["skip_reason"] == "scheduled_run_after_pre_open_window"
    assert payload["session_state"] == "INTRADAY"
    assert payload["expected_state"] == "PRE_OPEN"
    assert payload["trading_session"] is True
    assert payload["summary"] == {
        "skip_state": AI_BRIEF_SKIP_STATE_RUNTIME_GUARD_SKIPPED,
        "skip_reason": "scheduled_run_after_pre_open_window",
        "session_state": "INTRADAY",
        "expected_state": "PRE_OPEN",
        "trading_session": True,
    }


def test_write_ai_brief_skip_report_marks_non_trading_session(
    tmp_path: Path,
) -> None:
    out_path = write_ai_brief_skip_report(
        report_dir=tmp_path.as_posix(),
        market="US",
        session_date="2026-05-25",
        session_state="PRE_OPEN",
        expected_state="PRE_OPEN",
        trading_session=False,
        local_time="2026-05-25T08:30:00-04:00",
        run_url="",
        source="scheduled-runtime-guard",
        now=datetime(2026, 5, 25, 12, 30, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))

    assert payload["skip_reason"] == "non_trading_session"
    validate_ai_brief_skip_artifact(payload)


def test_validate_ai_brief_skip_artifact_rejects_unknown_state() -> None:
    payload = {
        "schema": "sab.ai_brief_skip.v1",
        "type": "ai_brief_skip",
        "generated_at": "2026-05-25T12:30:00+00:00",
        "report_date": "2026-05-25",
        "market": "US",
        "skip_state": "NO_SIGNAL",
        "skip_reason": "non_trading_session",
        "session_date": "2026-05-25",
        "session_state": "PRE_OPEN",
        "expected_state": "PRE_OPEN",
        "trading_session": False,
        "local_time": "2026-05-25T08:30:00-04:00",
        "run_url": "",
        "source": "scheduled-runtime-guard",
        "summary": {},
    }

    with pytest.raises(AiBriefSkipValidationError, match="skip_state"):
        validate_ai_brief_skip_artifact(payload)
