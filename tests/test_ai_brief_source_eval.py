from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sab.ai_brief_source_eval import evaluate_ai_brief_source_report, parse_eval_now
from scripts.eval_ai_brief_sources import main as eval_sources_main

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_brief_sources"
EVAL_NOW = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC)


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).as_posix()


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_source_eval_passes_good_payload() -> None:
    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=_fixture("sources.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.summary["eligible_ticker_count"] == 3
    assert result.summary["covered_ticker_count"] == 3
    assert result.summary["coverage_ratio"] == 1.0
    assert result.summary["source_count"] == 3
    assert result.issues == []


def test_source_eval_fails_when_coverage_is_below_default_threshold() -> None:
    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=_fixture("sources.partial.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert result.summary["covered_ticker_count"] == 1
    assert result.summary["coverage_ratio"] == 1 / 3
    assert "source_coverage_below_threshold" in _issue_codes(result)


def test_source_eval_does_not_credit_ineligible_tickers() -> None:
    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=_fixture("sources.issues.json"),
        minimum_coverage_ratio=0.0,
        now=EVAL_NOW,
    )

    assert result.status == "WARN"
    assert result.summary["covered_ticker_count"] == 1
    assert result.summary["source_count"] == 1
    assert _issue_codes(result) == {
        "local_source_unknown_ticker",
        "local_source_stale",
        "local_source_invalid_row",
    }


def test_source_eval_detects_duplicate_urls_and_cap_exceeded() -> None:
    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=_fixture("sources.duplicates-cap.json"),
        now=EVAL_NOW,
    )

    assert result.status == "WARN"
    assert result.summary["covered_ticker_count"] == 3
    assert result.summary["source_count"] == 5
    assert result.summary["duplicate_url_count"] == 1
    assert _issue_codes(result) == {
        "local_source_cap_exceeded",
        "local_source_duplicate_url",
    }


def test_source_eval_preserves_collector_payload_issues(tmp_path: Path) -> None:
    source_report = tmp_path / "collector-warning.sources.json"
    source_report.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_sources.v1",
                "type": "ai_brief_sources",
                "generated_at": EVAL_NOW.isoformat(),
                "status": "WARN",
                "summary": {
                    "source_count": 3,
                    "covered_ticker_count": 3,
                    "covered_tickers": ["AAPL.NAS", "MSFT.NAS", "NVDA.NAS"],
                    "issue_count": 1,
                },
                "sources": [
                    {
                        "ticker": "AAPL.NAS",
                        "title": "Apple source",
                        "url": "https://news.example.test/aapl",
                        "published_at": "2026-05-06T10:00:00+00:00",
                    },
                    {
                        "ticker": "MSFT.NAS",
                        "title": "Microsoft source",
                        "url": "https://news.example.test/msft",
                        "published_at": "2026-05-06T09:30:00+00:00",
                    },
                    {
                        "ticker": "NVDA.NAS",
                        "title": "Nvidia source",
                        "url": "https://news.example.test/nvda",
                        "published_at": "2026-05-06T09:00:00+00:00",
                    },
                ],
                "issues": [
                    {
                        "ticker": "AAPL.NAS",
                        "code": "feed_item_duplicate_url",
                        "severity": "WARN",
                        "message": "duplicate feed item URL ignored",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=source_report.as_posix(),
        now=EVAL_NOW,
    )

    assert result.status == "WARN"
    assert result.summary["covered_ticker_count"] == 3
    assert _issue_codes(result) == {"feed_item_duplicate_url"}


def test_source_eval_treats_error_source_issue_as_failure(tmp_path: Path) -> None:
    source_report = tmp_path / "collector-error.sources.json"
    payload = json.loads(
        Path(_fixture("sources.good.json")).read_text(encoding="utf-8")
    )
    payload["issues"] = [
        {
            "ticker": "AAPL.NAS",
            "code": "feed_item_failed",
            "severity": "ERROR",
            "message": "collector failed for ticker feed",
        }
    ]
    source_report.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=source_report.as_posix(),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert result.issues[0].severity == "FAIL"
    assert _issue_codes(result) == {"feed_item_failed"}


def test_source_eval_fails_when_entry_report_has_no_enter_candidates(
    tmp_path: Path,
) -> None:
    entry_report = tmp_path / "empty.entry.json"
    entry_report.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "US",
                "entries": [{"ticker": "AAPL.NAS", "action": "REVIEW"}],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_ai_brief_source_report(
        entry_report_path=entry_report.as_posix(),
        source_report_path=_fixture("sources.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"entry_report_no_eligible_tickers"}


def test_source_eval_fails_when_source_report_cannot_be_loaded(tmp_path: Path) -> None:
    missing_source_report = tmp_path / "missing.sources.json"

    result = evaluate_ai_brief_source_report(
        entry_report_path=_fixture("entry.us.json"),
        source_report_path=missing_source_report.as_posix(),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"source_provider_failed"}


def test_source_eval_requires_market_for_mixed_entry_report(tmp_path: Path) -> None:
    entry_report = tmp_path / "mixed.entry.json"
    entry_report.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "MIXED",
                "entries": [
                    {"ticker": "005930", "action": "ENTER"},
                    {"ticker": "AAPL.NAS", "action": "ENTER"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_ai_brief_source_report(
        entry_report_path=entry_report.as_posix(),
        source_report_path=_fixture("sources.good.json"),
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"entry_report_market_required"}


def test_source_eval_fails_when_market_filter_conflicts_with_entry_report(
    tmp_path: Path,
) -> None:
    entry_report = tmp_path / "us.entry.json"
    entry_report.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "US",
                "entries": [{"ticker": "AAPL.NAS", "action": "ENTER"}],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_ai_brief_source_report(
        entry_report_path=entry_report.as_posix(),
        source_report_path=_fixture("sources.good.json"),
        market="KR",
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert _issue_codes(result) == {"entry_report_market_mismatch"}


def test_source_eval_market_filters_mixed_entry_report(tmp_path: Path) -> None:
    entry_report = tmp_path / "mixed.entry.json"
    entry_report.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "MIXED",
                "entries": [
                    {"ticker": "005930", "action": "ENTER"},
                    {"ticker": "AAPL.NAS", "action": "ENTER"},
                    {"ticker": "MSFT.NAS", "action": "REVIEW"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_ai_brief_source_report(
        entry_report_path=entry_report.as_posix(),
        source_report_path=_fixture("sources.partial.json"),
        market="US",
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.summary["eligible_ticker_count"] == 1
    assert result.summary["covered_ticker_count"] == 1


def test_source_eval_script_outputs_json_and_returns_zero_for_warn(
    capsys,
) -> None:
    exit_code = eval_sources_main(
        [
            "--entry-report",
            _fixture("entry.us.json"),
            "--source-report",
            _fixture("sources.duplicates-cap.json"),
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "WARN"
    assert payload["summary"]["duplicate_url_count"] == 1


def test_source_eval_script_returns_nonzero_for_fail(capsys) -> None:
    exit_code = eval_sources_main(
        [
            "--entry-report",
            _fixture("entry.us.json"),
            "--source-report",
            _fixture("sources.partial.json"),
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["status"] == "FAIL"


def test_parse_eval_now_requires_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        parse_eval_now("2026-05-06T12:00:00")
