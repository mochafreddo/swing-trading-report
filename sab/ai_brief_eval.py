from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .ai_brief_eval_common import (
    AiBriefEvalIssue,
    AiBriefEvalSeverity,
    AiBriefEvalStatus,
    normalize_market,
    optional_text,
    string_list,
)
from .ai_brief_providers import PRESELECTION_LIMIT
from .report.ai_brief_report import AiBriefValidationError, validate_ai_brief_artifact
from .tickers import infer_market_from_ticker

AiBriefRecommendationEvalStatus = AiBriefEvalStatus
AiBriefRecommendationEvalSeverity = AiBriefEvalSeverity


@dataclass(frozen=True)
class AiBriefRecommendationEvalIssue(AiBriefEvalIssue):
    pass


@dataclass(frozen=True)
class AiBriefRecommendationEvalResult:
    status: AiBriefRecommendationEvalStatus
    summary: dict[str, object]
    issues: list[AiBriefRecommendationEvalIssue]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _EntryContext:
    market: str
    target_entry_count: int
    expected_preselected_tickers: list[str]
    expected_excluded_candidates: list[tuple[str, str]]
    expected_cap_excluded_candidates: list[tuple[str, str]]


def evaluate_ai_brief_recommendation_report(
    *,
    entry_report_path: str,
    ai_brief_report_path: str,
    market: str | None = None,
    minimum_source_backed_ratio: float = 1.0,
    now: dt.datetime | None = None,
) -> AiBriefRecommendationEvalResult:
    if (
        not math.isfinite(minimum_source_backed_ratio)
        or minimum_source_backed_ratio < 0
        or minimum_source_backed_ratio > 1
    ):
        raise ValueError("minimum_source_backed_ratio must be between 0 and 1")

    ai_brief_report, ai_brief_issue = _load_json_mapping(
        ai_brief_report_path,
        failed_code="ai_brief_report_failed",
        invalid_code="ai_brief_report_invalid",
        label="AI brief report",
    )
    if ai_brief_issue is not None:
        return _issue_only_result(ai_brief_issue)

    validation_now = now or _validation_now_from_report(ai_brief_report)
    try:
        validate_ai_brief_artifact(ai_brief_report, now=validation_now)
    except AiBriefValidationError as exc:
        return _issue_only_result(
            AiBriefRecommendationEvalIssue(
                code="ai_brief_report_invalid",
                severity="FAIL",
                message=str(exc),
            )
        )

    normalized_market = normalize_market(market)
    entry_context, entry_issue = _load_entry_context(
        entry_report_path,
        market=normalized_market,
    )
    if entry_issue is not None:
        return _issue_only_result(entry_issue)
    assert entry_context is not None

    recommendations = _mapping_rows(ai_brief_report.get("recommendations"))
    excluded_candidates = _mapping_rows(ai_brief_report.get("excluded_candidates"))
    vetoed_candidates = _mapping_rows(ai_brief_report.get("vetoed_candidates"))
    cap_excluded_candidates = _mapping_rows(
        ai_brief_report.get("cap_excluded_candidates")
    )
    source_issues = _mapping_rows(ai_brief_report.get("source_issues"))
    system_issues = _mapping_rows(ai_brief_report.get("system_issues"))
    eligible_tickers = string_list(ai_brief_report.get("eligible_tickers"))

    issues: list[AiBriefRecommendationEvalIssue] = []
    report_market = str(ai_brief_report.get("market") or "").strip().upper()
    if report_market != entry_context.market:
        issues.append(
            AiBriefRecommendationEvalIssue(
                code="ai_brief_market_mismatch",
                severity="FAIL",
                message=(
                    "AI brief market "
                    f"{report_market!r} does not match entry report "
                    f"{entry_context.market!r}"
                ),
            )
        )

    if eligible_tickers != entry_context.expected_preselected_tickers:
        issues.append(
            AiBriefRecommendationEvalIssue(
                code="eligible_tickers_mismatch",
                severity="FAIL",
                message=(
                    "AI brief eligible_tickers must match the entry report's "
                    f"first {PRESELECTION_LIMIT} ENTER tickers"
                ),
            )
        )

    issues.extend(
        _candidate_alignment_issues(
            field_name="excluded_candidates",
            actual_candidates=excluded_candidates,
            expected_candidates=entry_context.expected_excluded_candidates,
        )
    )
    issues.extend(
        _candidate_alignment_issues(
            field_name="cap_excluded_candidates",
            actual_candidates=cap_excluded_candidates,
            expected_candidates=entry_context.expected_cap_excluded_candidates,
        )
    )

    expected_preselected = set(entry_context.expected_preselected_tickers)
    issues.extend(
        _recommendation_ticker_issues(
            recommendations,
            expected_preselected=expected_preselected,
        )
    )
    issues.extend(_rank_issues(recommendations))
    issues.extend(
        _summary_count_issues(
            ai_brief_report.get("summary"),
            {
                "entry_count": entry_context.target_entry_count,
                "preselected_count": len(eligible_tickers),
                "recommendation_count": len(recommendations),
                "excluded_count": len(excluded_candidates),
                "vetoed_count": len(vetoed_candidates),
                "cap_excluded_count": len(cap_excluded_candidates),
                "source_issue_count": len(source_issues),
                "system_issue_count": len(system_issues),
            },
        )
    )
    issues.extend(_reported_issue_issues(source_issues, issue_type="source"))
    issues.extend(_reported_issue_issues(system_issues, issue_type="system"))
    if (
        entry_context.expected_preselected_tickers
        and not recommendations
        and not vetoed_candidates
        and not source_issues
        and not system_issues
    ):
        issues.append(
            AiBriefRecommendationEvalIssue(
                code="recommendation_report_empty",
                severity="FAIL",
                message=(
                    "AI brief must not silently omit recommendations and vetoes "
                    "when preselected ENTER candidates exist"
                ),
            )
        )

    source_issue_tickers = _issue_tickers(source_issues)
    source_backed_count = 0
    for recommendation in recommendations:
        ticker = str(recommendation.get("ticker") or "").strip()
        sources = recommendation.get("sources")
        if isinstance(sources, list) and sources:
            source_backed_count += 1
            continue
        confidence = str(recommendation.get("confidence") or "").strip().upper()
        if confidence in {"MEDIUM", "HIGH"}:
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker or None,
                    code="unbacked_recommendation_confidence_too_high",
                    severity="FAIL",
                    message=(
                        "recommendations without sources must not use MEDIUM or "
                        "HIGH confidence"
                    ),
                )
            )
        elif ticker in source_issue_tickers:
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker or None,
                    code="unbacked_low_confidence_recommendation",
                    severity="WARN",
                    message=(
                        "recommendation has no sources and is disclosed with LOW "
                        "confidence plus a ticker source issue"
                    ),
                )
            )

    source_backed_ratio = _source_backed_ratio(
        recommendation_count=len(recommendations),
        source_backed_count=source_backed_count,
    )
    if source_backed_ratio < minimum_source_backed_ratio:
        issues.append(
            AiBriefRecommendationEvalIssue(
                code="source_backed_ratio_below_threshold",
                severity="FAIL",
                message=(
                    "source-backed recommendation ratio "
                    f"{source_backed_ratio:.3f} is below minimum "
                    f"{minimum_source_backed_ratio:.3f}"
                ),
            )
        )

    status = _status_from_issues(issues)
    return AiBriefRecommendationEvalResult(
        status=status,
        summary={
            "entry_count": entry_context.target_entry_count,
            "expected_preselected_count": len(
                entry_context.expected_preselected_tickers
            ),
            "recommendation_count": len(recommendations),
            "source_backed_recommendation_count": source_backed_count,
            "source_backed_ratio": source_backed_ratio,
            "minimum_source_backed_ratio": minimum_source_backed_ratio,
            "source_issue_count": len(source_issues),
            "system_issue_count": len(system_issues),
            "issue_count": len(issues),
        },
        issues=issues,
    )


