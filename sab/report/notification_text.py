from __future__ import annotations

from collections.abc import Collection
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except TypeError, ValueError:
        return default


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except TypeError, ValueError:
        return None


def _safe_str(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _generated_at(report: dict[str, Any]) -> str:
    generated_at = _safe_str(report.get("generated_at"))
    if generated_at:
        return generated_at

    run_at = _safe_str(report.get("run_at"))
    tz = _safe_str(report.get("tz"))
    if run_at and tz:
        return f"{run_at} {tz}"
    if run_at:
        return run_at
    return _safe_str(report.get("date"), default="-")


def _scan_counts(report: dict[str, Any]) -> tuple[int, int]:
    summary = _as_dict(report.get("summary"))
    candidates = _as_list(report.get("candidates"))
    issues = _as_list(report.get("issues")) or _as_list(report.get("failures"))

    candidate_count = _safe_int(
        summary.get("candidate_count"),
        default=_safe_int(report.get("candidate_count"), default=len(candidates)),
    )
    issue_count = _safe_int(
        summary.get("issue_count"),
        default=_safe_int(report.get("issue_count"), default=len(issues)),
    )
    return candidate_count, issue_count


def _sell_counts(
    report: dict[str, Any],
) -> tuple[int, int, dict[str, int], list[dict[str, Any]]]:
    summary = _as_dict(report.get("summary"))
    evaluated_raw = _as_list(report.get("evaluated"))
    evaluated = [row for row in evaluated_raw if isinstance(row, dict)]
    issues = _as_list(report.get("issues")) or _as_list(report.get("failures"))

    action_counts_raw = _as_dict(summary.get("action_counts"))
    action_counts: dict[str, int] = {}
    if action_counts_raw:
        for raw_key, raw_value in action_counts_raw.items():
            key = _safe_str(raw_key).upper()
            if not key:
                continue
            action_counts[key] = _safe_int(raw_value, default=0)
    else:
        for row in evaluated:
            key = _safe_str(row.get("action")).upper()
            if not key:
                continue
            action_counts[key] = action_counts.get(key, 0) + 1

    evaluated_count = _safe_int(
        summary.get("evaluated_count"),
        default=_safe_int(report.get("evaluated_count"), default=len(evaluated)),
    )
    issue_count = _safe_int(
        summary.get("issue_count"),
        default=_safe_int(report.get("issue_count"), default=len(issues)),
    )
    return evaluated_count, issue_count, action_counts, evaluated


def _ai_brief_counts(
    report: dict[str, Any],
) -> tuple[
    int, int, int, int, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    summary = _as_dict(report.get("summary"))
    recommendations_raw = _as_list(report.get("recommendations"))
    recommendations = [row for row in recommendations_raw if isinstance(row, dict)]
    source_issues_raw = _as_list(report.get("source_issues"))
    source_issues = [row for row in source_issues_raw if isinstance(row, dict)]
    system_issues_raw = _as_list(report.get("system_issues"))
    system_issues = [row for row in system_issues_raw if isinstance(row, dict)]

    preselected_count = _safe_int(
        summary.get("preselected_count"),
        default=_safe_int(report.get("preselected_count"), default=0),
    )
    recommendation_count = _safe_int(
        summary.get("recommendation_count"),
        default=_safe_int(
            report.get("recommendation_count"), default=len(recommendations)
        ),
    )
    source_issue_count = _safe_int(
        summary.get("source_issue_count"),
        default=_safe_int(report.get("source_issue_count"), default=len(source_issues)),
    )
    system_issue_count = _safe_int(
        summary.get("system_issue_count"),
        default=_safe_int(report.get("system_issue_count"), default=len(system_issues)),
    )
    return (
        preselected_count,
        recommendation_count,
        source_issue_count,
        system_issue_count,
        recommendations,
        source_issues,
        system_issues,
    )


def _format_action_counts(action_counts: dict[str, int]) -> str:
    if not action_counts:
        return "-"
    parts = [f"{key}:{action_counts[key]}" for key in sorted(action_counts)]
    return ", ".join(parts) if parts else "-"


def _first_reason(row: dict[str, Any]) -> str:
    reasons = row.get("reasons")
    if isinstance(reasons, list):
        for reason in reasons:
            text = _safe_str(reason)
            if text:
                return text
    return _safe_str(reasons, default="-")


def _first_list_text(value: Any, *, default: str = "-") -> str:
    if isinstance(value, list):
        for item in value:
            text = _safe_str(item)
            if text:
                return text
    return _safe_str(value, default=default)


def _format_pnl(value: Any) -> str:
    pnl = _safe_float(value)
    if pnl is None:
        return "-"
    return f"{pnl * 100:+.1f}%"


def _normalize_actions(actions: Collection[str]) -> set[str]:
    normalized = {_safe_str(action).upper() for action in actions}
    normalized.discard("")
    return normalized


def build_scan_slack_summary_text(
    *,
    report: dict[str, Any],
    repo: str,
    run_url: str,
    provider: str,
    universe: str,
    storage_key: str | None = None,
) -> str:
    candidate_count, issue_count = _scan_counts(report)

    lines = [
        "[SAB][scan][schedule]",
        f"repo={repo}",
        f"provider={_safe_str(provider, default='kis')}",
        f"universe={_safe_str(universe, default='both')}",
        f"generated_at={_generated_at(report)}",
        f"candidate_count={candidate_count}",
        f"issue_count={issue_count}",
    ]
    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


def build_sell_slack_summary_text(
    *,
    report: dict[str, Any],
    repo: str,
    run_url: str,
    provider: str,
    storage_key: str | None = None,
) -> str:
    evaluated_count, issue_count, action_counts, _ = _sell_counts(report)

    lines = [
        "[SAB][sell][schedule]",
        f"repo={repo}",
        f"provider={_safe_str(provider, default='kis')}",
        f"generated_at={_generated_at(report)}",
        f"evaluated_count={evaluated_count}",
        f"issue_count={issue_count}",
        f"action_counts={_format_action_counts(action_counts)}",
    ]
    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


def build_ai_brief_slack_summary_text(
    *,
    report: dict[str, Any],
    repo: str,
    run_url: str,
    storage_key: str | None = None,
) -> str:
    (
        preselected_count,
        recommendation_count,
        source_issue_count,
        system_issue_count,
        _,
        _source_issues,
        _system_issues,
    ) = _ai_brief_counts(report)

    lines = [
        "[SAB][ai-brief][schedule]",
        f"repo={repo}",
        f"market={_safe_str(report.get('market'), default='-')}",
        f"model_provider={_safe_str(report.get('model_provider'), default='fake')}",
        f"model_name={_safe_str(report.get('model_name'), default='-')}",
        f"generated_at={_generated_at(report)}",
        f"preselected_count={preselected_count}",
        f"recommendation_count={recommendation_count}",
        f"source_issue_count={source_issue_count}",
        f"system_issue_count={system_issue_count}",
    ]
    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


def build_scan_telegram_report_text(
    *,
    report: dict[str, Any],
    run_url: str,
    provider: str,
    universe: str,
    storage_key: str | None = None,
    max_items: int = 5,
) -> str:
    candidates_raw = _as_list(report.get("candidates"))
    candidates = [row for row in candidates_raw if isinstance(row, dict)]
    total = len(candidates)
    shown = min(total, max(max_items, 0))

    lines = [
        "[SAB][scan][schedule]",
        f"provider={_safe_str(provider, default='kis')}",
        f"universe={_safe_str(universe, default='both')}",
        f"generated_at={_generated_at(report)}",
        f"매수 후보 {total}건 (표시 {shown}건)",
    ]

    if total == 0:
        lines.append("매수 후보 없음")
    else:
        for idx, row in enumerate(candidates[:shown], start=1):
            ticker = _safe_str(row.get("ticker"), default="-")
            name = _safe_str(row.get("name"))
            ticker_name = f"{ticker} {name}".strip()
            price = _safe_str(row.get("price"), default="-")
            score = _safe_str(
                row.get("score"),
                default=_safe_str(row.get("score_value"), default="-"),
            )
            entry_state = _safe_str(row.get("entry_state"), default="-")
            reason = _safe_str(
                row.get("entry_state_reason"),
                default=_safe_str(
                    row.get("pattern_reasons"),
                    default=_safe_str(row.get("risk_guide"), default="-"),
                ),
            )
            lines.append(
                f"{idx}. {ticker_name} | {price} | score {score} | "
                f"{entry_state}/{reason}"
            )
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {extra}건")

    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


def build_sell_telegram_report_text(
    *,
    report: dict[str, Any],
    run_url: str,
    provider: str,
    include_actions: Collection[str] = ("SELL", "REVIEW"),
    storage_key: str | None = None,
    max_items: int = 5,
) -> str:
    _, _, action_counts, evaluated = _sell_counts(report)
    allowed = _normalize_actions(include_actions)
    filtered = [
        row for row in evaluated if _safe_str(row.get("action")).upper() in allowed
    ]

    total = len(filtered)
    shown = min(total, max(max_items, 0))
    sell_count = action_counts.get("SELL", 0)
    review_count = action_counts.get("REVIEW", 0)
    hold_count = action_counts.get("HOLD", 0)

    lines = [
        "[SAB][sell][schedule]",
        f"provider={_safe_str(provider, default='kis')}",
        f"generated_at={_generated_at(report)}",
        (
            f"매도/점검 후보 {total}건 "
            f"(SELL {sell_count}, REVIEW {review_count}, HOLD {hold_count} 제외)"
        ),
    ]

    if total == 0:
        lines.append("매도/점검 후보 없음")
    else:
        for idx, row in enumerate(filtered[:shown], start=1):
            ticker = _safe_str(row.get("ticker"), default="-")
            action = _safe_str(row.get("action"), default="-").upper()
            pnl = _format_pnl(row.get("pnl_pct"))
            reason = _first_reason(row)
            lines.append(f"{idx}. {ticker} | {action} | PnL {pnl} | {reason}")
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {extra}건")

    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


def _recommendation_sources(recommendation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        source
        for source in _as_list(recommendation.get("sources"))
        if isinstance(source, dict)
    ]


def _first_source_title(recommendation: dict[str, Any]) -> str:
    for source in _recommendation_sources(recommendation):
        title = _safe_str(source.get("title"))
        if title:
            return title
    return ""


def _format_issue(prefix: str, issue: dict[str, Any]) -> str:
    ticker = _safe_str(issue.get("ticker"))
    code = _safe_str(issue.get("code"), default="-")
    if ticker:
        return f"{prefix}: {ticker} {code}"
    return f"{prefix}: {code}"


def build_ai_brief_telegram_report_text(
    *,
    report: dict[str, Any],
    run_url: str,
    storage_key: str | None = None,
    max_items: int = 5,
) -> str:
    (
        _preselected_count,
        _recommendation_count,
        source_issue_count,
        system_issue_count,
        recommendations,
        source_issues,
        system_issues,
    ) = _ai_brief_counts(report)
    total = len(recommendations)
    shown = min(total, max(max_items, 0))
    model_provider = _safe_str(report.get("model_provider"), default="fake")
    model_name = _safe_str(report.get("model_name"), default="-")

    lines = [
        "[SAB][ai-brief][schedule]",
        f"market={_safe_str(report.get('market'), default='-')}",
        f"model={model_provider}/{model_name}",
        f"generated_at={_generated_at(report)}",
        f"추천 후보 {total}건 (표시 {shown}건)",
        f"issues source={source_issue_count} system={system_issue_count}",
    ]

    if total == 0:
        lines.append("추천 후보 없음")
    else:
        for idx, row in enumerate(recommendations[:shown], start=1):
            ticker = _safe_str(row.get("ticker"), default="-")
            name = _safe_str(row.get("name"))
            ticker_name = f"{ticker} {name}".strip()
            confidence = _safe_str(row.get("confidence"), default="-").upper()
            rationale = _first_list_text(row.get("rationale"))
            source_count = len(_recommendation_sources(row))
            lines.append(
                f"{idx}. {ticker_name} | {confidence} | {rationale} | "
                f"sources {source_count}"
            )
            source_title = _first_source_title(row)
            if source_title:
                lines.append(f"   source: {source_title}")
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {extra}건")

    for issue in source_issues[:3]:
        lines.append(_format_issue("source issue", issue))
    for issue in system_issues[:3]:
        lines.append(_format_issue("system issue", issue))

    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


__all__ = [
    "build_ai_brief_slack_summary_text",
    "build_ai_brief_telegram_report_text",
    "build_scan_slack_summary_text",
    "build_scan_telegram_report_text",
    "build_sell_slack_summary_text",
    "build_sell_telegram_report_text",
]
