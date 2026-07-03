from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sab.sell_ai_brief_eval import evaluate_sell_ai_brief_report
from scripts.eval_sell_ai_brief import main as eval_sell_main

EVAL_NOW = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC)


def _write_payload(tmp_path: Path, name: str, payload: Mapping[str, Any]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.as_posix()


def _sell_row(ticker: str, *, action: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": ticker,
        "action": action,
        "reasons": ["sell condition matched"],
    }


def _source(ticker: str) -> dict[str, object]:
    return {
        "title": f"{ticker} source",
        "url": f"https://news.example.test/{ticker.lower()}",
        "published_at": "2026-05-06T10:00:00+00:00",
    }


def _sell_report() -> dict[str, Any]:
    return {
        "schema": "sab.report.v1",
        "type": "sell",
        "market": "US",
        "evaluated": [
            _sell_row("AAPL.NAS", action="SELL"),
            _sell_row("MSFT.NAS", action="SELL_PARTIAL"),
            _sell_row("TSLA.NAS", action="REVIEW"),
            _sell_row("NVDA.NAS", action="HOLD"),
            _sell_row("BAD.NAS", action="TRIM"),
        ],
    }


def _judgment(
    ticker: str, *, sell_action: str, sources: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": ticker,
        "sell_action": sell_action,
        "ai_stance": "AGREE" if sell_action != "REVIEW" else "CAUTION",
        "confidence": "LOW",
        "deterministic_reasons": ["sell condition matched"],
        "rationale": ["원본 매도 조건과 소스 맥락을 수동 확인"],
        "checklist": ["수량과 유동성을 확인"],
        "sources": sources,
        "as_of": "2026-05-06T12:00:00+00:00",
    }


def _sell_ai_brief_report() -> dict[str, Any]:
    judgments = [
        _judgment("AAPL.NAS", sell_action="SELL", sources=[_source("AAPL.NAS")]),
        _judgment(
            "MSFT.NAS",
            sell_action="SELL_PARTIAL",
            sources=[_source("MSFT.NAS")],
        ),
        _judgment("TSLA.NAS", sell_action="REVIEW", sources=[_source("TSLA.NAS")]),
    ]
    return {
        "schema": "sab.sell_ai_brief.v1",
        "type": "sell-ai-brief",
        "generated_at": "2026-05-06T12:00:00+00:00",
        "report_date": "2026-05-06",
        "source_sell_report": "sell.us.json",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-sell-ai-brief-v1",
        "brief_state": "FINAL_JUDGMENT",
        "brief_reason": "model_judgment_ready",
        "summary": {
            "evaluated_count": 5,
            "actionable_count": 3,
            "preselected_count": 3,
            "judgment_count": 3,
            "excluded_hold_count": 1,
            "unsupported_action_count": 1,
            "vetoed_count": 0,
            "cap_excluded_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 1,
        },
        "actionable_tickers": ["AAPL.NAS", "MSFT.NAS", "TSLA.NAS"],
        "actionable_candidates": [
            {
                "ticker": "AAPL.NAS",
                "sell_action": "SELL",
                "deterministic_reasons": ["sell condition matched"],
            },
            {
                "ticker": "MSFT.NAS",
                "sell_action": "SELL_PARTIAL",
                "deterministic_reasons": ["sell condition matched"],
            },
            {
                "ticker": "TSLA.NAS",
                "sell_action": "REVIEW",
                "deterministic_reasons": ["sell condition matched"],
            },
        ],
        "excluded_hold_candidates": [
            {
                "ticker": "NVDA.NAS",
                "sell_action": "HOLD",
                "reason": "sell report action was HOLD",
            }
        ],
        "unsupported_action_candidates": [
            {
                "ticker": "BAD.NAS",
                "sell_action": "TRIM",
                "reason": "unsupported sell action TRIM",
            }
        ],
        "cap_excluded_candidates": [],
        "judgments": judgments,
        "vetoed_candidates": [],
        "source_issues": [],
        "system_issues": [
            {
                "ticker": "BAD.NAS",
                "code": "unsupported_sell_action",
                "severity": "WARN",
                "message": "unsupported sell action TRIM",
            }
        ],
    }


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_sell_ai_brief_eval_passes_source_backed_artifact(tmp_path: Path) -> None:
    sell_report_path = _write_payload(tmp_path, "sell.us.json", _sell_report())
    sell_ai_brief_path = _write_payload(
        tmp_path,
        "sell-ai-brief.good.json",
        _sell_ai_brief_report(),
    )

    result = evaluate_sell_ai_brief_report(
        sell_report_path=sell_report_path,
        sell_ai_brief_report_path=sell_ai_brief_path,
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.summary["expected_preselected_count"] == 3
    assert result.summary["judgment_count"] == 3
    assert result.summary["source_backed_judgment_count"] == 3
    assert result.summary["source_backed_ratio"] == 1.0
    assert result.issues == []


def test_sell_ai_brief_eval_warns_when_source_backing_ratio_is_low(
    tmp_path: Path,
) -> None:
    payload = _sell_ai_brief_report()
    payload["judgments"][0]["sources"] = []
    payload["source_issues"] = [
        {
            "ticker": "AAPL.NAS",
            "code": "fake_provider_no_external_sources",
            "severity": "WARN",
            "message": "fake provider는 외부 소스를 수집하지 않음",
        }
    ]
    payload["summary"]["source_issue_count"] = 1
    payload["brief_state"] = "NEEDS_REVIEW_WEAK_NEWS"
    payload["brief_reason"] = "weak_news_coverage"
    sell_report_path = _write_payload(tmp_path, "sell.us.json", _sell_report())
    sell_ai_brief_path = _write_payload(tmp_path, "weak.json", payload)

    result = evaluate_sell_ai_brief_report(
        sell_report_path=sell_report_path,
        sell_ai_brief_report_path=sell_ai_brief_path,
        minimum_source_backed_ratio=1.0,
        now=EVAL_NOW,
    )

    assert result.status == "WARN"
    assert result.summary["source_backed_ratio"] == 2 / 3
    assert "source_backed_ratio_below_threshold" in _issue_codes(result)


def test_sell_ai_brief_eval_fails_when_preselected_candidate_is_uncovered(
    tmp_path: Path,
) -> None:
    payload = _sell_ai_brief_report()
    payload["judgments"] = []
    payload["summary"]["judgment_count"] = 0
    payload["system_issues"] = []
    payload["summary"]["system_issue_count"] = 0
    payload["brief_state"] = "FINAL_JUDGMENT"
    payload["brief_reason"] = "model_judgment_ready"
    sell_report_path = _write_payload(tmp_path, "sell.us.json", _sell_report())
    sell_ai_brief_path = _write_payload(tmp_path, "uncovered.json", payload)

    result = evaluate_sell_ai_brief_report(
        sell_report_path=sell_report_path,
        sell_ai_brief_report_path=sell_ai_brief_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "preselected_ticker_uncovered" in _issue_codes(result)


def test_sell_ai_brief_eval_fails_when_model_attempt_failed(
    tmp_path: Path,
) -> None:
    payload = _sell_ai_brief_report()
    payload["judgments"] = []
    payload["summary"]["judgment_count"] = 0
    payload["model_attempts"] = [
        {
            "role": "primary",
            "model_name": "gpt-test",
            "timeout_seconds": 1.0,
            "status": "failed",
            "duration_ms": 0,
            "error_type": "SellAiBriefProviderTimeoutError",
        }
    ]
    payload["system_issues"] = [
        {
            "ticker": None,
            "code": "model_provider_timeout",
            "severity": "ERROR",
            "message": "model provider timed out",
        }
    ]
    payload["summary"]["system_issue_count"] = 1
    payload["brief_state"] = "MODEL_OR_SYSTEM_ISSUE"
    payload["brief_reason"] = "system_issue_without_model_judgment"
    sell_report_path = _write_payload(tmp_path, "sell.us.json", _sell_report())
    sell_ai_brief_path = _write_payload(tmp_path, "model-failed.json", payload)

    result = evaluate_sell_ai_brief_report(
        sell_report_path=sell_report_path,
        sell_ai_brief_report_path=sell_ai_brief_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "model_attempt_failed" in _issue_codes(result)


def test_sell_ai_brief_eval_fails_when_actionable_tickers_do_not_match_source(
    tmp_path: Path,
) -> None:
    payload = _sell_ai_brief_report()
    payload["actionable_tickers"] = ["MSFT.NAS", "AAPL.NAS", "TSLA.NAS"]
    sell_report_path = _write_payload(tmp_path, "sell.us.json", _sell_report())
    sell_ai_brief_path = _write_payload(tmp_path, "misordered.json", payload)

    result = evaluate_sell_ai_brief_report(
        sell_report_path=sell_report_path,
        sell_ai_brief_report_path=sell_ai_brief_path,
        now=EVAL_NOW,
    )

    assert result.status == "FAIL"
    assert "actionable_tickers_mismatch" in _issue_codes(result)


def test_sell_ai_brief_eval_cli_returns_nonzero_on_failure(
    tmp_path: Path,
    capsys,
) -> None:
    payload = _sell_ai_brief_report()
    payload["actionable_tickers"] = ["MSFT.NAS", "AAPL.NAS", "TSLA.NAS"]
    sell_report_path = _write_payload(tmp_path, "sell.us.json", _sell_report())
    sell_ai_brief_path = _write_payload(tmp_path, "misordered.json", payload)

    exit_code = eval_sell_main(
        [
            "--sell-report",
            sell_report_path,
            "--sell-ai-brief-report",
            sell_ai_brief_path,
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    assert exit_code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FAIL"