def _load_json_mapping(
    path: str,
    *,
    failed_code: str,
    invalid_code: str,
    label: str,
) -> tuple[dict[str, Any], AiBriefRecommendationEvalIssue | None]:
    try:
        with open(path, encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, AiBriefRecommendationEvalIssue(
            code=failed_code,
            severity="FAIL",
            message=f"failed to load {label}: {exc}",
        )
    if not isinstance(payload, Mapping):
        return {}, AiBriefRecommendationEvalIssue(
            code=invalid_code,
            severity="FAIL",
            message=f"{label} must contain a JSON object",
        )
    return dict(payload), None


def _validation_now_from_report(payload: Mapping[str, Any]) -> dt.datetime:
    try:
        return parse_eval_now(str(payload.get("generated_at") or ""))
    except ValueError:
        return dt.datetime.now().astimezone()


def _load_entry_context(
    entry_report_path: str,
    *,
    market: str | None,
) -> tuple[_EntryContext | None, AiBriefRecommendationEvalIssue | None]:
    entry_report, load_issue = _load_json_mapping(
        entry_report_path,
        failed_code="entry_report_failed",
        invalid_code="entry_report_invalid",
        label="entry report",
    )
    if load_issue is not None:
        return None, load_issue

    report_market = str(entry_report.get("market") or "").strip().upper()
    if report_market == "MIXED":
        if market is None:
            return None, AiBriefRecommendationEvalIssue(
                code="entry_report_market_required",
                severity="FAIL",
                message="MIXED entry report requires --market KR or --market US",
            )
    elif report_market in {"KR", "US"}:
        if market is not None and market != report_market:
            return None, AiBriefRecommendationEvalIssue(
                code="entry_report_market_mismatch",
                severity="FAIL",
                message=f"--market {market} does not match entry report {report_market}",
            )
        market = report_market
    else:
        return None, AiBriefRecommendationEvalIssue(
            code="entry_report_invalid",
            severity="FAIL",
            message="entry report market must be KR, US, or MIXED",
        )

    rows = entry_report.get("entries")
    if not isinstance(rows, list):
        return None, AiBriefRecommendationEvalIssue(
            code="entry_report_invalid",
            severity="FAIL",
            message="entry report entries must be a list",
        )

    target_entry_count = 0
    enter_tickers: list[str] = []
    excluded_candidates: list[tuple[str, str]] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        ticker = str(raw_row.get("ticker") or "").strip()
        if not ticker or infer_market_from_ticker(ticker) != market:
            continue
        target_entry_count += 1
        action = str(raw_row.get("action") or "").strip().upper()
        if action == "ENTER":
            enter_tickers.append(ticker)
        elif action in {"REVIEW", "SKIP"}:
            excluded_candidates.append((ticker, action))
        else:
            return None, AiBriefRecommendationEvalIssue(
                code="entry_report_invalid",
                severity="FAIL",
                message="entry row action must be ENTER, REVIEW, or SKIP",
            )

    assert market is not None
    return _EntryContext(
        market=market,
        target_entry_count=target_entry_count,
        expected_preselected_tickers=enter_tickers[:PRESELECTION_LIMIT],
        expected_excluded_candidates=excluded_candidates,
        expected_cap_excluded_candidates=[
            (ticker, "ENTER") for ticker in enter_tickers[PRESELECTION_LIMIT:]
        ],
    ), None


def _candidate_alignment_issues(
    *,
    field_name: Literal["excluded_candidates", "cap_excluded_candidates"],
    actual_candidates: list[dict[str, Any]],
    expected_candidates: list[tuple[str, str]],
) -> list[AiBriefRecommendationEvalIssue]:
    if _candidate_signatures(actual_candidates) == expected_candidates:
        return []
    return [
        AiBriefRecommendationEvalIssue(
            code=f"{field_name}_mismatch",
            severity="FAIL",
            message=f"{field_name} must match the entry report ticker/action order",
        )
    ]


def _candidate_signatures(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    signatures: list[tuple[str, str]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        action = str(row.get("action") or "").strip().upper()
        if ticker:
            signatures.append((ticker, action))
    return signatures


def _recommendation_ticker_issues(
    recommendations: list[dict[str, Any]],
    *,
    expected_preselected: set[str],
) -> list[AiBriefRecommendationEvalIssue]:
    issues: list[AiBriefRecommendationEvalIssue] = []
    seen_tickers: set[str] = set()
    for recommendation in recommendations:
        ticker = str(recommendation.get("ticker") or "").strip()
        if ticker and ticker not in expected_preselected:
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker,
                    code="recommendation_ticker_not_preselected",
                    severity="FAIL",
                    message="recommendation ticker must be an expected preselected ENTER ticker",
                )
            )
        if ticker in seen_tickers:
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker,
                    code="recommendation_ticker_duplicate",
                    severity="FAIL",
                    message="recommendation ticker must be unique",
                )
            )
        if ticker:
            seen_tickers.add(ticker)
    return issues


def _rank_issues(
    recommendations: list[dict[str, Any]],
) -> list[AiBriefRecommendationEvalIssue]:
    ranks = [recommendation.get("rank") for recommendation in recommendations]
    if ranks == list(range(1, len(recommendations) + 1)):
        return []
    return [
        AiBriefRecommendationEvalIssue(
            code="recommendation_ranks_not_contiguous",
            severity="FAIL",
            message="recommendation ranks must be contiguous from 1 to N",
        )
    ]


def _summary_count_issues(
    summary: object,
    expected_counts: Mapping[str, int],
) -> list[AiBriefRecommendationEvalIssue]:
    if not isinstance(summary, Mapping):
        return [
            AiBriefRecommendationEvalIssue(
                code="summary_invalid",
                severity="FAIL",
                message="summary must be an object",
            )
        ]

    issues: list[AiBriefRecommendationEvalIssue] = []
    for field_name, expected_count in expected_counts.items():
        actual = _int_value(summary.get(field_name))
        if actual != expected_count:
            issues.append(
                AiBriefRecommendationEvalIssue(
                    code="summary_count_mismatch",
                    severity="FAIL",
                    message=(
                        f"summary.{field_name} must be {expected_count}, "
                        f"got {summary.get(field_name)!r}"
                    ),
                )
            )
    return issues


