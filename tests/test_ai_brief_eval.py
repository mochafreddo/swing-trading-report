from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from sab import ai_brief_eval
from sab.ai_brief_eval import (
    evaluate_ai_brief_recommendation_report,
    parse_eval_now,
)
from scripts.eval_ai_brief_recommendations import main as eval_brief_main

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


def _write_payload(tmp_path: Path, name: str, payload: Mapping[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_posix()


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def _copy_mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, Mapping)
    return dict(value)


def _copy_mapping_rows(value: object) -> list[dict[str, Any]]:
    assert isinstance(value, list)
    rows: list[dict[str, Any]] = []
    for row in value:
        assert isinstance(row, Mapping)
        rows.append(dict(row))
    return rows


def _unbacked_payload(*, confidence: str = "LOW") -> dict[str, Any]:
    payload = _load_good_ai_brief()
    recommendations = _copy_mapping_rows(payload["recommendations"])
    first = dict(recommendations[0])
    first["sources"] = []
    first["confidence"] = confidence
    recommendations[0] = first
    payload["recommendations"] = recommendations
    payload["source_issues"] = [
        {
            "ticker": "AAPL.NAS",
            "code": "openai_no_external_sources",
            "severity": "WARN",
            "message": "OpenAI provider returned no usable source for this ticker",
        }
    ]
    summary = _copy_mapping(payload["summary"])
    summary["source_issue_count"] = 1
    payload["summary"] = summary
    return payload


def _entry_row(
    ticker: str,
    *,
    action: str = "ENTER",
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reasons": reasons or ["entry conditions satisfied"],
        "entry_state": "READY",
        "entry_price_status": "available",
    }


def _ai_brief_recommendation(ticker: str, *, rank: int = 1) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": None,
        "rank": rank,
        "action": "ENTER",
        "confidence": "MEDIUM",
        "rationale": ["AI brief inclusion is supported by classifier role"],
        "checklist": ["manually confirm current price and risk limits"],
        "sources": [
            {
                "title": f"{ticker} source",
                "url": f"https://news.example.test/{ticker.lower()}",
                "published_at": "2026-05-06T10:00:00+00:00",
            }
        ],
        "as_of": "2026-05-06T12:00:00+00:00",
    }


def _watch_candidate(ticker: str, *, action: str = "WATCH") -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reason": "entry trigger is pending re-confirmation",
        "retrigger_conditions": ["price must satisfy the original trigger again"],
        "sources": [],
        "as_of": "2026-05-06T12:00:00+00:00",
    }


