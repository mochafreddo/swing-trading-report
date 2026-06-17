from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sab.ai_brief import run_ai_brief
from sab.ai_brief_eval import evaluate_ai_brief_recommendation_report

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_brief_eval"
EVAL_NOW = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC)


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).as_posix()


def _load_good_ai_brief() -> dict[str, Any]:
    payload = json.loads(
        Path(_fixture("ai-brief.good.json")).read_text(encoding="utf-8")
    )
    assert isinstance(payload, dict)
    return payload


def _copy_mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, Mapping)
    return dict(value)


def _write_payload(tmp_path: Path, name: str, payload: Mapping[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_posix()


def _issue_codes(result: Any) -> set[str]:
    return {issue.code for issue in result.issues}


def test_ai_brief_eval_fails_empty_recommendations_even_with_source_issues(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["recommendations"] = []
    payload["vetoed_candidates"] = []
    payload["source_issues"] = [
        {
            "ticker": "AAPL.NAS",
            "code": "openai_no_external_sources",
            "severity": "WARN",
            "message": "OpenAI provider returned no usable source for this ticker",
        }
    ]
    summary = _copy_mapping(payload["summary"])
    summary["recommendation_count"] = 0
    summary["vetoed_count"] = 0
    summary["source_issue_count"] = 1
    payload["summary"] = summary
    report_path = _write_payload(
        tmp_path, "empty-with-source-issue.ai-brief.json", payload
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "recommendation_report_empty" in _issue_codes(result)


def test_run_ai_brief_rejects_nonfinite_model_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=_fixture("entry.us.json"),
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
        model_timeout_seconds=float("nan"),
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 1
    assert not list(report_dir.glob("*.ai-brief.json"))


def test_run_ai_brief_suppresses_generation_upload_on_github_actions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SAB_SUPPRESS_REPORT_UPLOADS", "true")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=_fixture("entry.us.json"),
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    assert len(list(report_dir.glob("*.ai-brief.json"))) == 1
