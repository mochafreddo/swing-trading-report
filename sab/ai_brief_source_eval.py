from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass

from .ai_brief_eval_common import (
    AiBriefEvalIssue,
    AiBriefEvalSeverity,
    AiBriefEvalStatus,
    normalize_market,
    optional_text,
)
from .ai_brief_sources import (
    SOURCE_PROVIDER_LOCAL_JSON,
    AiBriefSourceProviderError,
    load_ai_brief_sources,
)
from .tickers import infer_market_from_ticker

AiBriefSourceEvalStatus = AiBriefEvalStatus
AiBriefSourceEvalSeverity = AiBriefEvalSeverity


@dataclass(frozen=True)
class AiBriefSourceEvalIssue(AiBriefEvalIssue):
    pass


@dataclass(frozen=True)
class AiBriefSourceEvalResult:
    status: AiBriefSourceEvalStatus
    summary: dict[str, object]
    issues: list[AiBriefSourceEvalIssue]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class AiBriefSourceCompareResult:
    status: AiBriefSourceEvalStatus
    summary: dict[str, object]
    reports: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "summary": self.summary,
            "reports": self.reports,
        }


def evaluate_ai_brief_source_report(
    *,
    entry_report_path: str,
    source_report_path: str,
    market: str | None = None,
    minimum_coverage_ratio: float = 1.0,
    now: dt.datetime | None = None,
) -> AiBriefSourceEvalResult:
    if minimum_coverage_ratio < 0 or minimum_coverage_ratio > 1:
        raise ValueError("minimum_coverage_ratio must be between 0 and 1")
    normalized_market = normalize_market(market)
    resolved_now = now or dt.datetime.now().astimezone()
    eligible_tickers, entry_issue = _load_eligible_tickers(
        entry_report_path,
        market=normalized_market,
    )
    if entry_issue is not None:
        return _result(
            status="FAIL",
            eligible_tickers=eligible_tickers,
            covered_tickers=set(),
            source_count=0,
            minimum_coverage_ratio=minimum_coverage_ratio,
            issues=[entry_issue],
        )
    if not eligible_tickers:
        return _result(
            status="FAIL",
            eligible_tickers=eligible_tickers,
            covered_tickers=set(),
            source_count=0,
            minimum_coverage_ratio=minimum_coverage_ratio,
            issues=[
                AiBriefSourceEvalIssue(
                    code="entry_report_no_eligible_tickers",
                    severity="FAIL",
                    message="entry report contains no ENTER candidates to evaluate",
                )
            ],
        )

    issues: list[AiBriefSourceEvalIssue] = []
    try:
        provider_result = load_ai_brief_sources(
            source_provider=SOURCE_PROVIDER_LOCAL_JSON,
            source_report_path=source_report_path,
            eligible_tickers=eligible_tickers,
            now=resolved_now,
        )
    except AiBriefSourceProviderError as exc:
        return _result(
            status="FAIL",
            eligible_tickers=eligible_tickers,
            covered_tickers=set(),
            source_count=0,
            minimum_coverage_ratio=minimum_coverage_ratio,
            issues=[
                AiBriefSourceEvalIssue(
                    code=exc.code,
                    severity="FAIL",
                    message=str(exc),
                )
            ],
        )

    provider_duplicate_count = _provider_duplicate_url_issue_count(
        provider_result.source_issues
    )
    issues.extend(_source_issues(provider_result.source_issues))
    duplicate_issues = _duplicate_url_issues(provider_result.sources_by_ticker)
    issues.extend(duplicate_issues)

    covered_tickers = {
        ticker
        for ticker, sources in provider_result.sources_by_ticker.items()
        if sources
    }
    source_count = sum(
        len(sources) for sources in provider_result.sources_by_ticker.values()
    )
    coverage_ratio = _coverage_ratio(
        eligible_tickers=eligible_tickers,
        covered_tickers=covered_tickers,
    )
    if coverage_ratio < minimum_coverage_ratio:
        issues.append(
            AiBriefSourceEvalIssue(
                code="source_coverage_below_threshold",
                severity="FAIL",
                message=(
                    "source coverage "
                    f"{coverage_ratio:.3f} is below minimum "
                    f"{minimum_coverage_ratio:.3f}"
                ),
            )
        )

    status: AiBriefSourceEvalStatus = "PASS"
    if any(issue.severity == "FAIL" for issue in issues):
        status = "FAIL"
    elif issues:
        status = "WARN"

    return _result(
        status=status,
        eligible_tickers=eligible_tickers,
        covered_tickers=covered_tickers,
        source_count=source_count,
        minimum_coverage_ratio=minimum_coverage_ratio,
        issues=issues,
        duplicate_url_count=provider_duplicate_count + len(duplicate_issues),
    )


def compare_ai_brief_source_reports(
    *,
    entry_report_path: str,
    source_reports: Mapping[str, str],
    market: str | None = None,
    minimum_coverage_ratio: float = 1.0,
    now: dt.datetime | None = None,
) -> AiBriefSourceCompareResult:
    if len(source_reports) < 2:
        raise ValueError("source_reports must contain at least two reports")
    resolved_now = now or dt.datetime.now().astimezone()
    reports: list[dict[str, object]] = []
    pass_count = 0
    warn_count = 0
    fail_count = 0
    for label, source_report_path in source_reports.items():
        result = evaluate_ai_brief_source_report(
            entry_report_path=entry_report_path,
            source_report_path=source_report_path,
            market=market,
            minimum_coverage_ratio=minimum_coverage_ratio,
            now=resolved_now,
        )
        if result.status == "PASS":
            pass_count += 1
        elif result.status == "WARN":
            warn_count += 1
        else:
            fail_count += 1
        reports.append(
            {
                "label": label,
                "status": result.status,
                "summary": result.summary,
                "issues": [issue.to_dict() for issue in result.issues],
            }
        )

    status: AiBriefSourceEvalStatus = "PASS"
    if fail_count:
        status = "FAIL"
    elif warn_count:
        status = "WARN"

    summary = {
        "report_count": len(reports),
        "pass_count": pass_count,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "leaders": {
            "coverage": _leader_labels(
                reports,
                key="coverage_ratio",
                prefer_high=True,
            ),
            "source_count": _leader_labels(
                reports,
                key="source_count",
                prefer_high=True,
            ),
            "fewest_issues": _leader_labels(
                reports,
                key="issue_count",
                prefer_high=False,
            ),
        },
    }
    return AiBriefSourceCompareResult(
        status=status,
        summary=summary,
        reports=reports,
    )


def _load_eligible_tickers(
    entry_report_path: str,
    *,
    market: str | None,
) -> tuple[set[str], AiBriefSourceEvalIssue | None]:
    try:
        with open(entry_report_path, encoding="utf-8") as fp:
            payload = json.load(fp)
    except (OSError, json.JSONDecodeError) as exc:
        return set(), AiBriefSourceEvalIssue(
            code="entry_report_failed",
            severity="FAIL",
            message=f"failed to load entry report: {exc}",
        )
    if not isinstance(payload, Mapping):
        return set(), AiBriefSourceEvalIssue(
            code="entry_report_invalid",
            severity="FAIL",
            message="entry report must contain a JSON object",
        )
    report_market = str(payload.get("market") or "").strip().upper()
    if report_market == "MIXED":
        if market is None:
            return set(), AiBriefSourceEvalIssue(
                code="entry_report_market_required",
                severity="FAIL",
                message="MIXED entry report requires --market KR or --market US",
            )
    elif report_market in {"KR", "US"}:
        if market is not None and market != report_market:
            return set(), AiBriefSourceEvalIssue(
                code="entry_report_market_mismatch",
                severity="FAIL",
                message=f"--market {market} does not match entry report {report_market}",
            )
        market = report_market
    else:
        return set(), AiBriefSourceEvalIssue(
            code="entry_report_invalid",
            severity="FAIL",
            message="entry report market must be KR, US, or MIXED",
        )

    rows = payload.get("entries")
    if not isinstance(rows, list):
        return set(), AiBriefSourceEvalIssue(
            code="entry_report_invalid",
            severity="FAIL",
            message="entry report entries must be a list",
        )

    tickers: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        action = str(raw_row.get("action") or "").strip().upper()
        ticker = str(raw_row.get("ticker") or "").strip()
        if action == "ENTER" and ticker and infer_market_from_ticker(ticker) == market:
            tickers.add(ticker)
    return tickers, None


