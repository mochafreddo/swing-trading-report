from __future__ import annotations

import html
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..utils.numeric import to_finite_float as _to_finite_float
from ..utils.numeric import to_int as _safe_int
from .ai_brief_state import (
    BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE,
    BRIEF_REASON_WEAK_NEWS_COVERAGE,
    BRIEF_STATE_FINAL_JUDGMENT,
    BRIEF_STATE_NEEDS_REVIEW_WATCH_ONLY,
    BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS,
    BRIEF_STATE_NO_SIGNAL,
    read_ai_brief_state,
)
from .risk_disclosure import RISK_GUIDE_NOTICE_KO

TELEGRAM_MESSAGE_MAX_CHARS = 4096
_HTML_LINK_MAX_CHARS = 1024
_HTML_LINK_TOO_LONG_TEXT = "URL too long"
_TRADING_SESSION_TRUE_TEXT = {"1", "true", "yes", "open"}
_ISSUE_MESSAGE_TRANSLATIONS = {
    "No supplied source context.": "제공된 소스 맥락이 없음",
    "OpenAI request timed out.": "OpenAI 요청 시간이 초과됨",
    "OpenAI request failed.": "OpenAI 요청 실패",
    "Finnhub source provider supports US tickers only": (
        "Finnhub 소스 제공자는 US 티커만 지원함"
    ),
    "Polygon News source provider supports US tickers only": (
        "Polygon News 소스 제공자는 US 티커만 지원함"
    ),
    "Alpha Vantage News source provider supports US tickers only": (
        "Alpha Vantage News 소스 제공자는 US 티커만 지원함"
    ),
    "Marketaux News source provider supports US tickers only": (
        "Marketaux News 소스 제공자는 US 티커만 지원함"
    ),
    "Benzinga News source provider supports US tickers only": (
        "Benzinga News 소스 제공자는 US 티커만 지원함"
    ),
    "Naver News source provider supports KR tickers only": (
        "Naver News 소스 제공자는 KR 티커만 지원함"
    ),
}


@dataclass(frozen=True)
class _AiBriefCounts:
    preselected_count: int
    recommendable_count: int
    executable_count: int
    blocked_but_valid_count: int
    role_present: bool
    watch_count: int
    watch_present: bool
    recommendation_count: int
    vetoed_count: int
    source_issue_count: int
    system_issue_count: int
    executable_tickers: list[str]
    blocked_but_valid_tickers: list[str]
    watch_tickers: list[str]
    recommendations: list[dict[str, Any]]
    vetoed_candidates: list[dict[str, Any]]
    source_issues: list[dict[str, Any]]
    system_issues: list[dict[str, Any]]


