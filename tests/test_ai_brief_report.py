from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.report.ai_brief_report import (
    AiBriefValidationError,
    write_ai_brief_report,
)


def _artifact(*, generated_at: str | None = None) -> dict[str, object]:
    artifact: dict[str, object] = {
        "source_entry_report": "2026-05-05.entry.json",
        "source_buy_report": "2026-05-04.buy.json",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {
            "entry_count": 2,
            "preselected_count": 1,
            "recommendation_count": 1,
            "excluded_count": 1,
            "vetoed_count": 0,
            "cap_excluded_count": 0,
        },
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "rank": 1,
                "action": "ENTER",
                "confidence": "LOW",
                "rationale": ["entry report marked this candidate ENTER"],
                "checklist": [
                    "entry price is still close to the entry report snapshot",
                    "manually check for blocking headlines or market-wide shocks",
                ],
                "sources": [],
                "as_of": "2026-05-05T08:40:00+09:00",
            }
        ],
        "excluded_candidates": [
            {
                "ticker": "MSFT.NAS",
                "action": "REVIEW",
                "reason": "entry report action was REVIEW",
            }
        ],
        "vetoed_candidates": [],
        "cap_excluded_candidates": [],
        "source_issues": [
            {
                "ticker": "AAPL.NAS",
                "code": "fake_provider_no_external_sources",
                "severity": "WARN",
                "message": "fake provider does not collect external sources",
            }
        ],
        "system_issues": [],
        "eligible_tickers": ["AAPL.NAS"],
    }
    if generated_at is not None:
        artifact["generated_at"] = generated_at
    return artifact


def test_write_ai_brief_report_writes_schema_and_offset_generated_at(
    tmp_path: Path,
) -> None:
    out_path = write_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=_artifact(),
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert Path(out_path).name == "2026-05-05.ai-brief.json"
    assert payload["schema"] == "sab.ai_brief.v1"
    assert payload["type"] == "ai_brief"
    assert payload["generated_at"] == "2026-05-05T08:40:00+00:00"
    assert payload["report_date"] == "2026-05-05"
    assert payload["recommendations"][0]["ticker"] == "AAPL.NAS"


def test_write_ai_brief_report_rejects_generated_at_without_offset(
    tmp_path: Path,
) -> None:
    artifact = _artifact(generated_at="2026-05-05T08:40:00")

    with pytest.raises(AiBriefValidationError, match="generated_at"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_recommendation_for_ineligible_ticker(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["recommendations"] = [
        {
            **artifact["recommendations"][0],  # type: ignore[index]
            "ticker": "NVDA.NAS",
        }
    ]

    with pytest.raises(AiBriefValidationError, match="eligible"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_review_or_skip_recommendation(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["recommendations"] = [
        {
            **artifact["recommendations"][0],  # type: ignore[index]
            "action": "REVIEW",
        }
    ]

    with pytest.raises(AiBriefValidationError, match="ENTER"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_duplicate_recommendation_ranks(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    second = {
        **artifact["recommendations"][0],  # type: ignore[index]
        "ticker": "MSFT.NAS",
        "rank": 1,
    }
    artifact["eligible_tickers"] = ["AAPL.NAS", "MSFT.NAS"]
    artifact["recommendations"] = [
        artifact["recommendations"][0],  # type: ignore[index]
        second,
    ]

    with pytest.raises(AiBriefValidationError, match="rank"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_more_than_three_sources(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["sources"] = [
        {
            "title": f"source {idx}",
            "url": f"https://example.test/{idx}",
            "published_at": "2026-05-05T08:00:00+09:00",
        }
        for idx in range(4)
    ]
    artifact["recommendations"] = [recommendation]

    with pytest.raises(AiBriefValidationError, match="sources"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_sources_older_than_72_hours(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["sources"] = [
        {
            "title": "stale source",
            "url": "https://example.test/stale",
            "published_at": "2026-05-01T08:39:59+09:00",
        }
    ]
    artifact["recommendations"] = [recommendation]

    with pytest.raises(AiBriefValidationError, match="72h"):
        write_ai_brief_report(
            report_dir=tmp_path.as_posix(),
            artifact=artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )
