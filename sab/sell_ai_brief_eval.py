from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .ai_brief_eval_common import (
    AiBriefEvalIssue,
    AiBriefEvalSeverity,
    AiBriefEvalStatus,
    contains_automated_order_language,
    parse_eval_now,
)
from .report.sell_ai_brief_report import (
    SellAiBriefValidationError,
    validate_sell_ai_brief_artifact,
)
from .sell_ai_brief_candidates import classify_sell_ai_brief_rows
from .sell_ai_brief_providers import PRESELECTION_LIMIT

SellAiBriefEvalStatus = AiBriefEvalStatus
SellAiBriefEvalSeverity = AiBriefEvalSeverity


@dataclass(frozen=True)
class SellAiBriefEvalIssue(AiBriefEvalIssue):
    pass


@dataclass(frozen=True)
class SellAiBriefEvalResult:
    status: SellAiBriefEvalStatus
    summary: dict[str, object]
    issues: list[SellAiBriefEvalIssue]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _SellContext:
    evaluated_count: int
    expected_actionable_tickers: list[str]
    expected_preselected_tickers: list[str]
    expected_action_by_ticker: dict[str, str]
    expected_broker_state_review_candidates: list[tuple[str, str]]
    expected_excluded_hold_candidates: list[tuple[str, str]]
    expected_unsupported_candidates: list[tuple[str, str]]
    expected_cap_excluded_candidates: list[tuple[str, str]]


def evaluate_sell_ai_brief_report(
    *,
    sell_report_path: str,
    sell_ai_brief_report_path: str,
    minimum_source_backed_ratio: float = 1.0,
    now: dt.datetime | None = None,
) -> SellAiBriefEvalResult:
    if (
        not math.isfinite(minimum_source_backed_ratio)
        or minimum_source_backed_ratio < 0
        or minimum_source_backed_ratio > 1
    ):
        raise ValueError("minimum_source_backed_ratio must be between 0 and 1")

    sell_report, sell_issue = _load_json_mapping(
        sell_report_path,
        failed_code="sell_report_failed",
        invalid_code="sell_report_invalid",
        label="sell report",
    )
    if sell_issue is not None:
        return _issue_only_result(sell_issue)
    assert sell_report is not None
    sell_context, context_issue = _load_sell_context(sell_report)
    if context_issue is not None:
        return _issue_only_result(context_issue)
    assert sell_context is not None

    sell_ai_brief_report, brief_issue = _load_json_mapping(
        sell_ai_brief_report_path,
        failed_code="sell_ai_brief_report_failed",
        invalid_code="sell_ai_brief_report_invalid",
        label="Sell AI brief report",
    )
    if brief_issue is not None:
        return _issue_only_result(brief_issue)
    assert sell_ai_brief_report is not None

    issues: list[SellAiBriefEvalIssue] = []
    issues.extend(_alignment_issues(sell_ai_brief_report, sell_context))
    issues.extend(_preselected_coverage_issues(sell_ai_brief_report, sell_context))
    issues.extend(_model_attempt_issues(sell_ai_brief_report))
    validation_now = now or _validation_now_from_report(sell_ai_brief_report)
    try:
        validate_sell_ai_brief_artifact(sell_ai_brief_report, now=validation_now)
    except SellAiBriefValidationError as exc:
        issues.append(
            SellAiBriefEvalIssue(
                code="sell_ai_brief_report_invalid",
                severity="FAIL",
                message=str(exc),
            )
        )

    judgments = _mapping_rows(sell_ai_brief_report.get("judgments"))
    source_issues = _mapping_rows(sell_ai_brief_report.get("source_issues"))
    system_issues = _mapping_rows(sell_ai_brief_report.get("system_issues"))
    source_backed_count = sum(1 for row in judgments if _source_backed(row))
    source_backed_ratio = 1.0 if not judgments else source_backed_count / len(judgments)
    if source_backed_ratio < minimum_source_backed_ratio:
        issues.append(
            SellAiBriefEvalIssue(
                code="source_backed_ratio_below_threshold",
                severity="WARN",
                message=(
                    "Sell AI Brief source-backed judgment ratio "
                    f"{source_backed_ratio:.3f} is below "
                    f"{minimum_source_backed_ratio:.3f}"
                ),
            )
        )
    issues.extend(_language_issues(judgments, field_name="judgments"))
    issues.extend(
        _language_issues(
            _mapping_rows(sell_ai_brief_report.get("vetoed_candidates")),
            field_name="vetoed_candidates",
        )
    )

    summary: dict[str, object] = {
        "evaluated_count": sell_context.evaluated_count,
        "expected_actionable_count": len(sell_context.expected_actionable_tickers),
        "expected_preselected_count": len(sell_context.expected_preselected_tickers),
        "judgment_count": len(judgments),
        "source_backed_judgment_count": source_backed_count,
        "source_backed_ratio": source_backed_ratio,
        "source_issue_count": len(source_issues),
        "system_issue_count": len(system_issues),
    }
    return SellAiBriefEvalResult(
        status=_status_from_issues(issues),
        summary=summary,
        issues=issues,
    )


def _load_json_mapping(
    path: str,
    *,
    failed_code: str,
    invalid_code: str,
    label: str,
) -> tuple[dict[str, Any] | None, SellAiBriefEvalIssue | None]:
    try:
        with open(path, encoding="utf-8") as fp:
            raw = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        return None, SellAiBriefEvalIssue(
            code=failed_code,
            severity="FAIL",
            message=f"Failed to load {label}: {exc}",
        )
    if not isinstance(raw, dict):
        return None, SellAiBriefEvalIssue(
            code=invalid_code,
            severity="FAIL",
            message=f"{label} must contain a JSON object",
        )
    return raw, None


def _load_sell_context(
    sell_report: Mapping[str, Any],
) -> tuple[_SellContext | None, SellAiBriefEvalIssue | None]:
    if sell_report.get("type") != "sell":
        return None, SellAiBriefEvalIssue(
            code="sell_report_invalid",
            severity="FAIL",
            message="sell report type must be 'sell'",
        )
    rows = _mapping_rows(sell_report.get("evaluated"))
    classification = classify_sell_ai_brief_rows(rows)
    actionable_candidates = classification.actionable
    expected_preselected = actionable_candidates[:PRESELECTION_LIMIT]
    expected_cap_excluded = actionable_candidates[PRESELECTION_LIMIT:]
    return _SellContext(
        evaluated_count=len(rows),
        expected_actionable_tickers=[row.ticker for row in actionable_candidates],
        expected_preselected_tickers=[row.ticker for row in expected_preselected],
        expected_action_by_ticker={
            row.ticker: row.sell_action for row in expected_preselected
        },
        expected_broker_state_review_candidates=[
            (row.ticker, row.sell_action) for row in classification.broker_state_review
        ],
        expected_excluded_hold_candidates=[
            (row.ticker, row.sell_action) for row in classification.excluded_hold
        ],
        expected_unsupported_candidates=[
            (row.ticker, row.sell_action) for row in classification.unsupported
        ],
        expected_cap_excluded_candidates=[
            (row.ticker, row.sell_action) for row in expected_cap_excluded
        ],
    ), None


def _alignment_issues(
    report: Mapping[str, Any],
    context: _SellContext,
) -> list[SellAiBriefEvalIssue]:
    issues: list[SellAiBriefEvalIssue] = []
    actionable_tickers = _string_list(report.get("actionable_tickers"))
    if actionable_tickers != context.expected_preselected_tickers:
        issues.append(
            SellAiBriefEvalIssue(
                code="actionable_tickers_mismatch",
                severity="FAIL",
                message=(
                    "Sell AI Brief actionable_tickers must match the source sell "
                    f"report's first {PRESELECTION_LIMIT} actionable rows"
                ),
            )
        )
    issues.extend(
        _candidate_alignment_issues(
            field_name="excluded_hold_candidates",
            actual_candidates=_mapping_rows(report.get("excluded_hold_candidates")),
            expected_candidates=context.expected_excluded_hold_candidates,
        )
    )
    issues.extend(
        _candidate_alignment_issues(
            field_name="broker_state_review_candidates",
            actual_candidates=_mapping_rows(
                report.get("broker_state_review_candidates")
            ),
            expected_candidates=context.expected_broker_state_review_candidates,
        )
    )
    issues.extend(
        _candidate_alignment_issues(
            field_name="unsupported_action_candidates",
            actual_candidates=_mapping_rows(
                report.get("unsupported_action_candidates")
            ),
            expected_candidates=context.expected_unsupported_candidates,
        )
    )
    issues.extend(
        _candidate_alignment_issues(
            field_name="cap_excluded_candidates",
            actual_candidates=_mapping_rows(report.get("cap_excluded_candidates")),
            expected_candidates=context.expected_cap_excluded_candidates,
        )
    )
    issues.extend(_judgment_action_issues(report, context))
    return issues


def _candidate_alignment_issues(
    *,
    field_name: str,
    actual_candidates: list[dict[str, Any]],
    expected_candidates: list[tuple[str, str]],
) -> list[SellAiBriefEvalIssue]:
    actual = [
        (
            str(row.get("ticker") or "").strip(),
            str(row.get("sell_action") or row.get("action") or "").strip().upper(),
        )
        for row in actual_candidates
    ]
    if actual == expected_candidates:
        return []
    return [
        SellAiBriefEvalIssue(
            code=f"{field_name}_mismatch",
            severity="FAIL",
            message=f"{field_name} must match source sell report classification",
        )
    ]


