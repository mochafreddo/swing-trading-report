from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .ai_brief_candidates import classify_ai_brief_entry_rows
from .ai_brief_eval_common import (
    ENTRY_REPORT_MARKET_INVALID_MESSAGE,
    MIXED_ENTRY_REPORT_MARKET_REQUIRED_MESSAGE,
    AiBriefEvalIssue,
    AiBriefEvalSeverity,
    AiBriefEvalStatus,
    normalize_market,
    optional_text,
    parse_eval_now,
    resolve_entry_report_market,
    string_list,
)
from .ai_brief_providers import PRESELECTION_LIMIT
from .report.ai_brief_report import AiBriefValidationError, validate_ai_brief_artifact
from .tickers import infer_market_from_ticker

AiBriefRecommendationEvalStatus = AiBriefEvalStatus
AiBriefRecommendationEvalSeverity = AiBriefEvalSeverity

_SUPPORTED_ENTRY_ACTIONS = frozenset({"ENTER", "REVIEW", "SKIP"})
_EXPANDED_SUMMARY_COUNT_FIELDS = frozenset({"recommendable_count", "watch_count"})
_NEW_FORMAT_ARTIFACT_FIELDS = frozenset(
    {"watch_tickers", "watch_candidates", "source_provider_summary"}
)


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
    recommendable_count: int
    watch_count: int
    expected_preselected_tickers: list[str]
    expected_watch_tickers: list[str]
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
        message = str(exc)
        issue_code = "ai_brief_report_invalid"
        if "rank must be contiguous" in message:
            issue_code = "recommendation_ranks_not_contiguous"
        return _issue_only_result(
            AiBriefRecommendationEvalIssue(
                code=issue_code,
                severity="FAIL",
                message=message,
            )
        )

    legacy_artifact_contract = _is_legacy_artifact_contract(ai_brief_report)
    normalized_market = normalize_market(market)
    entry_context, entry_issue = _load_entry_context(
        entry_report_path,
        market=normalized_market,
        legacy_artifact_contract=legacy_artifact_contract,
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
    watch_tickers = string_list(ai_brief_report.get("watch_tickers"))
    watch_candidates = _mapping_rows(ai_brief_report.get("watch_candidates"))

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
                    f"first {PRESELECTION_LIMIT} preselected recommendable tickers"
                ),
            )
        )

    if watch_tickers != entry_context.expected_watch_tickers:
        issues.append(
            AiBriefRecommendationEvalIssue(
                code="watch_tickers_mismatch",
                severity="FAIL",
                message=(
                    "AI brief watch_tickers must match the entry report's "
                    "watch-only tickers in order"
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
    issues.extend(
        _watch_candidate_issues(
            watch_candidates,
            expected_watch_tickers=entry_context.expected_watch_tickers,
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
                "recommendable_count": entry_context.recommendable_count,
                "watch_count": entry_context.watch_count,
                "preselected_count": len(eligible_tickers),
                "recommendation_count": len(recommendations),
                "excluded_count": len(excluded_candidates),
                "vetoed_count": len(vetoed_candidates),
                "cap_excluded_count": len(cap_excluded_candidates),
                "source_issue_count": len(source_issues),
                "system_issue_count": len(system_issues),
            },
            allow_legacy_missing_expanded_counts=legacy_artifact_contract,
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
                    "when preselected recommendable candidates exist"
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
            "expected_recommendable_count": entry_context.recommendable_count,
            "expected_watch_count": entry_context.watch_count,
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
    legacy_artifact_contract: bool,
) -> tuple[_EntryContext | None, AiBriefRecommendationEvalIssue | None]:
    entry_report, load_issue = _load_json_mapping(
        entry_report_path,
        failed_code="entry_report_failed",
        invalid_code="entry_report_invalid",
        label="entry report",
    )
    if load_issue is not None:
        return None, load_issue

    try:
        market = resolve_entry_report_market(
            report_market=entry_report.get("market"),
            market_override=market,
        )
    except ValueError as exc:
        message = str(exc)
        if message == MIXED_ENTRY_REPORT_MARKET_REQUIRED_MESSAGE:
            code = "entry_report_market_required"
        elif message == ENTRY_REPORT_MARKET_INVALID_MESSAGE:
            code = "entry_report_invalid"
        else:
            code = "entry_report_market_mismatch"
        return None, AiBriefRecommendationEvalIssue(
            code=code,
            severity="FAIL",
            message=message,
        )

    rows = entry_report.get("entries")
    if not isinstance(rows, list):
        return None, AiBriefRecommendationEvalIssue(
            code="entry_report_invalid",
            severity="FAIL",
            message="entry report entries must be a list",
        )

    target_rows: list[Mapping[str, object]] = []
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        ticker = str(raw_row.get("ticker") or "").strip()
        if not ticker or infer_market_from_ticker(ticker) != market:
            continue
        action = str(raw_row.get("action") or "").strip().upper()
        if action not in _SUPPORTED_ENTRY_ACTIONS:
            return None, AiBriefRecommendationEvalIssue(
                code="entry_report_invalid",
                severity="FAIL",
                message="entry row action must be ENTER, REVIEW, or SKIP",
            )
        target_rows.append(raw_row)

    assert market is not None
    if legacy_artifact_contract:
        return _legacy_entry_context(
            market=market,
            target_rows=target_rows,
        ), None

    classified_rows = classify_ai_brief_entry_rows(target_rows)
    recommendable_candidates = classified_rows.recommendable
    watch_candidates = classified_rows.watch_only
    return _EntryContext(
        market=market,
        target_entry_count=len(target_rows),
        recommendable_count=len(recommendable_candidates),
        watch_count=len(watch_candidates),
        expected_preselected_tickers=[
            candidate.ticker
            for candidate in recommendable_candidates[:PRESELECTION_LIMIT]
        ],
        expected_watch_tickers=[candidate.ticker for candidate in watch_candidates],
        expected_excluded_candidates=[
            (candidate.ticker, candidate.action)
            for candidate in classified_rows.excluded
        ],
        expected_cap_excluded_candidates=[
            (candidate.ticker, candidate.action)
            for candidate in recommendable_candidates[PRESELECTION_LIMIT:]
        ],
    ), None


def _legacy_entry_context(
    *,
    market: str,
    target_rows: list[Mapping[str, object]],
) -> _EntryContext:
    enter_tickers: list[str] = []
    excluded_candidates: list[tuple[str, str]] = []
    for row in target_rows:
        ticker = str(row.get("ticker") or "").strip()
        action = str(row.get("action") or "").strip().upper()
        if action == "ENTER":
            enter_tickers.append(ticker)
        else:
            excluded_candidates.append((ticker, action))

    return _EntryContext(
        market=market,
        target_entry_count=len(target_rows),
        recommendable_count=len(enter_tickers),
        watch_count=0,
        expected_preselected_tickers=enter_tickers[:PRESELECTION_LIMIT],
        expected_watch_tickers=[],
        expected_excluded_candidates=excluded_candidates,
        expected_cap_excluded_candidates=[
            (ticker, "ENTER") for ticker in enter_tickers[PRESELECTION_LIMIT:]
        ],
    )


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


def _watch_candidate_issues(
    rows: list[dict[str, Any]],
    *,
    expected_watch_tickers: list[str],
) -> list[AiBriefRecommendationEvalIssue]:
    issues: list[AiBriefRecommendationEvalIssue] = []
    actual_tickers: list[str] = []
    seen_tickers: set[str] = set()
    duplicate_tickers: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        action = str(row.get("action") or "").strip().upper()
        if ticker:
            actual_tickers.append(ticker)
            if ticker in seen_tickers and ticker not in duplicate_tickers:
                issues.append(
                    AiBriefRecommendationEvalIssue(
                        ticker=ticker,
                        code="watch_candidate_duplicate",
                        severity="FAIL",
                        message="watch candidate ticker must be unique",
                    )
                )
                duplicate_tickers.add(ticker)
            seen_tickers.add(ticker)
        if action != "WATCH":
            issues.append(
                AiBriefRecommendationEvalIssue(
                    ticker=ticker or None,
                    code="watch_candidate_action_invalid",
                    severity="FAIL",
                    message="watch_candidates[].action must be WATCH",
                )
            )
    if actual_tickers != expected_watch_tickers:
        issues.append(
            AiBriefRecommendationEvalIssue(
                code="watch_candidates_mismatch",
                severity="FAIL",
                message=(
                    "watch_candidates[].ticker must match expected watch-only "
                    "tickers in order"
                ),
            )
        )
    return issues


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
                    message=(
                        "recommendation ticker must be an expected preselected "
                        "recommendable ticker"
                    ),
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
    *,
    allow_legacy_missing_expanded_counts: bool = False,
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
        if (
            allow_legacy_missing_expanded_counts
            and field_name in _EXPANDED_SUMMARY_COUNT_FIELDS
        ):
            continue
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


def _is_legacy_artifact_contract(payload: Mapping[str, Any]) -> bool:
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        return False
    return not any(
        field_name in payload for field_name in _NEW_FORMAT_ARTIFACT_FIELDS
    ) and all(
        field_name not in summary for field_name in _EXPANDED_SUMMARY_COUNT_FIELDS
    )


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


__all__ = [
    "AiBriefRecommendationEvalIssue",
    "AiBriefRecommendationEvalResult",
    "evaluate_ai_brief_recommendation_report",
    "parse_eval_now",
]
