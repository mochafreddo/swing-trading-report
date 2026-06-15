from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sab.report.ai_brief_report import (
    AiBriefValidationError,
    validate_ai_brief_artifact,
    write_ai_brief_report,
)
from sab.report.ai_brief_state import (
    export_ai_brief_state_contract,
    infer_ai_brief_state,
    read_ai_brief_state,
    validate_optional_ai_brief_state_fields,
)

_ROOT = Path(__file__).resolve().parents[1]
_AI_BRIEF_STATE_CONTRACT_PATH = (
    _ROOT / "web" / "src" / "components" / "reports" / "ai-brief-state-contract.json"
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


def _watch_candidate(
    ticker: str = "MSFT.NAS",
    *,
    action: str = "WATCH",
    reason: str = "entry trigger is pending re-confirmation",
    retrigger_conditions: list[str] | None = None,
    sources: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reason": reason,
        "retrigger_conditions": retrigger_conditions
        if retrigger_conditions is not None
        else ["price must satisfy the original entry trigger again"],
        "sources": [] if sources is None else sources,
        "as_of": "2026-05-05T08:40:00+00:00",
    }


def _artifact_with_watch() -> dict[str, object]:
    artifact = _artifact()
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {
        **summary,
        "recommendable_count": 1,
        "watch_count": 1,
        "source_issue_count": 1,
        "system_issue_count": 0,
    }
    artifact["watch_tickers"] = ["MSFT.NAS"]
    artifact["watch_candidates"] = [_watch_candidate()]
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
    assert payload["brief_state"] == "NEEDS_REVIEW_WEAK_NEWS"
    assert payload["brief_reason"] == "weak_news_coverage"


def test_write_ai_brief_report_marks_no_signal_when_no_enter_candidates(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {
        **summary,
        "preselected_count": 0,
        "recommendation_count": 0,
        "source_issue_count": 0,
        "system_issue_count": 0,
    }
    artifact["recommendations"] = []
    artifact["source_issues"] = []
    artifact["system_issues"] = []
    artifact["eligible_tickers"] = []

    out_path = write_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["brief_state"] == "NO_SIGNAL"
    assert payload["brief_reason"] == "no_enter_candidates"


def test_write_ai_brief_report_marks_source_backed_final_judgment(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["sources"] = [
        {
            "title": "Apple supply chain update",
            "url": "https://example.test/aapl",
            "published_at": "2026-05-05T08:00:00+00:00",
        }
    ]
    artifact["recommendations"] = [recommendation]
    artifact["source_issues"] = []
    artifact["system_issues"] = []
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {
        **summary,
        "source_issue_count": 0,
        "system_issue_count": 0,
    }

    out_path = write_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["brief_state"] == "FINAL_JUDGMENT"
    assert payload["brief_reason"] == "source_backed_final"


def test_write_ai_brief_report_rejects_stale_issue_summary_counts(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["sources"] = [
        {
            "title": "Apple supply chain update",
            "url": "https://example.test/aapl",
            "published_at": "2026-05-05T08:00:00+00:00",
        }
    ]
    artifact["recommendations"] = [recommendation]
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {
        **summary,
        "source_issue_count": 0,
        "system_issue_count": 0,
    }

    with pytest.raises(AiBriefValidationError, match="source_issue_count"):
        write_ai_brief_report(
            report_dir=tmp_path.as_posix(),
            artifact=artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_write_ai_brief_report_accepts_cap_excluded_review_and_skip_actions(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {**summary, "cap_excluded_count": 2}
    artifact["cap_excluded_candidates"] = [
        {
            "ticker": "COHR.NYS",
            "action": "REVIEW",
            "reason": "preselection cap 5 exceeded",
        },
        {
            "ticker": "CAT.NYS",
            "action": "SKIP",
            "reason": "preselection cap 5 exceeded",
        },
    ]

    out_path = write_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert [row["action"] for row in payload["cap_excluded_candidates"]] == [
        "REVIEW",
        "SKIP",
    ]


def test_write_ai_brief_report_accepts_excluded_enter_action(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["excluded_candidates"] = [
        {
            "ticker": "AAPL.NAS",
            "action": "ENTER",
            "reason": "entry row failed AI brief base gates: entry_state=WAITING",
        }
    ]
    artifact["recommendations"] = []
    artifact["eligible_tickers"] = []
    artifact["source_issues"] = []
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {
        **summary,
        "preselected_count": 0,
        "recommendation_count": 0,
        "excluded_count": 1,
        "source_issue_count": 0,
    }

    out_path = write_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["excluded_candidates"][0]["action"] == "ENTER"


def test_validate_ai_brief_artifact_accepts_legacy_missing_state() -> None:
    payload = {
        "schema": "sab.ai_brief.v1",
        "type": "ai_brief",
        "generated_at": "2026-05-05T08:40:00+00:00",
        "report_date": "2026-05-05",
        **_artifact(),
    }

    validate_ai_brief_artifact(
        payload,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )


def test_validate_ai_brief_artifact_rejects_invalid_state_and_reason() -> None:
    payload = {
        "schema": "sab.ai_brief.v1",
        "type": "ai_brief",
        "generated_at": "2026-05-05T08:40:00+00:00",
        "report_date": "2026-05-05",
        **_artifact(),
        "brief_state": "REST",
        "brief_reason": "weak_news_coverage",
    }

    with pytest.raises(AiBriefValidationError, match="brief_state"):
        validate_ai_brief_artifact(
            payload,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )

    payload["brief_state"] = "NEEDS_REVIEW_WEAK_NEWS"
    payload["brief_reason"] = "unknown_reason"
    with pytest.raises(AiBriefValidationError, match="brief_reason"):
        validate_ai_brief_artifact(
            payload,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_validate_ai_brief_artifact_rejects_state_that_disagrees_with_artifact() -> (
    None
):
    payload = {
        "schema": "sab.ai_brief.v1",
        "type": "ai_brief",
        "generated_at": "2026-05-05T08:40:00+00:00",
        "report_date": "2026-05-05",
        **_artifact(),
        "brief_state": "FINAL_JUDGMENT",
        "brief_reason": "source_backed_final",
    }

    with pytest.raises(AiBriefValidationError, match="deterministic inference"):
        validate_ai_brief_artifact(
            payload,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


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


def test_write_ai_brief_report_rejects_non_contiguous_recommendation_ranks(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    second = {
        **artifact["recommendations"][0],  # type: ignore[index]
        "ticker": "MSFT.NAS",
        "rank": 3,
    }
    artifact["eligible_tickers"] = ["AAPL.NAS", "MSFT.NAS"]
    artifact["recommendations"] = [
        artifact["recommendations"][0],  # type: ignore[index]
        second,
    ]
    source_issues = artifact["source_issues"]
    assert isinstance(source_issues, list)
    artifact["source_issues"] = [
        *source_issues,
        {
            "ticker": "MSFT.NAS",
            "code": "fake_provider_no_external_sources",
            "severity": "WARN",
            "message": "fake provider does not collect external sources",
        },
    ]

    with pytest.raises(AiBriefValidationError, match="contiguous"):
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


def test_write_ai_brief_report_rejects_invalid_source_url(tmp_path: Path) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["sources"] = [
        {
            "title": "bad source",
            "url": "https://token@example.test/source",
            "published_at": "2026-05-05T08:00:00+09:00",
        }
    ]
    artifact["recommendations"] = [recommendation]

    with pytest.raises(AiBriefValidationError, match="userinfo"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_future_source_dates(tmp_path: Path) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["sources"] = [
        {
            "title": "future source",
            "url": "https://example.test/future",
            "published_at": "2026-05-05T09:00:01+00:00",
        }
    ]
    artifact["recommendations"] = [recommendation]

    with pytest.raises(AiBriefValidationError, match="15m"):
        write_ai_brief_report(
            report_dir=tmp_path.as_posix(),
            artifact=artifact,
            now=datetime(2026, 5, 5, 8, 45, tzinfo=UTC),
        )


def test_write_ai_brief_report_allows_openai_model_provider(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["model_provider"] = "openai"
    artifact["model_name"] = "gpt-test"

    out_path = write_ai_brief_report(
        report_dir=tmp_path.as_posix(),
        artifact=artifact,
        now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
    )

    payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert payload["model_provider"] == "openai"
    assert payload["model_name"] == "gpt-test"


def test_write_ai_brief_report_rejects_automated_order_language(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["checklist"] = ["buy now without any manual review"]
    artifact["recommendations"] = [recommendation]

    with pytest.raises(AiBriefValidationError, match="automated-order"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_korean_automated_order_language(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    recommendation = dict(artifact["recommendations"][0])  # type: ignore[index]
    recommendation["checklist"] = ["지금 매수하고 주문 실행"]
    artifact["recommendations"] = [recommendation]

    with pytest.raises(AiBriefValidationError, match="automated-order"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_requires_source_issue_when_sources_are_empty(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["source_issues"] = []

    with pytest.raises(AiBriefValidationError, match="source issue"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_unknown_vetoed_candidate(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    artifact["vetoed_candidates"] = [
        {
            "ticker": "MSFT.NAS",
            "action": "SKIP",
            "reason": "model tried to veto an ineligible ticker",
        }
    ]

    with pytest.raises(AiBriefValidationError, match="vetoed_candidates"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_watch_candidate_blank_ticker(
    tmp_path: Path,
) -> None:
    artifact = _artifact_with_watch()
    artifact["watch_candidates"] = [_watch_candidate("")]

    with pytest.raises(AiBriefValidationError, match=r"watch_candidates\[0\].ticker"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"reason": ""}, "reason"),
        ({"retrigger_conditions": []}, "retrigger_conditions"),
        ({"retrigger_conditions": ["   "]}, "retrigger_conditions"),
        ({"retrigger_conditions": [{}]}, "retrigger_conditions"),
    ],
)
def test_write_ai_brief_report_rejects_watch_candidate_required_text(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    artifact = _artifact_with_watch()
    watch_candidate = _watch_candidate()
    watch_candidate.update(override)
    artifact["watch_candidates"] = [watch_candidate]

    with pytest.raises(AiBriefValidationError, match=message):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


@pytest.mark.parametrize("missing_field", ["watch_tickers", "watch_candidates"])
def test_write_ai_brief_report_requires_watch_fields_together(
    tmp_path: Path,
    missing_field: str,
) -> None:
    artifact = _artifact_with_watch()
    artifact.pop(missing_field)

    with pytest.raises(AiBriefValidationError, match=missing_field):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_watch_candidate_automated_order_language(
    tmp_path: Path,
) -> None:
    artifact = _artifact_with_watch()
    artifact["watch_candidates"] = [
        _watch_candidate(
            reason="buy now when the trigger recovers",
            retrigger_conditions=["execute order immediately"],
        )
    ]

    with pytest.raises(AiBriefValidationError, match="automated-order"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            {
                "title": "bad url",
                "url": "https://token@example.test/source",
                "published_at": "2026-05-05T08:00:00+00:00",
            },
            "userinfo",
        ),
        (
            {
                "title": "stale source",
                "url": "https://example.test/stale",
                "published_at": "2026-05-01T08:39:59+00:00",
            },
            "72h",
        ),
    ],
)
def test_write_ai_brief_report_rejects_bad_watch_candidate_sources(
    tmp_path: Path,
    source: dict[str, object],
    message: str,
) -> None:
    artifact = _artifact_with_watch()
    artifact["watch_candidates"] = [_watch_candidate(sources=[source])]

    with pytest.raises(AiBriefValidationError, match=message):
        write_ai_brief_report(
            report_dir=tmp_path.as_posix(),
            artifact=artifact,
            now=datetime(2026, 5, 5, 8, 40, tzinfo=UTC),
        )


def test_write_ai_brief_report_rejects_watch_candidate_order_mismatch(
    tmp_path: Path,
) -> None:
    artifact = _artifact_with_watch()
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {**summary, "watch_count": 2}
    artifact["watch_tickers"] = ["MSFT.NAS", "TSLA.NAS"]
    artifact["watch_candidates"] = [
        _watch_candidate("TSLA.NAS"),
        _watch_candidate("MSFT.NAS"),
    ]

    with pytest.raises(AiBriefValidationError, match="watch_candidates"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_bad_summary_counts(tmp_path: Path) -> None:
    artifact = _artifact_with_watch()
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {
        **summary,
        "recommendation_count": 99,
        "watch_count": 42,
    }

    with pytest.raises(AiBriefValidationError, match="recommendation_count"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


@pytest.mark.parametrize("entry_count", [True, "2", -1])
def test_write_ai_brief_report_rejects_bad_summary_entry_count(
    tmp_path: Path,
    entry_count: object,
) -> None:
    artifact = _artifact_with_watch()
    summary = artifact["summary"]
    assert isinstance(summary, dict)
    artifact["summary"] = {**summary, "entry_count": entry_count}

    with pytest.raises(AiBriefValidationError, match=r"summary\.entry_count"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_write_ai_brief_report_rejects_bad_source_provider_summary_totals(
    tmp_path: Path,
) -> None:
    artifact = _artifact_with_watch()
    artifact["source_provider_summary"] = {
        "chain": ["finnhub"],
        "providers": [
            {
                "provider": "finnhub",
                "status": "success",
                "covered": 1,
                "total": 2,
            }
        ],
        "final": {
            "recommendable_covered": 1,
            "recommendable_total": 1,
            "watch_covered": 0,
            "watch_total": 99,
        },
    }

    with pytest.raises(AiBriefValidationError, match="watch_total"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


@pytest.mark.parametrize(
    ("provider", "status", "message"),
    [
        ("polygon-news", "success", "chain"),
        ("finnhub", "completed", "status"),
    ],
)
def test_write_ai_brief_report_rejects_bad_source_provider_summary_provider_status(
    tmp_path: Path,
    provider: str,
    status: str,
    message: str,
) -> None:
    artifact = _artifact_with_watch()
    artifact["source_provider_summary"] = {
        "chain": ["finnhub"],
        "providers": [
            {
                "provider": provider,
                "status": status,
                "covered": 1,
                "total": 1,
            }
        ],
        "final": {
            "recommendable_covered": 1,
            "recommendable_total": 1,
            "watch_covered": 0,
            "watch_total": 1,
        },
    }

    with pytest.raises(AiBriefValidationError, match=message):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


@pytest.mark.parametrize(
    ("chain", "providers"),
    [
        (
            ["none"],
            [
                {
                    "provider": "none",
                    "status": "success",
                    "covered": 0,
                    "total": 0,
                }
            ],
        ),
        (
            ["finnhub", "benzinga-news"],
            [
                {
                    "provider": "finnhub",
                    "status": "success",
                    "covered": 1,
                    "total": 1,
                }
            ],
        ),
        (
            ["finnhub", "benzinga-news"],
            [
                {
                    "provider": "finnhub",
                    "status": "success",
                    "covered": 1,
                    "total": 1,
                },
                {
                    "provider": "finnhub",
                    "status": "skipped",
                    "covered": 0,
                    "total": 1,
                },
            ],
        ),
        (
            ["finnhub", "benzinga-news"],
            [
                {
                    "provider": "benzinga-news",
                    "status": "success",
                    "covered": 1,
                    "total": 1,
                },
                {
                    "provider": "finnhub",
                    "status": "success",
                    "covered": 1,
                    "total": 1,
                },
            ],
        ),
    ],
)
def test_write_ai_brief_report_rejects_source_provider_summary_chain_mismatch(
    tmp_path: Path,
    chain: list[str],
    providers: list[dict[str, object]],
) -> None:
    artifact = _artifact_with_watch()
    artifact["source_provider_summary"] = {
        "chain": chain,
        "providers": providers,
        "final": {
            "recommendable_covered": 1,
            "recommendable_total": 1,
            "watch_covered": 0,
            "watch_total": 1,
        },
    }

    with pytest.raises(AiBriefValidationError, match="providers"):
        write_ai_brief_report(report_dir=tmp_path.as_posix(), artifact=artifact)


def test_ai_brief_state_contract_matches_committed_web_artifact() -> None:
    committed_contract = json.loads(
        _AI_BRIEF_STATE_CONTRACT_PATH.read_text(encoding="utf-8")
    )

    assert committed_contract == export_ai_brief_state_contract()


@pytest.mark.parametrize(
    ("rule_id", "payload", "state", "reason"),
    [
        (
            "no_signal",
            {
                "summary": {
                    "preselected_count": 0,
                    "recommendation_count": 0,
                    "source_issue_count": 0,
                    "system_issue_count": 0,
                },
                "eligible_tickers": [],
                "recommendations": [],
                "source_issues": [],
                "system_issues": [],
            },
            "NO_SIGNAL",
            "no_enter_candidates",
        ),
        (
            "source_backed_final",
            {
                "summary": {
                    "preselected_count": 1,
                    "recommendation_count": 1,
                    "source_issue_count": 0,
                    "system_issue_count": 0,
                },
                "eligible_tickers": ["AAPL.NAS"],
                "recommendations": [
                    {
                        "ticker": "AAPL.NAS",
                        "sources": [
                            {
                                "title": "Apple update",
                                "url": "https://example.test/aapl",
                            }
                        ],
                    }
                ],
                "source_issues": [],
                "system_issues": [],
            },
            "FINAL_JUDGMENT",
            "source_backed_final",
        ),
        (
            "system_issue",
            {
                "summary": {
                    "preselected_count": 1,
                    "recommendation_count": 0,
                    "source_issue_count": 0,
                    "system_issue_count": 1,
                },
                "eligible_tickers": ["005930"],
                "recommendations": [],
                "source_issues": [],
                "system_issues": [{"code": "model_provider_failed"}],
            },
            "NEEDS_REVIEW_WEAK_NEWS",
            "model_or_system_issue",
        ),
        (
            "weak_news_coverage",
            {
                "summary": {
                    "preselected_count": 1,
                    "recommendation_count": 1,
                    "source_issue_count": 0,
                    "system_issue_count": 0,
                },
                "eligible_tickers": ["AAPL.NAS"],
                "recommendations": [{"ticker": "AAPL.NAS", "sources": []}],
                "source_issues": [],
                "system_issues": [],
            },
            "NEEDS_REVIEW_WEAK_NEWS",
            "weak_news_coverage",
        ),
        (
            "model_deferred",
            {
                "summary": {
                    "preselected_count": 1,
                    "recommendation_count": 0,
                    "source_issue_count": 0,
                    "system_issue_count": 0,
                },
                "eligible_tickers": ["005930"],
                "recommendations": [],
                "source_issues": [],
                "system_issues": [],
            },
            "NEEDS_REVIEW_WEAK_NEWS",
            "model_deferred",
        ),
    ],
)
def test_ai_brief_state_contract_drives_python_state_helpers(
    rule_id: str,
    payload: dict[str, object],
    state: str,
    reason: str,
) -> None:
    contract = export_ai_brief_state_contract()
    rule = contract["rules"][rule_id]

    inferred = infer_ai_brief_state(payload)
    assert inferred.state == rule["state"] == state
    assert inferred.reason == rule["reason"] == reason

    payload_with_explicit = {
        **payload,
        "brief_state": rule["state"],
        "brief_reason": rule["reason"],
    }
    validate_optional_ai_brief_state_fields(payload_with_explicit)
    assert read_ai_brief_state(payload_with_explicit) == inferred


def test_ai_brief_state_helpers_fall_back_when_explicit_contract_fields_invalid() -> (
    None
):
    payload = {
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": ["005930"],
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
        "brief_state": "FINAL_JUDGMENT",
        "brief_reason": "source_backed_final",
    }

    with pytest.raises(ValueError, match="deterministic inference"):
        validate_optional_ai_brief_state_fields(payload)

    inferred = read_ai_brief_state(payload)
    assert inferred.state == "NEEDS_REVIEW_WEAK_NEWS"
    assert inferred.reason == "model_deferred"