def _reported_issue_issues(
    rows: list[dict[str, Any]],
    *,
    issue_type: Literal["source", "system"],
) -> list[AiBriefRecommendationEvalIssue]:
    issues: list[AiBriefRecommendationEvalIssue] = []
    for row in rows:
        severity = str(row.get("severity") or "").strip().upper()
        ticker = optional_text(row.get("ticker"))
        if severity == "ERROR":
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker,
                    code=f"ai_brief_{issue_type}_issue_error",
                    severity="FAIL",
                    message=str(row.get("message") or "").strip(),
                )
            )
        elif severity in {"WARN", "INFO"}:
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker,
                    code=f"ai_brief_{issue_type}_issue_reported",
                    severity="WARN",
                    message=str(row.get("message") or "").strip(),
                )
            )
    return issues


def _issue_tickers(rows: list[dict[str, Any]]) -> set[str]:
    tickers: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            tickers.add(ticker)
    return tickers


def _source_backed_ratio(
    *,
    recommendation_count: int,
    source_backed_count: int,
) -> float:
    if recommendation_count == 0:
        return 1.0
    return source_backed_count / recommendation_count


def _issue_only_result(
    issue: AiBriefRecommendationEvalIssue,
) -> AiBriefRecommendationEvalResult:
    return AiBriefRecommendationEvalResult(
        status="FAIL",
        summary={"issue_count": 1},
        issues=[issue],
    )


def _status_from_issues(
    issues: list[AiBriefRecommendationEvalIssue],
) -> AiBriefRecommendationEvalStatus:
    if any(issue.severity == "FAIL" for issue in issues):
        return "FAIL"
    if issues:
        return "WARN"
    return "PASS"


def _mapping_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _int_value(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def parse_eval_now(value: str) -> dt.datetime:
    text = value.strip()
    if not text:
        raise ValueError("now must not be empty")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("now must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    return parsed


__all__ = [
    "AiBriefRecommendationEvalIssue",
    "AiBriefRecommendationEvalResult",
    "evaluate_ai_brief_recommendation_report",
    "parse_eval_now",
]
