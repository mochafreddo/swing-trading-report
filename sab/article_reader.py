from __future__ import annotations

import datetime as dt
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .ai_brief_source_report import source_issue

ArticleReaderName = Literal["none", "lightpanda"]
ArticleReadStatus = Literal[
    "not_attempted",
    "metadata_only",
    "accessed",
    "verified",
    "blocked",
    "failed",
]
SourceBackingTier = Literal[
    "metadata_backed",
    "article_accessed",
    "article_verified",
]

DEFAULT_ARTICLE_READER_MAX_URLS = 8
DEFAULT_ARTICLE_READER_TIMEOUT_SECONDS = 8.0
DEFAULT_ARTICLE_READER_MAX_EXCERPT_CHARS = 1200
DEFAULT_ARTICLE_READER_MAX_RESPONSE_BYTES = 1_000_000

type LightpandaRunner = Callable[[str, float], tuple[int, str, str]]


@dataclass(frozen=True)
class ArticleReaderSettings:
    reader: ArticleReaderName = "none"
    max_urls: int = DEFAULT_ARTICLE_READER_MAX_URLS
    timeout_seconds: float = DEFAULT_ARTICLE_READER_TIMEOUT_SECONDS
    max_excerpt_chars: int = DEFAULT_ARTICLE_READER_MAX_EXCERPT_CHARS
    require_verified: bool = False

    @property
    def enabled(self) -> bool:
        return self.reader != "none" and self.max_urls > 0


@dataclass(frozen=True)
class ArticleVerification:
    tier: SourceBackingTier
    matched_terms: tuple[str, ...]


@dataclass(frozen=True)
class ArticleReadResult:
    status: ArticleReadStatus
    tier: SourceBackingTier
    checked_at: dt.datetime
    reader: ArticleReaderName
    excerpt: str = ""
    matched_terms: tuple[str, ...] = ()
    issue_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "tier": self.tier,
            "checked_at": self.checked_at.isoformat(),
            "reader": self.reader,
            "excerpt": self.excerpt,
            "matched_terms": list(self.matched_terms),
            "issue_code": self.issue_code,
        }


def extract_bounded_excerpt(text: str, *, max_chars: int) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max(0, max_chars - 3)].rstrip() + "..."


def _ticker_terms(ticker: str) -> tuple[str, ...]:
    root = ticker.split(".", 1)[0].strip().upper()
    return (root,) if root else ()


def _contains_term(text: str, term: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.I)
    return pattern.search(text) is not None


def verify_article_text(
    text: str,
    *,
    ticker: str,
    company_terms: Sequence[str],
) -> ArticleVerification:
    matched: list[str] = []
    for term in (*_ticker_terms(ticker), *tuple(company_terms)):
        normalized = str(term or "").strip()
        if (
            normalized
            and normalized not in matched
            and _contains_term(text, normalized)
        ):
            matched.append(normalized)
    return ArticleVerification(
        tier="article_verified" if matched else "article_accessed",
        matched_terms=tuple(matched),
    )