def _source_issues(rows: list[dict[str, object]]) -> list[AiBriefSourceEvalIssue]:
    issues: list[AiBriefSourceEvalIssue] = []
    for row in rows:
        severity = str(row.get("severity") or "WARN").strip().upper()
        eval_severity: AiBriefSourceEvalSeverity = (
            "FAIL" if severity == "ERROR" else "WARN"
        )
        issues.append(
            AiBriefSourceEvalIssue(
                ticker=optional_text(row.get("ticker")),
                code=str(row.get("code") or "source_issue").strip(),
                severity=eval_severity,
                message=str(row.get("message") or "").strip(),
            )
        )
    return issues


def _provider_duplicate_url_issue_count(rows: list[dict[str, object]]) -> int:
    return sum(
        1
        for row in rows
        if str(row.get("code") or "").strip().endswith("_duplicate_url")
    )


def _duplicate_url_issues(
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> list[AiBriefSourceEvalIssue]:
    issues: list[AiBriefSourceEvalIssue] = []
    for ticker, sources in sources_by_ticker.items():
        seen_urls: set[str] = set()
        duplicate_urls: set[str] = set()
        for source in sources:
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            if url in seen_urls:
                duplicate_urls.add(url)
            seen_urls.add(url)
        for duplicate_url in sorted(duplicate_urls):
            issues.append(
                AiBriefSourceEvalIssue(
                    ticker=ticker,
                    code="source_duplicate_url",
                    severity="WARN",
                    message=f"duplicate source URL for ticker: {duplicate_url}",
                )
            )
    return issues


def _result(
    *,
    status: AiBriefSourceEvalStatus,
    eligible_tickers: set[str],
    covered_tickers: set[str],
    source_count: int,
    minimum_coverage_ratio: float,
    issues: list[AiBriefSourceEvalIssue],
    duplicate_url_count: int = 0,
) -> AiBriefSourceEvalResult:
    coverage_ratio = _coverage_ratio(
        eligible_tickers=eligible_tickers,
        covered_tickers=covered_tickers,
    )
    return AiBriefSourceEvalResult(
        status=status,
        summary={
            "eligible_ticker_count": len(eligible_tickers),
            "covered_ticker_count": len(covered_tickers),
            "coverage_ratio": coverage_ratio,
            "minimum_coverage_ratio": minimum_coverage_ratio,
            "source_count": source_count,
            "duplicate_url_count": duplicate_url_count,
            "issue_count": len(issues),
        },
        issues=issues,
    )


def _coverage_ratio(*, eligible_tickers: set[str], covered_tickers: set[str]) -> float:
    if not eligible_tickers:
        return 0.0
    return len(covered_tickers) / len(eligible_tickers)


def _leader_labels(
    reports: list[dict[str, object]],
    *,
    key: str,
    prefer_high: bool,
) -> list[str]:
    scores = [
        (
            str(report["label"]),
            _summary_number(report["summary"], key),
        )
        for report in reports
        if isinstance(report.get("summary"), Mapping)
    ]
    if not scores:
        return []
    best_score = (
        max(score for _, score in scores)
        if prefer_high
        else min(score for _, score in scores)
    )
    return sorted(label for label, score in scores if score == best_score)


def _summary_number(summary: object, key: str) -> float:
    if not isinstance(summary, Mapping):
        return 0.0
    value = summary.get(key)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


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
    "AiBriefSourceCompareResult",
    "AiBriefSourceEvalIssue",
    "AiBriefSourceEvalResult",
    "compare_ai_brief_source_reports",
    "evaluate_ai_brief_source_report",
    "parse_eval_now",
]
