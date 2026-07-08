from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sab.report.sell_ai_brief_report import (
    SellAiBriefValidationError,
    validate_sell_ai_brief_artifact,
    write_sell_ai_brief_report,
)


def _source(*, published_at: str = "2026-05-05T07:00:00+00:00") -> dict[str, object]:
    return {
        "title": "Apple sell-side risk update",
        "url": "https://news.example/aapl-risk",
        "published_at": published_at,
    }


def _judgment(
    ticker: str = "AAPL.NAS",
    *,
    sell_action: str = "SELL",
    sources: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": "Apple",
        "sell_action": sell_action,
        "ai_stance": "AGREE",
        "confidence": "LOW",
        "deterministic_reasons": ["stop loss breached"],
        "rationale": ["기계적 매도 조건과 최근 리스크가 같은 방향입니다."],
        "checklist": ["체결 전 수량, 세금, 유동성을 수동 확인"],
        "sources": [_source()] if sources is None else sources,
        "as_of": "2026-05-05T08:40:00+00:00",
    }


def _artifact() -> dict[str, object]:
    return {
        "source_sell_report": "2026-05-05.sell.json",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-sell-ai-brief-v1",
        "summary": {
            "evaluated_count": 3,
            "actionable_count": 1,
            "preselected_count": 1,
            "judgment_count": 1,
            "broker_state_review_count": 0,
            "excluded_hold_count": 1,
            "unsupported_action_count": 1,
            "vetoed_count": 0,
            "cap_excluded_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "tickers": ["AAPL.NAS"],
        "actionable_tickers": ["AAPL.NAS"],
        "actionable_candidates": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "sell_action": "SELL",
                "deterministic_reasons": ["stop loss breached"],
                "ai_role_reason": "sell report action was SELL",
            }
        ],
        "excluded_hold_candidates": [
            {
                "ticker": "MSFT.NAS",
                "sell_action": "HOLD",
                "reason": "sell report action was HOLD",
            }
        ],
        "broker_state_review_candidates": [],
        "unsupported_action_candidates": [
            {
                "ticker": "BAD.NAS",
                "sell_action": "TRIM",
                "reason": "unsupported sell action TRIM",
            }
        ],
        "cap_excluded_candidates": [],
        "judgments": [_judgment()],
        "vetoed_candidates": [],
        "source_issues": [],
        "system_issues": [],
    }


def test_write_sell_ai_brief_report_writes_schema_and_state(tmp_path: Path) -> None:
    out_path = write_sell_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=_artifact(),
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert Path(out_path).name == "2026-05-05.sell-ai-brief.json"
    assert payload["schema"] == "sab.sell_ai_brief.v1"
    assert payload["type"] == "sell-ai-brief"
    assert payload["generated_at"] == "2026-05-05T08:40:00+00:00"
    assert payload["report_date"] == "2026-05-05"
    assert payload["brief_state"] == "FINAL_JUDGMENT"
    assert payload["brief_reason"] == "model_judgment_ready"


def test_validate_rejects_judgment_ticker_not_from_actionable_candidates() -> None:
    artifact = _artifact()
    judgments = artifact["judgments"]
    assert isinstance(judgments, list)
    judgment = judgments[0]
    assert isinstance(judgment, dict)
    judgment["ticker"] = "MSFT.NAS"

    with pytest.raises(SellAiBriefValidationError, match="actionable_tickers"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_model_changed_sell_action() -> None:
    artifact = _artifact()
    judgments = artifact["judgments"]
    assert isinstance(judgments, list)
    judgment = judgments[0]
    assert isinstance(judgment, dict)
    judgment["sell_action"] = "SELL_PARTIAL"

    with pytest.raises(SellAiBriefValidationError, match="source sell action"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_hold_judgment() -> None:
    artifact = _artifact()
    artifact["actionable_tickers"] = ["MSFT.NAS"]
    artifact["actionable_candidates"] = [
        {
            "ticker": "MSFT.NAS",
            "name": "Microsoft",
            "sell_action": "HOLD",
            "deterministic_reasons": ["hold"],
            "ai_role_reason": "sell report action was HOLD",
        }
    ]
    judgments = artifact["judgments"]
    assert isinstance(judgments, list)
    judgment = judgments[0]
    assert isinstance(judgment, dict)
    judgment["ticker"] = "MSFT.NAS"
    judgment["sell_action"] = "HOLD"

    with pytest.raises(SellAiBriefValidationError, match="HOLD"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_automated_sell_language() -> None:
    artifact = _artifact()
    judgments = artifact["judgments"]
    assert isinstance(judgments, list)
    judgment = judgments[0]
    assert isinstance(judgment, dict)
    judgment["checklist"] = ["지금 매도하세요"]

    with pytest.raises(SellAiBriefValidationError, match="automated-order language"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_automated_sell_language_in_source_issues() -> None:
    artifact = _artifact()
    artifact["source_issues"] = [
        {
            "ticker": "AAPL.NAS",
            "code": "model_diagnostic",
            "severity": "WARN",
            "message": "지금 매도하세요",
        }
    ]
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    summary["source_issue_count"] = 1

    with pytest.raises(SellAiBriefValidationError, match="automated-order language"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_uncovered_actionable_candidate() -> None:
    artifact = _artifact()
    artifact["judgments"] = []
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    summary["judgment_count"] = 0
    artifact["brief_state"] = "NEEDS_REVIEW_WEAK_NEWS"
    artifact["brief_reason"] = "weak_news_coverage"

    with pytest.raises(SellAiBriefValidationError, match="judgments or vetoed"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_explicit_state_that_disagrees_with_inference() -> None:
    artifact = _artifact()
    artifact["source_issues"] = [
        {
            "ticker": "AAPL.NAS",
            "code": "weak_source",
            "severity": "WARN",
            "message": "최근 소스 커버리지가 약함",
        }
    ]
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    summary["source_issue_count"] = 1
    artifact["brief_state"] = "FINAL_JUDGMENT"
    artifact["brief_reason"] = "model_judgment_ready"

    with pytest.raises(SellAiBriefValidationError, match="brief_state"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_rejects_stale_sources() -> None:
    artifact = _artifact()
    stale = (datetime(2026, 5, 5, 8, 40, tzinfo=UTC) - timedelta(hours=73)).isoformat()
    judgments = artifact["judgments"]
    assert isinstance(judgments, list)
    judgment = judgments[0]
    assert isinstance(judgment, dict)
    judgment["sources"] = [_source(published_at=stale)]

    with pytest.raises(SellAiBriefValidationError, match="within 72h"):
        validate_sell_ai_brief_artifact(
            artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_write_infers_no_action_state_for_hold_only_report(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["summary"] = {
        "evaluated_count": 1,
        "actionable_count": 0,
        "preselected_count": 0,
        "judgment_count": 0,
        "broker_state_review_count": 0,
        "excluded_hold_count": 1,
        "unsupported_action_count": 0,
        "vetoed_count": 0,
        "cap_excluded_count": 0,
        "source_issue_count": 0,
        "system_issue_count": 0,
    }
    artifact["tickers"] = []
    artifact["actionable_tickers"] = []
    artifact["actionable_candidates"] = []
    artifact["excluded_hold_candidates"] = [
        {
            "ticker": "MSFT.NAS",
            "sell_action": "HOLD",
            "reason": "sell report action was HOLD",
        }
    ]
    artifact["broker_state_review_candidates"] = []
    artifact["unsupported_action_candidates"] = []
    artifact["judgments"] = []

    out_path = write_sell_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["brief_state"] == "NO_ACTION"
    assert payload["brief_reason"] == "no_actionable_sell_candidates"