def article_read_summary(
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> dict[str, int]:
    attempted = 0
    accessed = 0
    verified = 0
    issues = 0
    for sources in sources_by_ticker.values():
        for source in sources:
            raw_read = source.get("article_read")
            if not isinstance(raw_read, Mapping):
                continue
            attempted += 1
            status = str(raw_read.get("status") or "")
            tier = str(raw_read.get("tier") or "")
            issue_code = str(raw_read.get("issue_code") or "").strip()
            if status == "accessed" or tier == "article_accessed":
                accessed += 1
            if status == "verified" or tier == "article_verified":
                verified += 1
            if issue_code:
                issues += 1
    return {
        "article_read_attempted_count": attempted,
        "article_accessed_count": accessed,
        "article_verified_count": verified,
        "article_read_issue_count": issues,
    }


def _default_lightpanda_runner(
    url: str, timeout_seconds: float
) -> tuple[int, str, str]:
    completed = subprocess.run(
        [
            "lightpanda",
            "fetch",
            url,
            "--dump",
            "markdown",
            "--block-private-networks",
            "--obey-robots",
            "--disable-subframes",
            "--disable-workers",
            "--http-max-response-size",
            str(DEFAULT_ARTICLE_READER_MAX_RESPONSE_BYTES),
            "--http-timeout",
            str(int(timeout_seconds * 1000)),
            "--terminate-ms",
            str(int(timeout_seconds * 1000)),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds + 1.0,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _issue_code_for_failure(stderr: str) -> tuple[ArticleReadStatus, str]:
    text = stderr.lower()
    if "captcha" in text or "challenge" in text:
        return "blocked", "article_bot_challenge"
    if "paywall" in text or "login" in text:
        return "blocked", "article_paywalled"
    if "robots" in text:
        return "blocked", "article_robots_blocked"
    if "403" in text or "429" in text or "forbidden" in text or "rate" in text:
        return "blocked", "article_access_blocked"
    if "response size" in text or "max response" in text or "too large" in text:
        return "failed", "article_response_too_large"
    return "failed", "article_reader_failed"


def _metadata_only_result(
    *,
    status: ArticleReadStatus,
    checked_at: dt.datetime,
    reader: ArticleReaderName,
    issue_code: str | None = None,
) -> ArticleReadResult:
    return ArticleReadResult(
        status=status,
        tier="metadata_backed",
        checked_at=checked_at,
        reader=reader,
        issue_code=issue_code,
    )


def _article_source_issue(
    *,
    ticker: str,
    code: str,
    message: str,
) -> dict[str, object]:
    return source_issue(ticker=ticker, code=code, message=message)


def _read_one_source(
    *,
    ticker: str,
    source: Mapping[str, object],
    company_terms: Sequence[str],
    settings: ArticleReaderSettings,
    now: dt.datetime,
    lightpanda_runner: LightpandaRunner,
) -> tuple[ArticleReadResult, dict[str, object] | None]:
    url = str(source.get("url") or "").strip()
    try:
        returncode, stdout, stderr = lightpanda_runner(url, settings.timeout_seconds)
    except subprocess.TimeoutExpired:
        result = _metadata_only_result(
            status="failed",
            checked_at=now,
            reader=settings.reader,
            issue_code="article_timeout",
        )
        return result, _article_source_issue(
            ticker=ticker,
            code="article_timeout",
            message="article reader timed out while reading source URL",
        )
    except OSError:
        result = _metadata_only_result(
            status="failed",
            checked_at=now,
            reader=settings.reader,
            issue_code="article_reader_failed",
        )
        return result, _article_source_issue(
            ticker=ticker,
            code="article_reader_failed",
            message="article reader failed before reading source URL",
        )
    if returncode != 0:
        status, issue_code = _issue_code_for_failure(stderr)
        result = _metadata_only_result(
            status=status,
            checked_at=now,
            reader=settings.reader,
            issue_code=issue_code,
        )
        return result, _article_source_issue(
            ticker=ticker,
            code=issue_code,
            message="article reader could not access source URL",
        )
    excerpt = extract_bounded_excerpt(stdout, max_chars=settings.max_excerpt_chars)
    if not excerpt:
        result = _metadata_only_result(
            status="failed",
            checked_at=now,
            reader=settings.reader,
            issue_code="article_empty_content",
        )
        return result, _article_source_issue(
            ticker=ticker,
            code="article_empty_content",
            message="article reader extracted no usable source text",
        )
    verification = verify_article_text(
        excerpt,
        ticker=ticker,
        company_terms=company_terms,
    )
    return ArticleReadResult(
        status="verified" if verification.tier == "article_verified" else "accessed",
        tier=verification.tier,
        checked_at=now,
        reader=settings.reader,
        excerpt=excerpt,
        matched_terms=verification.matched_terms,
        issue_code=None,
    ), None


def enrich_sources_with_article_reads(
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
    *,
    ticker_names: Mapping[str, str],
    settings: ArticleReaderSettings,
    now: dt.datetime,
    lightpanda_runner: LightpandaRunner = _default_lightpanda_runner,
) -> tuple[dict[str, list[dict[str, object]]], list[dict[str, object]]]:
    enriched: dict[str, list[dict[str, object]]] = {}
    issues: list[dict[str, object]] = []
    attempted = 0
    for ticker in sorted(sources_by_ticker):
        enriched_rows: list[dict[str, object]] = []
        company_name = str(ticker_names.get(ticker) or "").strip()
        company_terms = (company_name,) if company_name else ()
        for source in sources_by_ticker[ticker]:
            row = dict(source)
            if not settings.enabled or attempted >= settings.max_urls:
                row["article_read"] = _metadata_only_result(
                    status="not_attempted",
                    checked_at=now,
                    reader=settings.reader,
                ).to_dict()
                enriched_rows.append(row)
                continue

            attempted += 1
            read_result, issue = _read_one_source(
                ticker=ticker,
                source=row,
                company_terms=company_terms,
                settings=settings,
                now=now,
                lightpanda_runner=lightpanda_runner,
            )
            row["article_read"] = read_result.to_dict()
            if issue is not None:
                issues.append(issue)
            enriched_rows.append(row)
        enriched[ticker] = enriched_rows
    return enriched, issues