def _judgment_action_issues(
    report: Mapping[str, Any],
    context: _SellContext,
) -> list[SellAiBriefEvalIssue]:
    issues: list[SellAiBriefEvalIssue] = []
    seen_tickers: set[str] = set()
    for row in _mapping_rows(report.get("judgments")):
        ticker = str(row.get("ticker") or "").strip()
        sell_action = (
            str(row.get("sell_action") or row.get("action") or "").strip().upper()
        )
        if ticker in seen_tickers:
            issues.append(
                SellAiBriefEvalIssue(
                    code="duplicate_judgment_ticker",
                    severity="FAIL",
                    message=f"Duplicate judgment ticker {ticker}",
                    ticker=ticker,
                )
            )
        seen_tickers.add(ticker)
        expected_action = context.expected_action_by_ticker.get(ticker)
        if expected_action is None:
            issues.append(
                SellAiBriefEvalIssue(
                    code="judgment_ticker_not_preselected",
                    severity="FAIL",
                    message="Judgment ticker is not a preselected source sell row",
                    ticker=ticker or None,
                )
            )
            continue
        if sell_action != expected_action:
            issues.append(
                SellAiBriefEvalIssue(
                    code="judgment_sell_action_mismatch",
                    severity="FAIL",
                    message=(
                        f"Judgment sell_action {sell_action!r} does not match "
                        f"source sell action {expected_action!r}"
                    ),
                    ticker=ticker,
                )
            )
    return issues


def _preselected_coverage_issues(
    report: Mapping[str, Any],
    context: _SellContext,
) -> list[SellAiBriefEvalIssue]:
    judgment_tickers = {
        str(row.get("ticker") or "").strip()
        for row in _mapping_rows(report.get("judgments"))
    }
    vetoed_tickers = {
        str(row.get("ticker") or "").strip()
        for row in _mapping_rows(report.get("vetoed_candidates"))
    }
    covered_tickers = judgment_tickers | vetoed_tickers
    return [
        SellAiBriefEvalIssue(
            code="preselected_ticker_uncovered",
            severity="FAIL",
            message="Preselected ticker is missing from judgments and vetoed_candidates",
            ticker=ticker,
        )
        for ticker in context.expected_preselected_tickers
        if ticker not in covered_tickers
    ]


def _model_attempt_issues(report: Mapping[str, Any]) -> list[SellAiBriefEvalIssue]:
    issues: list[SellAiBriefEvalIssue] = []
    for idx, attempt in enumerate(_mapping_rows(report.get("model_attempts"))):
        status = str(attempt.get("status") or "").strip().lower()
        if status == "failed":
            model_name = str(attempt.get("model_name") or "").strip() or "unknown"
            issues.append(
                SellAiBriefEvalIssue(
                    code="model_attempt_failed",
                    severity="FAIL",
                    message=f"Model attempt {idx + 1} failed for {model_name}",
                )
            )
    return issues


def _language_issues(
    rows: list[dict[str, Any]],
    *,
    field_name: str,
) -> list[SellAiBriefEvalIssue]:
    issues: list[SellAiBriefEvalIssue] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip() or None
        text = " ".join(
            [
                *_string_list(row.get("deterministic_reasons")),
                *_string_list(row.get("rationale")),
                *_string_list(row.get("checklist")),
                str(row.get("reason") or ""),
            ]
        )
        if contains_automated_order_language(text):
            issues.append(
                SellAiBriefEvalIssue(
                    code=f"{field_name}_automated_order_language",
                    severity="FAIL",
                    message=f"{field_name} must avoid automated order language",
                    ticker=ticker,
                )
            )
    return issues


def _mapping_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _source_backed(row: Mapping[str, Any]) -> bool:
    return bool(_mapping_rows(row.get("sources")))


def _validation_now_from_report(report: Mapping[str, Any]) -> dt.datetime:
    generated_at = str(report.get("generated_at") or "").strip()
    if generated_at:
        try:
            parsed = dt.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
    return dt.datetime.now(dt.UTC)


def _status_from_issues(
    issues: list[SellAiBriefEvalIssue],
) -> SellAiBriefEvalStatus:
    if any(issue.severity == "FAIL" for issue in issues):
        return "FAIL"
    if any(issue.severity == "WARN" for issue in issues):
        return "WARN"
    return "PASS"


def _issue_only_result(issue: SellAiBriefEvalIssue) -> SellAiBriefEvalResult:
    return SellAiBriefEvalResult(
        status="FAIL",
        summary={},
        issues=[issue],
    )


__all__ = [
    "SellAiBriefEvalIssue",
    "SellAiBriefEvalResult",
    "evaluate_sell_ai_brief_report",
    "parse_eval_now",
]
