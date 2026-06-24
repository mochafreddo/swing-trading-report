from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

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
