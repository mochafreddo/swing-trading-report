from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from ..utils.numeric import to_finite_float as _to_finite_float
from ..utils.numeric import to_int as _safe_int
from .ai_brief_state import (
    BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE,
    BRIEF_REASON_WEAK_NEWS_COVERAGE,
    BRIEF_STATE_FINAL_JUDGMENT,
    BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
    BRIEF_STATE_NO_SIGNAL,
    read_ai_brief_state,
)

TELEGRAM_MESSAGE_MAX_CHARS = 4096
_TRADING_SESSION_TRUE_TEXT = {"1", "true", "yes", "open"}


@dataclass(frozen=True)
class _AiBriefCounts:
    preselected_count: int
    recommendable_count: int
    watch_count: int
    watch_present: bool
    recommendation_count: int
    vetoed_count: int
    source_issue_count: int
    system_issue_count: int
    watch_tickers: list[str]
    recommendations: list[dict[str, Any]]
    vetoed_candidates: list[dict[str, Any]]
    source_issues: list[dict[str, Any]]
    system_issues: list[dict[str, Any]]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return _to_finite_float(value)


def _safe_str(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _safe_single_line(value: Any, *, default: str = "", max_chars: int = 140) -> str:
    text = " ".join(_safe_str(value, default=default).split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


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


def _ai_brief_counts(report: dict[str, Any]) -> _AiBriefCounts:
    summary = _as_dict(report.get("summary"))
    recommendations_raw = _as_list(report.get("recommendations"))
    recommendations = [row for row in recommendations_raw if isinstance(row, dict)]
    vetoed_raw = _as_list(report.get("vetoed_candidates"))
    vetoed_candidates = [row for row in vetoed_raw if isinstance(row, dict)]
    watch_raw = _as_list(report.get("watch_candidates"))
    watch_candidates = [row for row in watch_raw if isinstance(row, dict)]
    source_issues_raw = _as_list(report.get("source_issues"))
    source_issues = [row for row in source_issues_raw if isinstance(row, dict)]
    system_issues_raw = _as_list(report.get("system_issues"))
    system_issues = [row for row in system_issues_raw if isinstance(row, dict)]
    eligible_count = len(
        [item for item in _as_list(report.get("eligible_tickers")) if _safe_str(item)]
    )
    watch_tickers = [_safe_str(item) for item in _as_list(report.get("watch_tickers"))]
    watch_tickers = [ticker for ticker in watch_tickers if ticker]
    if not watch_tickers:
        watch_tickers = [
            _safe_str(row.get("ticker"))
            for row in watch_candidates
            if _safe_str(row.get("ticker"))
        ]
    watch_present = (
        "watch_tickers" in report
        or "watch_candidates" in report
        or "watch_count" in summary
    )

    recommendation_count = max(
        _safe_int(summary.get("recommendation_count"), default=0),
        _safe_int(report.get("recommendation_count"), default=0),
        len(recommendations),
    )
    watch_count = max(
        _safe_int(summary.get("watch_count"), default=0),
        len(watch_tickers),
        len(watch_candidates),
    )
    vetoed_count = max(
        _safe_int(summary.get("vetoed_count"), default=0),
        _safe_int(report.get("vetoed_count"), default=0),
        len(vetoed_candidates),
    )
    preselected_count = max(
        _safe_int(summary.get("preselected_count"), default=0),
        _safe_int(report.get("preselected_count"), default=0),
        eligible_count,
        len(recommendations),
        len(recommendations) + len(vetoed_candidates),
        recommendation_count,
        vetoed_count,
    )
    recommendable_count = max(
        _safe_int(summary.get("recommendable_count"), default=0),
        _safe_int(report.get("recommendable_count"), default=0),
        preselected_count,
    )
    source_issue_count = max(
        _safe_int(summary.get("source_issue_count"), default=0),
        _safe_int(report.get("source_issue_count"), default=0),
        len(source_issues),
    )
    system_issue_count = max(
        _safe_int(summary.get("system_issue_count"), default=0),
        _safe_int(report.get("system_issue_count"), default=0),
        len(system_issues),
    )
    return _AiBriefCounts(
        preselected_count=preselected_count,
        recommendable_count=recommendable_count,
        watch_count=watch_count,
        watch_present=watch_present,
        recommendation_count=recommendation_count,
        vetoed_count=vetoed_count,
        source_issue_count=source_issue_count,
        system_issue_count=system_issue_count,
        watch_tickers=watch_tickers,
        recommendations=recommendations,
        vetoed_candidates=vetoed_candidates,
        source_issues=source_issues,
        system_issues=system_issues,
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


def _format_sell_action(action: str) -> str:
    normalized = _safe_str(action).upper()
    if normalized == "SELL":
        return "매도"
    if normalized == "REVIEW":
        return "점검"
    if normalized == "HOLD":
        return "보유"
    return normalized or "-"


def _format_provider_label(provider: Any) -> str:
    normalized = _safe_str(provider, default="kis").lower()
    labels = {
        "kis": "KIS",
        "pykrx": "PyKRX",
    }
    return labels.get(normalized, _safe_str(provider, default="KIS"))


def _format_universe_label(universe: Any) -> str:
    normalized = _safe_str(universe, default="both").lower()
    labels = {
        "kr": "국내",
        "us": "미국",
        "both": "국내+미국",
    }
    return labels.get(normalized, _safe_str(universe, default="국내+미국"))


def _is_scan_telegram_candidate(row: dict[str, Any]) -> bool:
    entry_state = _safe_str(row.get("entry_state")).upper()
    return entry_state in {"", "READY"}


def _normalize_actions(actions: Collection[str]) -> set[str]:
    normalized = {_safe_str(action).upper() for action in actions}
    normalized.discard("")
    return normalized


def split_telegram_message_text(
    text: str,
    *,
    max_chars: int = TELEGRAM_MESSAGE_MAX_CHARS,
) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    lines = str(text).splitlines()
    if not lines:
        return []

    parts: list[str] = []
    current = ""
    for line in lines:
        pending = line
        while pending:
            if not current:
                if len(pending) <= max_chars:
                    current = pending
                    pending = ""
                else:
                    parts.append(pending[:max_chars])
                    pending = pending[max_chars:]
                continue

            candidate = f"{current}\n{pending}"
            if len(candidate) <= max_chars:
                current = candidate
                pending = ""
            else:
                parts.append(current)
                current = ""

        if line == "" and current:
            candidate = f"{current}\n"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                parts.append(current)
                current = ""

    if current:
        parts.append(current)
    return parts


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
    counts = _ai_brief_counts(report)
    brief_state = read_ai_brief_state(report)

    lines = [
        "[SAB][ai-brief][schedule]",
        f"repo={repo}",
        f"market={_safe_str(report.get('market'), default='-')}",
        f"model_provider={_safe_str(report.get('model_provider'), default='fake')}",
        f"model_name={_safe_str(report.get('model_name'), default='-')}",
        f"generated_at={_generated_at(report)}",
        f"brief_state={brief_state.state}",
        f"brief_reason={brief_state.reason}",
        f"preselected_count={counts.preselected_count}",
        f"recommendation_count={counts.recommendation_count}",
        f"vetoed_count={counts.vetoed_count}",
        f"source_issue_count={counts.source_issue_count}",
        f"system_issue_count={counts.system_issue_count}",
    ]
    if counts.watch_present:
        watch_tickers = ", ".join(counts.watch_tickers) if counts.watch_tickers else "-"
        lines.append(f"watch_count={counts.watch_count}")
        lines.append(f"watch_tickers={watch_tickers}")
    source_chain_summary = _format_source_chain_summary(report)
    if source_chain_summary:
        source_chain, _, source_final = source_chain_summary.partition(" final ")
        lines.append(source_chain)
        if source_final:
            recommendable_part, _, watch_part = source_final.partition(" watch=")
            lines.append(
                f"source_final_recommendable={recommendable_part.removeprefix('recommendable=')}"
            )
            lines.append(f"source_final_watch={watch_part}")
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(source_provider_statuses)
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
    max_items: int | None = None,
) -> str:
    # Kept for existing callers; scan Telegram intentionally lists all READY rows.
    _ = max_items
    candidates_raw = _as_list(report.get("candidates"))
    ready_candidates = [
        row
        for row in candidates_raw
        if isinstance(row, dict) and _is_scan_telegram_candidate(row)
    ]
    total = len(ready_candidates)

    lines = [
        "[SAB] 매수 후보",
        (
            f"시장: {_format_universe_label(universe)} / "
            f"데이터: {_format_provider_label(provider)}"
        ),
        f"시각: {_generated_at(report)}",
        f"진입 가능: {total}건",
    ]

    if total == 0:
        lines.append("진입 가능 후보 없음")
    else:
        for idx, row in enumerate(ready_candidates, start=1):
            ticker = _safe_str(row.get("ticker"), default="-")
            name = _safe_str(row.get("name"))
            ticker_name = f"{ticker} {name}".strip()
            price = _safe_str(row.get("price"), default="-")
            score = _safe_str(
                row.get("score"),
                default=_safe_str(row.get("score_value"), default="-"),
            )
            reason = _safe_str(
                row.get("entry_state_reason"),
                default=_safe_str(
                    row.get("pattern_reasons"),
                    default=_safe_str(row.get("risk_guide"), default="-"),
                ),
            )
            lines.append(f"{idx}. {ticker_name} | {price} | 점수 {score} | {reason}")

    key = _safe_str(storage_key)
    if key:
        lines.append(f"보관: {key}")
    lines.append(f"실행: {run_url}")
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
        "[SAB] 매도 점검",
        f"데이터: {_format_provider_label(provider)}",
        f"시각: {_generated_at(report)}",
        (
            f"대상: {total}건 "
            f"(매도 {sell_count}, 점검 {review_count}, 보유 {hold_count} 제외)"
        ),
    ]

    if total == 0:
        lines.append("매도/점검 대상 없음")
    else:
        for idx, row in enumerate(filtered[:shown], start=1):
            ticker = _safe_str(row.get("ticker"), default="-")
            action = _format_sell_action(_safe_str(row.get("action"), default="-"))
            pnl = _format_pnl(row.get("pnl_pct"))
            reason = _first_reason(row)
            lines.append(f"{idx}. {ticker} | {action} | {pnl} | {reason}")
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {extra}건")

    key = _safe_str(storage_key)
    if key:
        lines.append(f"보관: {key}")
    lines.append(f"실행: {run_url}")
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
    message = _safe_single_line(issue.get("message"))
    base = f"{prefix}: {ticker} {code}" if ticker else f"{prefix}: {code}"
    if message:
        return f"{base} - {message}"
    return base


def _ticker_preview(value: Any, *, max_items: int = 5) -> tuple[str, int]:
    tickers = [_safe_str(item) for item in _as_list(value)]
    tickers = [ticker for ticker in tickers if ticker]
    shown = tickers[: max(max_items, 0)]
    preview = ", ".join(shown)
    return preview, max(len(tickers) - len(shown), 0)


def _format_coverage(covered: Any, total: Any) -> str:
    return f"{_safe_int(covered, default=0)}/{_safe_int(total, default=0)}"


def _format_source_chain_summary(report: dict[str, Any]) -> str:
    source_provider_summary = _as_dict(report.get("source_provider_summary"))
    chain = [_safe_str(item) for item in _as_list(source_provider_summary.get("chain"))]
    chain = [provider for provider in chain if provider]
    if not chain:
        return ""

    final = _as_dict(source_provider_summary.get("final"))
    if not final:
        return f"source_chain={','.join(chain)}"
    recommendable = _format_coverage(
        final.get("recommendable_covered"),
        final.get("recommendable_total"),
    )
    watch = _format_coverage(final.get("watch_covered"), final.get("watch_total"))
    return f"source_chain={','.join(chain)} final recommendable={recommendable} watch={watch}"


def _format_source_provider_statuses(report: dict[str, Any]) -> str:
    source_provider_summary = _as_dict(report.get("source_provider_summary"))
    parts: list[str] = []
    for raw_provider in _as_list(source_provider_summary.get("providers")):
        provider = _as_dict(raw_provider)
        name = _safe_str(provider.get("provider"))
        if not name:
            continue
        status = _safe_str(provider.get("status"), default="-")
        coverage = _format_coverage(provider.get("covered"), provider.get("total"))
        parts.append(f"{name} {status} {coverage}")
    if not parts:
        return ""
    return f"source_providers={'; '.join(parts)}"


def build_ai_brief_telegram_report_text(
    *,
    report: dict[str, Any],
    run_url: str,
    storage_key: str | None = None,
    max_items: int = 5,
) -> str:
    counts = _ai_brief_counts(report)
    total = len(counts.recommendations)
    shown = min(total, max(max_items, 0), 3)
    model_provider = _safe_str(report.get("model_provider"), default="fake")
    model_name = _safe_str(report.get("model_name"), default="-")
    brief_state = read_ai_brief_state(report)

    lines = [
        "[SAB][ai-brief][schedule]",
        f"market={_safe_str(report.get('market'), default='-')}",
        f"model={model_provider}/{model_name}",
        f"generated_at={_generated_at(report)}",
        f"brief_state={brief_state.state}",
        f"brief_reason={brief_state.reason}",
        f"entry_preselected_count={counts.preselected_count}",
        f"추천 후보 {total}건 (표시 {shown}건)",
        (
            f"issues source={counts.source_issue_count} "
            f"system={counts.system_issue_count}"
        ),
    ]
    if counts.watch_present:
        ticker_preview, extra = _ticker_preview(counts.watch_tickers)
        suffix = f", 외 {extra}건" if extra > 0 else ""
        detail = f": {ticker_preview}{suffix}" if ticker_preview else ""
        lines.append(f"watch 후보 {counts.watch_count}건{detail}")
    source_chain_summary = _format_source_chain_summary(report)
    if source_chain_summary:
        lines.append(source_chain_summary)
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(source_provider_statuses)

    if brief_state.state == BRIEF_STATE_NO_SIGNAL:
        lines.append("오늘은 볼 종목 없음. 쉬어도 됨")
    elif brief_state.state == BRIEF_STATE_FINAL_JUDGMENT:
        lines.append(f"AI 최종 판단: 뉴스 근거 확인된 후보 {total}건")
    elif brief_state.reason == BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE:
        lines.append("AI 판단 보류: 모델/시스템 이슈 확인 필요")
    elif brief_state.reason == BRIEF_REASON_WEAK_NEWS_COVERAGE:
        lines.append("뉴스 근거 약함, 기술 신호만 있음")
    else:
        lines.append("AI 판단 보류: 추천을 확정하지 않음")

    if (
        brief_state.state == BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS
        and counts.preselected_count > 0
        and total > 0
    ):
        ticker_preview, extra = _ticker_preview(report.get("eligible_tickers"))
        if ticker_preview:
            suffix = f", 외 {extra}건" if extra > 0 else ""
            lines.append(f"대상: {ticker_preview}{suffix}")

    if total == 0:
        lines.append("추천 후보 없음")
        if counts.recommendable_count > 0:
            candidate_count_text = f"{counts.recommendable_count}건"
            if counts.preselected_count != counts.recommendable_count:
                candidate_count_text = (
                    f"{candidate_count_text}(모델 입력 {counts.preselected_count}건)"
                )
            lines.append(
                "추천 생성 실패/보류: recommendable 후보 "
                f"{candidate_count_text}이 있었지만 추천 결과가 비었습니다."
            )
            ticker_preview, extra = _ticker_preview(report.get("eligible_tickers"))
            if ticker_preview:
                suffix = f", 외 {extra}건" if extra > 0 else ""
                lines.append(f"대상: {ticker_preview}{suffix}")
    else:
        for idx, row in enumerate(counts.recommendations[:shown], start=1):
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

    vetoed_total = len(counts.vetoed_candidates)
    vetoed_shown = min(vetoed_total, max(max_items, 0), 3)
    if vetoed_total > 0:
        lines.append(f"AI 판단 제외 {vetoed_total}건")
        for row in counts.vetoed_candidates[:vetoed_shown]:
            ticker = _safe_str(row.get("ticker"), default="-")
            action = _safe_str(row.get("action"), default="-").upper()
            reason = _safe_single_line(row.get("reason"), default="-")
            lines.append(f"- {ticker} | {action} | {reason}")
        extra = vetoed_total - vetoed_shown
        if extra > 0:
            lines.append(f"제외 외 {extra}건")

    for issue in counts.source_issues[:3]:
        lines.append(_format_issue("source issue", issue))
    for issue in counts.system_issues[:3]:
        lines.append(_format_issue("system issue", issue))

    key = _safe_str(storage_key)
    if key:
        lines.append(f"storage_key={key}")
    lines.append(f"run_url={run_url}")
    return "\n".join(lines)


def build_ai_brief_skipped_telegram_text(
    *,
    market: str,
    session_state: str,
    session_date: str,
    run_url: str,
    expected_state: str | None = None,
    local_time: str | None = None,
    trading_session: object | None = None,
) -> str:
    session_state_text = _safe_str(session_state, default="-")
    expected_state_text = _safe_str(expected_state)
    local_time_text = _safe_str(local_time)
    trading_session_text = _safe_str(trading_session)
    skip_reason = ""
    is_trading_session = (
        trading_session_text.lower() in _TRADING_SESSION_TRUE_TEXT
        if trading_session_text
        else None
    )
    is_delayed_pre_open = (
        is_trading_session is True
        and expected_state_text.upper() == "PRE_OPEN"
        and session_state_text.upper() == "INTRADAY"
    )

    if is_delayed_pre_open:
        skip_message = (
            "GitHub scheduled run이 장전 window 이후 실행되어 AI Brief 건너뜀"
        )
        skip_reason = "scheduled_run_after_pre_open_window"
    elif is_trading_session is False:
        skip_message = "거래일이 아니라 AI Brief 건너뜀"
    else:
        skip_message = "장전 시간이 아니라 AI Brief 건너뜀"

    lines = [
        "[SAB][ai-brief][skipped]",
        f"market={_safe_str(market, default='-')}",
        f"session_state={session_state_text}",
        f"session_date={_safe_str(session_date, default='-')}",
    ]
    if expected_state_text:
        lines.append(f"expected_state={expected_state_text}")
    if local_time_text:
        lines.append(f"local_time={local_time_text}")
    if trading_session_text:
        lines.append(f"trading_session={trading_session_text}")
    if skip_reason:
        lines.append(f"reason={skip_reason}")
    lines.extend(
        [
            skip_message,
            f"run_url={run_url}",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "build_ai_brief_skipped_telegram_text",
    "build_ai_brief_slack_summary_text",
    "build_ai_brief_telegram_report_text",
    "build_scan_slack_summary_text",
    "build_scan_telegram_report_text",
    "build_sell_slack_summary_text",
    "build_sell_telegram_report_text",
    "split_telegram_message_text",
]