def _ai_brief_payload(
    *,
    entry_count: int,
    recommendable_count: int | None = None,
    watch_count: int | None = None,
    eligible_tickers: list[str],
    recommendations: list[dict[str, object]],
    watch_tickers: list[str] | None = None,
    watch_candidates: list[dict[str, object]] | None = None,
    excluded_candidates: list[dict[str, object]] | None = None,
    cap_excluded_candidates: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    watch_tickers = watch_tickers or []
    watch_candidates = watch_candidates or []
    excluded_candidates = excluded_candidates or []
    cap_excluded_candidates = cap_excluded_candidates or []
    return {
        "schema": "sab.ai_brief.v1",
        "type": "ai_brief",
        "generated_at": "2026-05-06T12:00:00+00:00",
        "report_date": "2026-05-06",
        "source_entry_report": "entry.us.json",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {
            "entry_count": entry_count,
            "recommendable_count": (
                len(eligible_tickers) + len(cap_excluded_candidates)
                if recommendable_count is None
                else recommendable_count
            ),
            "watch_count": len(watch_tickers) if watch_count is None else watch_count,
            "preselected_count": len(eligible_tickers),
            "recommendation_count": len(recommendations),
            "excluded_count": len(excluded_candidates),
            "vetoed_count": 0,
            "cap_excluded_count": len(cap_excluded_candidates),
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "recommendations": recommendations,
        "excluded_candidates": excluded_candidates,
        "vetoed_candidates": [],
        "watch_candidates": watch_candidates,
        "cap_excluded_candidates": cap_excluded_candidates,
        "source_issues": [],
        "system_issues": [],
        "eligible_tickers": eligible_tickers,
        "watch_tickers": watch_tickers,
    }


def test_ai_brief_eval_passes_source_backed_artifact() -> None:
    legacy_payload = _load_good_ai_brief()
    assert "brief_state" not in legacy_payload
    assert "brief_reason" not in legacy_payload

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=_fixture("ai-brief.good.json"),
    )

    assert result.status == "PASS"
    assert result.summary["entry_count"] == 8
    assert result.summary["expected_preselected_count"] == 5
    assert result.summary["recommendation_count"] == 3
    assert result.summary["source_backed_recommendation_count"] == 3
    assert result.summary["source_backed_ratio"] == 1.0
    assert result.issues == []


def test_ai_brief_eval_accepts_legacy_artifact_without_expanded_summary_counts(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    summary = _copy_mapping(payload["summary"])
    summary.pop("recommendable_count")
    summary.pop("watch_count")
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "legacy-counts.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.issues == []


def test_ai_brief_eval_accepts_legacy_artifact_with_old_style_entry_rows(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.legacy-shape.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                {"ticker": "AAPL.NAS", "action": "ENTER"},
                {"ticker": "MSFT.NAS", "action": "ENTER"},
                {"ticker": "NVDA.NAS", "action": "REVIEW"},
                {"ticker": "META.NAS", "action": "SKIP"},
                {"ticker": "TSLA.NAS", "action": "ENTER"},
                {"ticker": "AMZN.NAS", "action": "ENTER"},
                {"ticker": "GOOGL.NAS", "action": "ENTER"},
                {"ticker": "NFLX.NAS", "action": "ENTER"},
            ],
            "summary": {"entry_count": 8},
            "system_issues": [],
        },
    )
    payload = _load_good_ai_brief()
    summary = _copy_mapping(payload["summary"])
    summary.pop("recommendable_count")
    summary.pop("watch_count")
    payload["summary"] = summary
    report_path = _write_payload(
        tmp_path,
        "ai-brief.legacy-entry-shape.json",
        payload,
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.issues == []


def test_ai_brief_eval_accepts_promoted_recommendable_skip_and_review(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.promoted.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "CAT.NYS",
                    action="SKIP",
                    reasons=["portfolio market cap reached (US)"],
                ),
                _entry_row(
                    "CIFR.NAS",
                    action="REVIEW",
                    reasons=[
                        "hybrid risk_alignment requires manual review "
                        "(tight_stop_vs_volatility: gap_guard_exceeds_stop_max)"
                    ],
                ),
                _entry_row(
                    "NVDA.NAS",
                    action="REVIEW",
                    reasons=["manual review required by analyst"],
                ),
            ],
            "system_issues": [],
        },
    )
    report_path = _write_payload(
        tmp_path,
        "ai-brief.promoted.json",
        _ai_brief_payload(
            entry_count=4,
            eligible_tickers=["AAPL.NAS", "CAT.NYS", "CIFR.NAS"],
            recommendations=[
                _ai_brief_recommendation("CAT.NYS", rank=1),
                _ai_brief_recommendation("CIFR.NAS", rank=2),
            ],
            excluded_candidates=[
                {
                    "ticker": "NVDA.NAS",
                    "action": "REVIEW",
                    "reason": "action REVIEW did not match an AI brief inclusion rule",
                }
            ],
        ),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.issues == []


def test_ai_brief_eval_accepts_watch_only_candidate_contract(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.watch.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "MSFT.NAS",
                    action="SKIP",
                    reasons=["hybrid trigger guard failed (302.00 < ema10 303.00)"],
                ),
            ],
            "system_issues": [],
        },
    )
    report_path = _write_payload(
        tmp_path,
        "ai-brief.watch.json",
        _ai_brief_payload(
            entry_count=2,
            eligible_tickers=["AAPL.NAS"],
            recommendations=[_ai_brief_recommendation("AAPL.NAS")],
            watch_tickers=["MSFT.NAS"],
            watch_candidates=[_watch_candidate("MSFT.NAS")],
        ),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.issues == []


def test_ai_brief_eval_rejects_new_format_watch_artifact_without_expanded_summary_counts(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.watch-missing-counts.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "MSFT.NAS",
                    action="SKIP",
                    reasons=["hybrid trigger guard failed (302.00 < ema10 303.00)"],
                ),
            ],
            "system_issues": [],
        },
    )
    payload = _ai_brief_payload(
        entry_count=2,
        eligible_tickers=["AAPL.NAS"],
        recommendations=[_ai_brief_recommendation("AAPL.NAS")],
        watch_tickers=["MSFT.NAS"],
        watch_candidates=[_watch_candidate("MSFT.NAS")],
    )
    summary = _copy_mapping(payload["summary"])
    summary.pop("recommendable_count")
    summary.pop("watch_count")
    payload["summary"] = summary
    report_path = _write_payload(
        tmp_path,
        "ai-brief.watch-missing-counts.json",
        payload,
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_fails_when_watch_fields_do_not_match_classifier(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.bad-watch.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "MSFT.NAS",
                    action="SKIP",
                    reasons=["hybrid trigger guard failed (302.00 < ema10 303.00)"],
                ),
            ],
            "system_issues": [],
        },
    )
    report_path = _write_payload(
        tmp_path,
        "ai-brief.bad-watch.json",
        _ai_brief_payload(
            entry_count=2,
            eligible_tickers=["AAPL.NAS"],
            recommendations=[_ai_brief_recommendation("AAPL.NAS")],
            watch_tickers=["TSLA.NAS"],
            watch_candidates=[_watch_candidate("TSLA.NAS")],
        ),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert {
        "watch_tickers_mismatch",
        "watch_candidates_mismatch",
    }.issubset(_issue_codes(result))


def test_ai_brief_eval_fails_closed_for_malformed_watch_artifact(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.malformed-watch.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "MSFT.NAS",
                    action="SKIP",
                    reasons=["hybrid trigger guard failed (302.00 < ema10 303.00)"],
                ),
            ],
            "system_issues": [],
        },
    )
    report_path = _write_payload(
        tmp_path,
        "ai-brief.malformed-watch.json",
        _ai_brief_payload(
            entry_count=2,
            eligible_tickers=["AAPL.NAS"],
            recommendations=[_ai_brief_recommendation("AAPL.NAS")],
            watch_tickers=["MSFT.NAS"],
            watch_candidates=[_watch_candidate("")],
        ),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_fails_when_expanded_summary_counts_are_wrong(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.bad-summary-expanded.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "MSFT.NAS",
                    action="SKIP",
                    reasons=["hybrid trigger guard failed (302.00 < ema10 303.00)"],
                ),
            ],
            "system_issues": [],
        },
    )
    report_path = _write_payload(
        tmp_path,
        "ai-brief.bad-summary-expanded.json",
        _ai_brief_payload(
            entry_count=2,
            recommendable_count=99,
            watch_count=42,
            eligible_tickers=["AAPL.NAS"],
            recommendations=[_ai_brief_recommendation("AAPL.NAS")],
            watch_tickers=["MSFT.NAS"],
            watch_candidates=[_watch_candidate("MSFT.NAS")],
        ),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


@pytest.mark.parametrize("missing_field", ["recommendable_count", "watch_count"])
def test_ai_brief_eval_fails_when_only_one_expanded_summary_count_is_missing(
    tmp_path: Path,
    missing_field: str,
) -> None:
    payload = _load_good_ai_brief()
    summary = _copy_mapping(payload["summary"])
    summary.pop(missing_field)
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "partial-expanded.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_fails_when_eligible_tickers_do_not_match_entry_report(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["eligible_tickers"] = ["AAPL.NAS", "MSFT.NAS", "TSLA.NAS"]
    summary = _copy_mapping(payload["summary"])
    summary["preselected_count"] = 3
    summary["recommendable_count"] = 4
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "bad-eligible.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "eligible_tickers_mismatch" in _issue_codes(result)


def test_ai_brief_eval_fails_when_summary_counts_do_not_match_arrays(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    summary = _copy_mapping(payload["summary"])
    summary["recommendation_count"] = 99
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "bad-summary.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_fails_when_recommendation_ranks_are_not_contiguous(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    recommendations = _copy_mapping_rows(payload["recommendations"])
    recommendations[1]["rank"] = 4
    payload["recommendations"] = recommendations
    report_path = _write_payload(tmp_path, "bad-ranks.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "recommendation_ranks_not_contiguous" in _issue_codes(result)


def test_ai_brief_eval_fails_when_recommendation_ticker_is_duplicated(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    recommendations = _copy_mapping_rows(payload["recommendations"])
    recommendations[1]["ticker"] = "AAPL.NAS"
    payload["recommendations"] = recommendations
    report_path = _write_payload(tmp_path, "duplicate-ticker.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "recommendation_ticker_duplicate" in _issue_codes(result)


def test_ai_brief_eval_fails_when_excluded_candidates_do_not_match_entry_report(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["excluded_candidates"] = []
    payload["cap_excluded_candidates"] = []
    summary = _copy_mapping(payload["summary"])
    summary["excluded_count"] = 0
    summary["cap_excluded_count"] = 0
    summary["recommendable_count"] = 5
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "bad-exclusions.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert {
        "excluded_candidates_mismatch",
        "cap_excluded_candidates_mismatch",
    }.issubset(_issue_codes(result))


def test_ai_brief_eval_fails_expanded_candidate_alignment_mismatches(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.expanded-mismatch.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "US",
            "entries": [
                _entry_row("AAPL.NAS"),
                _entry_row(
                    "CAT.NYS",
                    action="SKIP",
                    reasons=["portfolio market cap reached (US)"],
                ),
                _entry_row(
                    "CIFR.NAS",
                    action="REVIEW",
                    reasons=[
                        "hybrid risk_alignment requires manual review "
                        "(tight_stop_vs_volatility: gap_guard_exceeds_stop_max)"
                    ],
                ),
                _entry_row("MSFT.NAS"),
                _entry_row("TSLA.NAS"),
                _entry_row("AMZN.NAS"),
                _entry_row(
                    "IREN.NAS",
                    action="REVIEW",
                    reasons=[
                        "hybrid risk_alignment requires manual review "
                        "(tight_stop_vs_volatility: gap_guard_exceeds_stop_max)"
                    ],
                ),
                _entry_row(
                    "NVDA.NAS",
                    action="REVIEW",
                    reasons=["manual review required by analyst"],
                ),
            ],
            "system_issues": [],
        },
    )
    report_path = _write_payload(
        tmp_path,
        "ai-brief.expanded-mismatch.json",
        _ai_brief_payload(
            entry_count=8,
            eligible_tickers=["AAPL.NAS", "CIFR.NAS", "MSFT.NAS", "TSLA.NAS"],
            recommendations=[_ai_brief_recommendation("AAPL.NAS")],
            excluded_candidates=[],
            cap_excluded_candidates=[
                {
                    "ticker": "AMZN.NAS",
                    "action": "ENTER",
                    "reason": "preselection cap 5 exceeded",
                },
                {
                    "ticker": "IREN.NAS",
                    "action": "ENTER",
                    "reason": "preselection cap 5 exceeded",
                },
            ],
        ),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert {
        "eligible_tickers_mismatch",
        "excluded_candidates_mismatch",
        "cap_excluded_candidates_mismatch",
    }.issubset(_issue_codes(result))


def test_ai_brief_eval_fails_when_ai_brief_report_cannot_be_loaded(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "broken.ai-brief.json"
    report_path.write_text("{", encoding="utf-8")

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path.as_posix(),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_failed"}


def test_ai_brief_eval_fails_when_ai_brief_report_is_not_an_object(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "list.ai-brief.json"
    report_path.write_text("[]", encoding="utf-8")

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path.as_posix(),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_fails_when_generated_at_is_invalid(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["generated_at"] = "not-a-date"
    report_path = _write_payload(tmp_path, "bad-date.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_fails_silent_empty_recommendation_artifact(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["recommendations"] = []
    summary = _copy_mapping(payload["summary"])
    summary["recommendation_count"] = 0
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "empty.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "recommendation_report_empty" in _issue_codes(result)


def test_ai_brief_eval_fails_when_report_market_does_not_match_entry_market(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(
        tmp_path,
        "entry.kr.json",
        {
            "schema": "sab.report.v1",
            "type": "entry",
            "market": "KR",
            "entries": [{"ticker": "005930", "action": "ENTER"}],
        },
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert {
        "ai_brief_market_mismatch",
        "eligible_tickers_mismatch",
        "recommendation_ticker_not_preselected",
    }.issubset(_issue_codes(result))


def test_ai_brief_eval_fails_when_source_backed_ratio_is_below_default(
    tmp_path: Path,
) -> None:
    report_path = _write_payload(
        tmp_path,
        "unbacked-low.ai-brief.json",
        _unbacked_payload(confidence="LOW"),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert result.summary["source_backed_ratio"] == 2 / 3
    assert "source_backed_ratio_below_threshold" in _issue_codes(result)


def test_ai_brief_eval_fails_when_unbacked_recommendation_has_high_confidence(
    tmp_path: Path,
) -> None:
    report_path = _write_payload(
        tmp_path,
        "unbacked-high.ai-brief.json",
        _unbacked_payload(confidence="HIGH"),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        minimum_source_backed_ratio=0.0,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "unbacked_recommendation_confidence_too_high" in _issue_codes(result)


def test_ai_brief_eval_warns_for_low_confidence_unbacked_recommendation_with_issue(
    tmp_path: Path,
) -> None:
    report_path = _write_payload(
        tmp_path,
        "unbacked-low.ai-brief.json",
        _unbacked_payload(confidence="LOW"),
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        minimum_source_backed_ratio=0.0,
        now=EVAL_NOW,
    )

    assert result.status == "WARN"
    assert _issue_codes(result) == {
        "ai_brief_source_issue_reported",
        "unbacked_low_confidence_recommendation",
    }


def test_ai_brief_eval_fails_for_reported_system_error(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["system_issues"] = [
        {
            "code": "openai_response_contract_invalid",
            "severity": "ERROR",
            "message": "model output could not be parsed",
        }
    ]
    summary = _copy_mapping(payload["summary"])
    summary["entry_count"] = 999
    summary["system_issue_count"] = 1
    payload["summary"] = summary
    report_path = _write_payload(tmp_path, "system-error.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert {
        "ai_brief_system_issue_error",
        "summary_count_mismatch",
    }.issubset(_issue_codes(result))


def test_ai_brief_eval_reports_invalid_ai_brief_contract(tmp_path: Path) -> None:
    payload = _load_good_ai_brief()
    payload["model_provider"] = "unknown"
    report_path = _write_payload(tmp_path, "invalid.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"ai_brief_report_invalid"}


def test_ai_brief_eval_supports_mixed_entry_report_with_market_override(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(tmp_path, "entry.mixed.json", _mixed_entry_payload())

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        market="US",
        now=EVAL_NOW,
    )

    assert result.status == "PASS"


def test_ai_brief_eval_script_accepts_market_override_for_mixed_entry_report(
    capsys,
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(tmp_path, "entry.mixed.json", _mixed_entry_payload())

    exit_code = eval_brief_main(
        [
            "--entry-report",
            entry_path,
            "--ai-brief-report",
            _fixture("ai-brief.good.json"),
            "--market",
            "US",
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 0
    assert output["status"] == "PASS"


def test_ai_brief_eval_fails_for_mixed_entry_report_without_market(
    tmp_path: Path,
) -> None:
    entry_path = _write_payload(tmp_path, "entry.mixed.json", _mixed_entry_payload())

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"entry_report_market_required"}


def test_ai_brief_eval_fails_when_entry_report_cannot_be_loaded(
    tmp_path: Path,
) -> None:
    entry_path = tmp_path / "broken-entry.json"
    entry_path.write_text("{", encoding="utf-8")

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path.as_posix(),
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"entry_report_failed"}


def test_ai_brief_eval_fails_when_market_override_disagrees_with_entry_report() -> None:
    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        market="KR",
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"entry_report_market_mismatch"}


@pytest.mark.parametrize(
    ("entry_payload", "expected_code"),
    [
        (
            {"schema": "sab.report.v1", "type": "entry", "market": "EU", "entries": []},
            "entry_report_invalid",
        ),
        (
            {"schema": "sab.report.v1", "type": "entry", "market": "US", "entries": {}},
            "entry_report_invalid",
        ),
        (
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "US",
                "entries": ["ignored", {"ticker": "AAPL.NAS", "action": "HOLD"}],
            },
            "entry_report_invalid",
        ),
    ],
)
def test_ai_brief_eval_fails_for_invalid_entry_report_shape(
    tmp_path: Path,
    entry_payload: dict[str, object],
    expected_code: str,
) -> None:
    entry_path = _write_payload(tmp_path, "bad-entry.json", entry_payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_path,
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {expected_code}


def test_ai_brief_eval_script_outputs_pretty_json_and_returns_zero(capsys) -> None:
    exit_code = eval_brief_main(
        [
            "--entry-report",
            _fixture("entry.us.json"),
            "--ai-brief-report",
            _fixture("ai-brief.good.json"),
            "--now",
            "2026-05-06T12:00:00+00:00",
            "--pretty",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "PASS"
    assert "\n  " in captured.out


def test_ai_brief_eval_script_returns_nonzero_for_fail(
    capsys,
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    payload["eligible_tickers"] = ["AAPL.NAS"]
    report_path = _write_payload(tmp_path, "fail.ai-brief.json", payload)

    exit_code = eval_brief_main(
        [
            "--entry-report",
            _fixture("entry.us.json"),
            "--ai-brief-report",
            report_path,
        ]
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 1
    assert output["status"] == "FAIL"


def test_ai_brief_eval_script_returns_zero_for_warn(
    capsys,
    tmp_path: Path,
) -> None:
    report_path = _write_payload(
        tmp_path,
        "warn.ai-brief.json",
        _unbacked_payload(confidence="LOW"),
    )

    exit_code = eval_brief_main(
        [
            "--entry-report",
            _fixture("entry.us.json"),
            "--ai-brief-report",
            report_path,
            "--minimum-source-backed-ratio",
            "0",
        ]
    )

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert exit_code == 0
    assert output["status"] == "WARN"


def test_ai_brief_eval_script_exits_for_invalid_now(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        eval_brief_main(
            [
                "--entry-report",
                _fixture("entry.us.json"),
                "--ai-brief-report",
                _fixture("ai-brief.good.json"),
                "--now",
                "not-a-date",
            ]
        )

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "now must be an ISO 8601 datetime" in captured.err


def test_parse_eval_now_requires_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        parse_eval_now("2026-05-06T12:00:00")


def test_parse_eval_now_rejects_empty_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        parse_eval_now(" ")
    with pytest.raises(ValueError, match="ISO 8601"):
        parse_eval_now("not-a-date")


def test_ai_brief_eval_rejects_invalid_minimum_source_backed_ratio() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ai_brief_eval.evaluate_ai_brief_recommendation_report(
            entry_report_path=_fixture("entry.us.json"),
            ai_brief_report_path=_fixture("ai-brief.good.json"),
            minimum_source_backed_ratio=1.2,
        )


def test_ai_brief_eval_rejects_nan_minimum_source_backed_ratio() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ai_brief_eval.evaluate_ai_brief_recommendation_report(
            entry_report_path=_fixture("entry.us.json"),
            ai_brief_report_path=_fixture("ai-brief.good.json"),
            minimum_source_backed_ratio=float("nan"),
        )


def test_ai_brief_eval_rejects_invalid_market_override() -> None:
    with pytest.raises(ValueError, match="market must be KR or US"):
        ai_brief_eval.evaluate_ai_brief_recommendation_report(
            entry_report_path=_fixture("entry.us.json"),
            ai_brief_report_path=_fixture("ai-brief.good.json"),
            market="EU",
            now=EVAL_NOW,
        )


def test_ai_brief_eval_treats_blank_market_override_as_unspecified() -> None:
    result = ai_brief_eval.evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=_fixture("ai-brief.good.json"),
        market=" ",
        now=EVAL_NOW,
    )

    assert result.status == "PASS"


def _mixed_entry_payload() -> dict[str, object]:
    return {
        "schema": "sab.report.v1",
        "type": "entry",
        "market": "MIXED",
        "entries": [
            _entry_row("005930"),
            _entry_row("AAPL.NAS"),
            _entry_row("MSFT.NAS"),
            _entry_row("NVDA.NAS", action="REVIEW"),
            _entry_row("META.NAS", action="SKIP"),
            _entry_row("TSLA.NAS"),
            _entry_row("AMZN.NAS"),
            _entry_row("GOOGL.NAS"),
            _entry_row("NFLX.NAS"),
            _entry_row("000660.KS", action="SKIP"),
        ],
        "system_issues": [],
    }


def test_ai_brief_recommendation_issue_preserves_public_class_identity() -> None:
    issue = ai_brief_eval.AiBriefRecommendationEvalIssue(
        ticker="AAPL.NAS",
        code="source_issue",
        severity="WARN",
        message="missing source",
    )

    assert issue.__class__.__module__ == "sab.ai_brief_eval"
    assert issue.__class__.__name__ == "AiBriefRecommendationEvalIssue"
    assert repr(issue).startswith("AiBriefRecommendationEvalIssue(")
    assert issue.to_dict() == {
        "ticker": "AAPL.NAS",
        "code": "source_issue",
        "severity": "WARN",
        "message": "missing source",
    }