@dataclass(frozen=True)
class _SellAiBriefCounts:
    actionable_count: int
    preselected_count: int
    judgment_count: int
    excluded_hold_count: int
    unsupported_action_count: int
    vetoed_count: int
    cap_excluded_count: int
    source_issue_count: int
    system_issue_count: int
    judgments: list[dict[str, Any]]
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
    raw_text = _safe_str(value, default=default)
    without_controls = "".join(
        " " if ord(char) < 32 or ord(char) == 127 else char for char in raw_text
    )
    text = " ".join(without_controls.split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _slack_kv(
    key: str,
    value: Any,
    *,
    default: str = "",
    max_chars: int = 360,
) -> str:
    return f"{key}={_safe_single_line(value, default=default, max_chars=max_chars)}"


def _html_escape(value: Any, *, default: str = "") -> str:
    return html.escape(_safe_str(value, default=default), quote=True)


def _html_single_line(
    value: Any,
    *,
    default: str = "",
    max_chars: int = 180,
) -> str:
    return _html_escape(_safe_single_line(value, default=default, max_chars=max_chars))


def _html_bold(value: Any, *, default: str = "") -> str:
    return f"<b>{_html_escape(value, default=default)}</b>"


def _html_code(value: Any, *, default: str = "") -> str:
    return f"<code>{_html_escape(value, default=default)}</code>"


def _html_bold_single_line(
    value: Any,
    *,
    default: str = "",
    max_chars: int = 180,
) -> str:
    return f"<b>{_html_single_line(value, default=default, max_chars=max_chars)}</b>"


def _html_code_single_line(
    value: Any,
    *,
    default: str = "",
    max_chars: int = 180,
) -> str:
    return (
        f"<code>{_html_single_line(value, default=default, max_chars=max_chars)}</code>"
    )


def _is_http_url(value: str) -> bool:
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlparse(value)
        _ = parsed.port
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _html_link(url: Any, label: str) -> str:
    text = _safe_str(url)
    if not text:
        return ""
    if not _is_http_url(text):
        return _html_single_line(text)
    href = _html_escape(text)
    label_text = _html_single_line(label, max_chars=60)
    link = f'<a href="{href}">{label_text}</a>'
    if len(link) > _HTML_LINK_MAX_CHARS:
        return _HTML_LINK_TOO_LONG_TEXT
    return link


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
    executable_tickers = [
        _safe_str(item) for item in _as_list(report.get("executable_tickers"))
    ]
    executable_tickers = [ticker for ticker in executable_tickers if ticker]
    blocked_but_valid_tickers = [
        _safe_str(item) for item in _as_list(report.get("blocked_but_valid_tickers"))
    ]
    blocked_but_valid_tickers = [
        ticker for ticker in blocked_but_valid_tickers if ticker
    ]
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
    role_present = (
        "executable_tickers" in report
        or "blocked_but_valid_tickers" in report
        or "executable_count" in summary
        or "blocked_but_valid_count" in summary
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
    executable_count = max(
        _safe_int(summary.get("executable_count"), default=0),
        len(executable_tickers),
    )
    blocked_but_valid_count = max(
        _safe_int(summary.get("blocked_but_valid_count"), default=0),
        len(blocked_but_valid_tickers),
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
        executable_count=executable_count,
        blocked_but_valid_count=blocked_but_valid_count,
        role_present=role_present,
        watch_count=watch_count,
        watch_present=watch_present,
        recommendation_count=recommendation_count,
        vetoed_count=vetoed_count,
        source_issue_count=source_issue_count,
        system_issue_count=system_issue_count,
        executable_tickers=executable_tickers,
        blocked_but_valid_tickers=blocked_but_valid_tickers,
        watch_tickers=watch_tickers,
        recommendations=recommendations,
        vetoed_candidates=vetoed_candidates,
        source_issues=source_issues,
        system_issues=system_issues,
    )


def _sell_ai_brief_counts(report: dict[str, Any]) -> _SellAiBriefCounts:
    summary = _as_dict(report.get("summary"))
    judgments_raw = _as_list(report.get("judgments"))
    judgments = [row for row in judgments_raw if isinstance(row, dict)]
    vetoed_raw = _as_list(report.get("vetoed_candidates"))
    vetoed_candidates = [row for row in vetoed_raw if isinstance(row, dict)]
    source_issues_raw = _as_list(report.get("source_issues"))
    source_issues = [row for row in source_issues_raw if isinstance(row, dict)]
    system_issues_raw = _as_list(report.get("system_issues"))
    system_issues = [row for row in system_issues_raw if isinstance(row, dict)]
    actionable_tickers = [
        _safe_str(item) for item in _as_list(report.get("actionable_tickers"))
    ]
    actionable_tickers = [ticker for ticker in actionable_tickers if ticker]
    preselected_default = len(actionable_tickers) or len(judgments)
    preselected_count = _safe_int(
        summary.get("preselected_count"),
        default=preselected_default,
    )
    judgment_count = _safe_int(
        summary.get("judgment_count"),
        default=len(judgments),
    )
    return _SellAiBriefCounts(
        actionable_count=_safe_int(
            summary.get("actionable_count"),
            default=preselected_count
            + _safe_int(summary.get("cap_excluded_count"), default=0),
        ),
        preselected_count=preselected_count,
        judgment_count=judgment_count,
        excluded_hold_count=_safe_int(
            summary.get("excluded_hold_count"),
            default=len(_as_list(report.get("excluded_hold_candidates"))),
        ),
        unsupported_action_count=_safe_int(
            summary.get("unsupported_action_count"),
            default=len(_as_list(report.get("unsupported_action_candidates"))),
        ),
        vetoed_count=_safe_int(
            summary.get("vetoed_count"),
            default=len(vetoed_candidates),
        ),
        cap_excluded_count=_safe_int(
            summary.get("cap_excluded_count"),
            default=len(_as_list(report.get("cap_excluded_candidates"))),
        ),
        source_issue_count=_safe_int(
            summary.get("source_issue_count"),
            default=len(source_issues),
        ),
        system_issue_count=_safe_int(
            summary.get("system_issue_count"),
            default=len(system_issues),
        ),
        judgments=judgments,
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
    if normalized == "SELL_PARTIAL":
        return "부분매도"
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
        _slack_kv("repo", repo),
        _slack_kv("provider", provider, default="kis"),
        _slack_kv("universe", universe, default="both"),
        _slack_kv("generated_at", _generated_at(report)),
        _slack_kv("candidate_count", candidate_count),
        _slack_kv("issue_count", issue_count),
    ]
    key = _safe_single_line(storage_key)
    if key:
        lines.append(_slack_kv("storage_key", key))
    lines.append(_slack_kv("run_url", run_url))
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
        _slack_kv("repo", repo),
        _slack_kv("provider", provider, default="kis"),
        _slack_kv("generated_at", _generated_at(report)),
        _slack_kv("evaluated_count", evaluated_count),
        _slack_kv("issue_count", issue_count),
        _slack_kv("action_counts", _format_action_counts(action_counts)),
    ]
    key = _safe_single_line(storage_key)
    if key:
        lines.append(_slack_kv("storage_key", key))
    lines.append(_slack_kv("run_url", run_url))
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
        _slack_kv("repo", repo),
        _slack_kv("market", report.get("market"), default="-"),
        _slack_kv("model_provider", report.get("model_provider"), default="fake"),
        _slack_kv("model_name", report.get("model_name"), default="-"),
        _slack_kv("generated_at", _generated_at(report)),
        _slack_kv("brief_state", brief_state.state),
        _slack_kv("brief_reason", brief_state.reason),
        _slack_kv("preselected_count", counts.preselected_count),
        _slack_kv("recommendation_count", counts.recommendation_count),
        _slack_kv("vetoed_count", counts.vetoed_count),
        _slack_kv("source_issue_count", counts.source_issue_count),
        _slack_kv("system_issue_count", counts.system_issue_count),
    ]
    if counts.watch_present:
        watch_tickers = ", ".join(counts.watch_tickers) if counts.watch_tickers else "-"
        lines.append(_slack_kv("watch_count", counts.watch_count))
        lines.append(_slack_kv("watch_tickers", watch_tickers))
    if counts.role_present:
        executable_tickers = (
            ", ".join(counts.executable_tickers) if counts.executable_tickers else "-"
        )
        blocked_but_valid_tickers = (
            ", ".join(counts.blocked_but_valid_tickers)
            if counts.blocked_but_valid_tickers
            else "-"
        )
        lines.append(_slack_kv("executable_count", counts.executable_count))
        lines.append(
            _slack_kv("blocked_but_valid_count", counts.blocked_but_valid_count)
        )
        lines.append(_slack_kv("executable_tickers", executable_tickers))
        lines.append(_slack_kv("blocked_but_valid_tickers", blocked_but_valid_tickers))
    source_chain_summary = _format_slack_source_chain_summary(report)
    if source_chain_summary:
        source_chain, _, source_final = source_chain_summary.partition(" final ")
        lines.append(source_chain)
        if source_final:
            recommendable_part, _, watch_part = source_final.partition(" watch=")
            lines.append(
                _slack_kv(
                    "source_final_recommendable",
                    recommendable_part.removeprefix("recommendable="),
                )
            )
            lines.append(_slack_kv("source_final_watch", watch_part))
    source_provider_statuses = _format_slack_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(source_provider_statuses)
    key = _safe_single_line(storage_key)
    if key:
        lines.append(_slack_kv("storage_key", key))
    lines.append(_slack_kv("run_url", run_url))
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
        lines.append(RISK_GUIDE_NOTICE_KO)

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
    include_actions: Collection[str] = ("SELL", "SELL_PARTIAL", "REVIEW"),
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
    partial_sell_count = action_counts.get("SELL_PARTIAL", 0)
    review_count = action_counts.get("REVIEW", 0)
    hold_count = action_counts.get("HOLD", 0)

    lines = [
        "[SAB] 매도 점검",
        f"데이터: {_format_provider_label(provider)}",
        f"시각: {_generated_at(report)}",
        (
            f"대상: {total}건 "
            f"(매도 {sell_count}, 부분매도 {partial_sell_count}, "
            f"점검 {review_count}, 보유 {hold_count} 제외)"
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
        lines.append(RISK_GUIDE_NOTICE_KO)

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
    ticker = _safe_single_line(issue.get("ticker"), max_chars=48)
    code = _safe_single_line(issue.get("code"), default="-", max_chars=80)
    message = _safe_single_line(
        _issue_message_for_display(issue.get("message")),
        max_chars=180,
    )
    base = f"{prefix}: {ticker} {code}" if ticker else f"{prefix}: {code}"
    if message:
        return f"{base} - {message}"
    return base


def _issue_message_for_display(message: Any) -> str:
    text = _safe_str(message)
    if not text:
        return ""
    translated = _ISSUE_MESSAGE_TRANSLATIONS.get(text)
    if translated:
        return translated

    http_failure_prefix = "OpenAI request failed with HTTP "
    if text.startswith(http_failure_prefix):
        detail = text.removeprefix(http_failure_prefix)
        status, separator, remainder = detail.partition(": ")
        if separator:
            return f"OpenAI 요청 실패(HTTP {status}): {remainder}"
        return f"OpenAI 요청 실패(HTTP {detail})"

    request_failure_prefix = "OpenAI request failed: "
    if text.startswith(request_failure_prefix):
        return f"OpenAI 요청 실패: {text.removeprefix(request_failure_prefix)}"

    no_results_marker = " returned no usable sources for "
    if no_results_marker in text:
        provider, _, ticker = text.partition(no_results_marker)
        return f"{provider}에서 {ticker}에 사용할 수 있는 소스를 찾지 못함"

    provider_failure_marker = " source provider failed: "
    if provider_failure_marker in text:
        provider, _, detail = text.partition(provider_failure_marker)
        return f"{provider} 소스 제공자 실패: {detail}"

    return text


def _ticker_preview(value: Any, *, max_items: int = 5) -> tuple[str, int]:
    tickers = [_safe_single_line(item, max_chars=48) for item in _as_list(value)]
    tickers = [ticker for ticker in tickers if ticker]
    shown = tickers[: max(max_items, 0)]
    preview = ", ".join(shown)
    return preview, max(len(tickers) - len(shown), 0)


def _format_coverage(covered: Any, total: Any) -> str:
    return f"{_safe_int(covered, default=0)}/{_safe_int(total, default=0)}"


def _format_provider_status_label(status: Any) -> str:
    normalized = _safe_str(status).lower()
    labels = {
        "success": "성공",
        "partial": "부분",
        "failed": "실패",
        "error": "오류",
        "skipped": "건너뜀",
    }
    return labels.get(normalized, _safe_str(status, default="-"))


def _source_provider_summary(report: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(report.get("source_provider_summary"))


def _source_provider_chain(report: dict[str, Any]) -> list[str]:
    source_provider_summary = _source_provider_summary(report)
    chain = [
        _safe_single_line(item, max_chars=80)
        for item in _as_list(source_provider_summary.get("chain"))
    ]
    return [provider for provider in chain if provider]


def _source_provider_status_parts(
    report: dict[str, Any],
    *,
    status_label: Callable[[Any], str],
) -> list[str]:
    source_provider_summary = _source_provider_summary(report)
    parts: list[str] = []
    for raw_provider in _as_list(source_provider_summary.get("providers")):
        provider = _as_dict(raw_provider)
        name = _safe_single_line(provider.get("provider"), max_chars=80)
        if not name:
            continue
        status = _safe_single_line(status_label(provider.get("status")), max_chars=80)
        coverage = _format_coverage(provider.get("covered"), provider.get("total"))
        parts.append(f"{name} {status} {coverage}")
    return parts


def _format_source_chain_summary(report: dict[str, Any]) -> str:
    chain = _source_provider_chain(report)
    if not chain:
        return ""

    chain_text = ", ".join(chain)
    final = _as_dict(_source_provider_summary(report).get("final"))
    if not final:
        return f"소스 체인 {chain_text}"
    recommendable = _format_coverage(
        final.get("recommendable_covered"),
        final.get("recommendable_total"),
    )
    watch = _format_coverage(final.get("watch_covered"), final.get("watch_total"))
    return (
        f"소스 체인 {chain_text} · 추천 커버리지 {recommendable} · "
        f"watch 커버리지 {watch}"
    )


def _format_source_provider_statuses(report: dict[str, Any]) -> str:
    parts = _source_provider_status_parts(
        report,
        status_label=_format_provider_status_label,
    )
    if not parts:
        return ""
    return f"소스 제공자: {'; '.join(parts)}"


def _format_slack_source_chain_summary(report: dict[str, Any]) -> str:
    chain = _source_provider_chain(report)
    if not chain:
        return ""

    final = _as_dict(_source_provider_summary(report).get("final"))
    if not final:
        return f"source_chain={','.join(chain)}"
    recommendable = _format_coverage(
        final.get("recommendable_covered"),
        final.get("recommendable_total"),
    )
    watch = _format_coverage(final.get("watch_covered"), final.get("watch_total"))
    return f"source_chain={','.join(chain)} final recommendable={recommendable} watch={watch}"


def _format_slack_source_provider_statuses(report: dict[str, Any]) -> str:
    parts = _source_provider_status_parts(
        report,
        status_label=lambda status: _safe_str(status, default="-"),
    )
    if not parts:
        return ""
    return f"source_providers={'; '.join(parts)}"


def _ai_brief_decision_text(
    *,
    state: str,
    reason: str,
    recommendation_count: int,
) -> str:
    if state == BRIEF_STATE_NO_SIGNAL:
        return "오늘은 볼 종목 없음. 쉬어도 됨"
    if state == BRIEF_STATE_NEEDS_REVIEW_WATCH_ONLY:
        return "watch 후보만 있음. 재트리거 조건 확인 필요"
    if state == BRIEF_STATE_FINAL_JUDGMENT:
        return f"뉴스 근거 확인된 추천 후보 {recommendation_count}건"
    if reason == BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE:
        return "AI 판단 보류: 모델/시스템 이슈 확인 필요"
    if reason == BRIEF_REASON_WEAK_NEWS_COVERAGE:
        return "뉴스 근거 약함, 기술 신호만 있음"
    return "AI 판단 보류: 추천을 확정하지 않음"


def _sell_ai_brief_decision_text(
    *,
    state: str,
    reason: str,
    judgment_count: int,
) -> str:
    if state == "NO_ACTION":
        return "매도/점검 대상 없음"
    if state == "FINAL_JUDGMENT":
        return f"AI 매도 판단 {judgment_count}건"
    if state == "NEEDS_REVIEW_WEAK_NEWS":
        return "최신 기사 근거 약함, 기술적 매도 신호 중심"
    if state == "MODEL_OR_SYSTEM_ISSUE":
        return "AI 판단 보류: 모델/시스템 이슈 확인 필요"
    if reason == "weak_news_coverage":
        return "최신 기사 근거 약함, 기술적 매도 신호 중심"
    return "AI 판단 보류: 매도 판단을 확정하지 않음"


def build_sell_ai_brief_telegram_report_text(
    *,
    report: dict[str, Any],
    run_url: str,
    storage_key: str | None = None,
    max_items: int = 5,
) -> str:
    counts = _sell_ai_brief_counts(report)
    total = len(counts.judgments)
    shown = min(total, max(max_items, 0), 5)
    model_provider = _safe_str(report.get("model_provider"), default="fake")
    model_name = _safe_str(report.get("model_name"), default="-")
    model_label = f"{model_provider}/{model_name}"
    brief_state = _safe_str(report.get("brief_state"), default="FINAL_JUDGMENT").upper()
    brief_reason = _safe_str(report.get("brief_reason"), default="model_judgment_ready")
    decision = _sell_ai_brief_decision_text(
        state=brief_state,
        reason=brief_reason,
        judgment_count=total,
    )

    lines = [
        _html_bold("SAB Sell AI Brief"),
        (
            f"시장 {_html_code_single_line(report.get('market'), default='-', max_chars=24)} · "
            f"모델 {_html_code_single_line(model_label)}"
        ),
        f"생성 {_html_code_single_line(_generated_at(report), max_chars=80)}",
        "",
        _html_bold("판단"),
        (
            f"상태 {_html_code_single_line(brief_state, max_chars=80)} · "
            f"사유 {_html_code_single_line(brief_reason, max_chars=80)}"
        ),
        _html_escape(decision),
        (
            f"판단 {_html_code(total)}건 · 표시 {_html_code(shown)}건 · "
            f"모델 입력 {_html_code(counts.preselected_count)}건 · "
            f"HOLD 제외 {_html_code(counts.excluded_hold_count)}건 · "
            f"소스 이슈 {_html_code(counts.source_issue_count)} · "
            f"시스템 이슈 {_html_code(counts.system_issue_count)}"
        ),
    ]
    if counts.unsupported_action_count or counts.cap_excluded_count:
        lines.append(
            f"미지원 액션 {_html_code(counts.unsupported_action_count)}건 · "
            f"cap 제외 {_html_code(counts.cap_excluded_count)}건"
        )

    lines.append("")
    if total == 0:
        lines.extend([_html_bold("매도 판단"), "매도/점검 대상 없음"])
    else:
        lines.append(
            f"{_html_bold(f'매도 판단 {total}건')} (표시 {_html_code(shown)}건)"
        )
        for idx, row in enumerate(counts.judgments[:shown], start=1):
            ticker = _safe_single_line(row.get("ticker"), default="-", max_chars=48)
            name = _safe_single_line(row.get("name"), max_chars=96)
            ticker_name = f"{ticker} {name}".strip()
            sell_action = _safe_single_line(
                row.get("sell_action") or row.get("action"),
                default="-",
                max_chars=24,
            ).upper()
            ai_stance = _safe_single_line(
                row.get("ai_stance"),
                default="-",
                max_chars=24,
            ).upper()
            confidence = _safe_single_line(
                row.get("confidence"),
                default="-",
                max_chars=24,
            ).upper()
            reason = _first_list_text(row.get("deterministic_reasons"))
            rationale = _first_list_text(row.get("rationale"))
            source_count = len(_recommendation_sources(row))
            lines.append(
                f"{idx}. {_html_bold_single_line(ticker_name)} · "
                f"{_html_code_single_line(sell_action, max_chars=24)} · "
                f"{_html_code_single_line(ai_stance, max_chars=24)} · "
                f"{_html_code_single_line(confidence, max_chars=24)}"
            )
            lines.append(f"   규칙 {_html_single_line(reason)}")
            lines.append(f"   판단 {_html_single_line(rationale)}")
            source_title = _first_source_title(row)
            if source_title:
                lines.append(
                    f"   근거 {_html_code(source_count)}개 · "
                    f"{_html_single_line(source_title)}"
                )
            else:
                lines.append(f"   근거 {_html_code(source_count)}개")
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {_html_code(extra)}건")

    vetoed_total = len(counts.vetoed_candidates)
    vetoed_shown = min(vetoed_total, max(max_items, 0), 5)
    if vetoed_total > 0:
        lines.extend(["", _html_bold(f"AI 판단 보류 {vetoed_total}건")])
        for row in counts.vetoed_candidates[:vetoed_shown]:
            ticker = _safe_single_line(row.get("ticker"), default="-", max_chars=48)
            sell_action = _safe_single_line(
                row.get("sell_action") or row.get("action"),
                default="-",
                max_chars=24,
            ).upper()
            reason = _safe_single_line(row.get("reason"), default="-", max_chars=180)
            lines.append(
                f"- {_html_code_single_line(ticker, max_chars=48)} · "
                f"{_html_code_single_line(sell_action, max_chars=24)} · "
                f"{_html_single_line(reason)}"
            )
        extra = vetoed_total - vetoed_shown
        if extra > 0:
            lines.append(f"보류 외 {_html_code(extra)}건")

    lines.extend(
        [
            "",
            _html_bold("진단"),
            (
                f"소스 이슈 {_html_code(counts.source_issue_count)} · "
                f"시스템 이슈 {_html_code(counts.system_issue_count)}"
            ),
        ]
    )
    source_chain_summary = _format_source_chain_summary(report)
    if source_chain_summary:
        lines.append(_html_single_line(source_chain_summary, max_chars=360))
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(_html_single_line(source_provider_statuses, max_chars=360))
    for issue in counts.source_issues[:3]:
        lines.append(
            _html_single_line(_format_issue("소스 이슈", issue), max_chars=360)
        )
    for issue in counts.system_issues[:3]:
        lines.append(
            _html_single_line(_format_issue("시스템 이슈", issue), max_chars=360)
        )

    key = _safe_str(storage_key)
    if key:
        lines.append(f"보관 {_html_code_single_line(key)}")
    run_link = _html_link(run_url, "실행 보기")
    if run_link:
        if _is_http_url(_safe_str(run_url)):
            lines.append(run_link)
        else:
            lines.append(f"실행 {run_link}")
    return "\n".join(lines)


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
    model_label = f"{model_provider}/{model_name}"
    brief_state = read_ai_brief_state(report)
    decision = _ai_brief_decision_text(
        state=brief_state.state,
        reason=brief_state.reason,
        recommendation_count=total,
    )

    lines = [
        _html_bold("SAB AI Brief"),
        (
            f"시장 {_html_code_single_line(report.get('market'), default='-', max_chars=24)} · "
            f"모델 {_html_code_single_line(model_label)}"
        ),
        f"생성 {_html_code_single_line(_generated_at(report), max_chars=80)}",
        "",
        _html_bold("판단"),
        (
            f"상태 {_html_code_single_line(brief_state.state, max_chars=80)} · "
            f"사유 {_html_code_single_line(brief_state.reason, max_chars=80)}"
        ),
        _html_escape(decision),
        (
            f"추천 {_html_code(total)}건 · 표시 {_html_code(shown)}건 · "
            f"모델 입력 {_html_code(counts.preselected_count)}건 · "
            f"소스 이슈 {_html_code(counts.source_issue_count)} · "
            f"시스템 이슈 {_html_code(counts.system_issue_count)}"
        ),
    ]

    if counts.role_present:
        lines.append(
            f"역할 실행가능 {_html_code(counts.executable_count)}건 · "
            f"차단/검토 {_html_code(counts.blocked_but_valid_count)}건"
        )
        executable_preview, executable_extra = _ticker_preview(
            counts.executable_tickers
        )
        if executable_preview:
            suffix = f", 외 {executable_extra}건" if executable_extra > 0 else ""
            lines.append(
                "실행가능 후보 "
                f"{_html_code(counts.executable_count)}건: "
                f"{_html_escape(executable_preview)}{_html_escape(suffix)}"
            )
        blocked_preview, blocked_extra = _ticker_preview(
            counts.blocked_but_valid_tickers
        )
        if blocked_preview:
            suffix = f", 외 {blocked_extra}건" if blocked_extra > 0 else ""
            lines.append(
                "차단/검토 후보 "
                f"{_html_code(counts.blocked_but_valid_count)}건: "
                f"{_html_escape(blocked_preview)}{_html_escape(suffix)}"
            )

    if counts.watch_present:
        ticker_preview, extra = _ticker_preview(counts.watch_tickers)
        suffix = f", 외 {extra}건" if extra > 0 else ""
        detail = (
            f": {_html_escape(ticker_preview)}{_html_escape(suffix)}"
            if ticker_preview
            else ""
        )
        lines.append(f"watch 후보 {_html_code(counts.watch_count)}건{detail}")

    if (
        brief_state.state == BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS
        and counts.preselected_count > 0
        and total > 0
    ):
        ticker_preview, extra = _ticker_preview(report.get("eligible_tickers"))
        if ticker_preview:
            suffix = f", 외 {extra}건" if extra > 0 else ""
            lines.append(f"대상: {_html_escape(ticker_preview)}{_html_escape(suffix)}")

    lines.append("")
    if total == 0:
        lines.extend([_html_bold("추천 후보"), "추천 후보 없음"])
        if counts.recommendable_count > 0:
            candidate_count_text = f"{counts.recommendable_count}건"
            if counts.preselected_count != counts.recommendable_count:
                candidate_count_text = (
                    f"{candidate_count_text}(모델 입력 {counts.preselected_count}건)"
                )
            lines.append(
                "추천 생성 실패/보류: 모델 후보 "
                f"{_html_escape(candidate_count_text)}이 있었지만 추천 결과가 비었습니다."
            )
            ticker_preview, extra = _ticker_preview(report.get("eligible_tickers"))
            if ticker_preview:
                suffix = f", 외 {extra}건" if extra > 0 else ""
                lines.append(
                    f"대상: {_html_escape(ticker_preview)}{_html_escape(suffix)}"
                )
    else:
        lines.append(
            f"{_html_bold(f'추천 후보 {total}건')} (표시 {_html_code(shown)}건)"
        )
        for idx, row in enumerate(counts.recommendations[:shown], start=1):
            ticker = _safe_single_line(row.get("ticker"), default="-", max_chars=48)
            name = _safe_single_line(row.get("name"), max_chars=96)
            ticker_name = f"{ticker} {name}".strip()
            confidence = _safe_single_line(
                row.get("confidence"),
                default="-",
                max_chars=24,
            ).upper()
            rationale = _first_list_text(row.get("rationale"))
            source_count = len(_recommendation_sources(row))
            lines.append(
                f"{idx}. {_html_bold_single_line(ticker_name)} · "
                f"{_html_code_single_line(confidence, max_chars=24)}"
            )
            lines.append(f"   {_html_single_line(rationale)}")
            source_title = _first_source_title(row)
            if source_title:
                lines.append(
                    f"   근거 {_html_code(source_count)}개 · "
                    f"{_html_single_line(source_title)}"
                )
            else:
                lines.append(f"   근거 {_html_code(source_count)}개")
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {_html_code(extra)}건")

    vetoed_total = len(counts.vetoed_candidates)
    vetoed_shown = min(vetoed_total, max(max_items, 0), 3)
    if vetoed_total > 0:
        lines.extend(["", _html_bold(f"AI 판단 제외 {vetoed_total}건")])
        for row in counts.vetoed_candidates[:vetoed_shown]:
            ticker = _safe_single_line(row.get("ticker"), default="-", max_chars=48)
            action = _safe_single_line(
                row.get("action"),
                default="-",
                max_chars=24,
            ).upper()
            reason = _safe_single_line(row.get("reason"), default="-", max_chars=180)
            lines.append(
                f"- {_html_code_single_line(ticker, max_chars=48)} · "
                f"{_html_code_single_line(action, max_chars=24)} · "
                f"{_html_single_line(reason)}"
            )
        extra = vetoed_total - vetoed_shown
        if extra > 0:
            lines.append(f"제외 외 {_html_code(extra)}건")

    lines.extend(
        [
            "",
            _html_bold("진단"),
            (
                f"소스 이슈 {_html_code(counts.source_issue_count)} · "
                f"시스템 이슈 {_html_code(counts.system_issue_count)}"
            ),
        ]
    )
    source_chain_summary = _format_source_chain_summary(report)
    if source_chain_summary:
        lines.append(_html_single_line(source_chain_summary, max_chars=360))
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(_html_single_line(source_provider_statuses, max_chars=360))

    for issue in counts.source_issues[:3]:
        lines.append(
            _html_single_line(_format_issue("소스 이슈", issue), max_chars=360)
        )
    for issue in counts.system_issues[:3]:
        lines.append(
            _html_single_line(_format_issue("시스템 이슈", issue), max_chars=360)
        )

    key = _safe_str(storage_key)
    if key:
        lines.append(f"보관 {_html_code_single_line(key)}")
    run_link = _html_link(run_url, "실행 보기")
    if run_link:
        if _is_http_url(_safe_str(run_url)):
            lines.append(run_link)
        else:
            lines.append(f"실행 {run_link}")
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
    "build_sell_ai_brief_telegram_report_text",
    "build_sell_slack_summary_text",
    "build_sell_telegram_report_text",
    "split_telegram_message_text",
]
