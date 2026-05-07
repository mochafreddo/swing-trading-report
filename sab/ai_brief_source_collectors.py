from __future__ import annotations

import datetime as dt
import email.utils
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from xml.etree import ElementTree as ET
from xml.parsers import expat

from .ai_brief_sources import (
    MAX_SOURCES_PER_TICKER,
    SOURCE_FRESHNESS_HOURS,
    SOURCE_FUTURE_SKEW_MINUTES,
    SOURCE_REPORT_SCHEMA,
    SOURCE_REPORT_TYPE,
    is_ai_brief_source_future,
    is_ai_brief_source_stale,
    validate_ai_brief_source_url,
)

SOURCE_FEED_CATALOG_SCHEMA = "sab.ai_brief_source_feed_catalog.v1"
MAX_FEED_CATALOG_BYTES = 1_000_000
MAX_FEED_BYTES = 1_000_000

AiBriefSourceCollectStatus = Literal["PASS", "WARN"]


class AiBriefSourceCollectorError(RuntimeError):
    pass


class _UnsafeFeedXmlError(RuntimeError):
    pass


class _FeedFileTooLargeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiBriefSourceCollectIssue:
    code: str
    message: str
    ticker: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "code": self.code,
            "severity": "WARN",
            "message": self.message,
        }


@dataclass(frozen=True)
class AiBriefSourceCollectResult:
    generated_at: dt.datetime
    sources: list[dict[str, object]]
    issues: list[AiBriefSourceCollectIssue]

    @property
    def status(self) -> AiBriefSourceCollectStatus:
        return "WARN" if self.issues else "PASS"

    def to_dict(self) -> dict[str, object]:
        covered_tickers = sorted(
            {
                str(source.get("ticker") or "").strip()
                for source in self.sources
                if str(source.get("ticker") or "").strip()
            }
        )
        return {
            "schema": SOURCE_REPORT_SCHEMA,
            "type": SOURCE_REPORT_TYPE,
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "summary": {
                "source_count": len(self.sources),
                "covered_ticker_count": len(covered_tickers),
                "covered_tickers": covered_tickers,
                "issue_count": len(self.issues),
            },
            "sources": self.sources,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _FeedSourceRow:
    ticker: str
    title: str
    url: str
    published_at: dt.datetime


def collect_ai_brief_sources(
    *,
    feed_catalog_path: str,
    tickers: set[str] | None = None,
    now: dt.datetime | None = None,
    freshness_hours: float = SOURCE_FRESHNESS_HOURS,
    max_sources_per_ticker: int = MAX_SOURCES_PER_TICKER,
) -> AiBriefSourceCollectResult:
    if not math.isfinite(freshness_hours) or freshness_hours < 0:
        raise ValueError("freshness_hours must be non-negative")
    if freshness_hours > SOURCE_FRESHNESS_HOURS:
        raise ValueError(f"freshness_hours must be at most {SOURCE_FRESHNESS_HOURS:g}")
    if max_sources_per_ticker < 1:
        raise ValueError("max_sources_per_ticker must be positive")
    if max_sources_per_ticker > MAX_SOURCES_PER_TICKER:
        raise ValueError(
            f"max_sources_per_ticker must be at most {MAX_SOURCES_PER_TICKER}"
        )

    resolved_now = now or dt.datetime.now().astimezone()
    requested_tickers = _normalize_requested_tickers(tickers)
    catalog_path = Path(feed_catalog_path)
    catalog = _load_feed_catalog(catalog_path)
    raw_feeds = catalog.get("feeds")
    if not isinstance(raw_feeds, list):
        raise AiBriefSourceCollectorError("feed catalog feeds must be a list")

    issues: list[AiBriefSourceCollectIssue] = []
    rows_by_ticker: dict[str, list[_FeedSourceRow]] = {}
    seen_catalog_tickers: set[str] = set()
    for idx, raw_feed in enumerate(raw_feeds):
        if not isinstance(raw_feed, Mapping):
            issues.append(
                AiBriefSourceCollectIssue(
                    code="feed_catalog_invalid_row",
                    message=f"feeds[{idx}] ignored because it is not an object",
                )
            )
            continue
        ticker = str(raw_feed.get("ticker") or "").strip()
        feed_path_text = str(
            raw_feed.get("path") or raw_feed.get("feed_path") or ""
        ).strip()
        if not ticker or not feed_path_text:
            issues.append(
                AiBriefSourceCollectIssue(
                    ticker=ticker or None,
                    code="feed_catalog_invalid_row",
                    message=(
                        f"feeds[{idx}] ignored because ticker and path are required"
                    ),
                )
            )
            continue
        if requested_tickers and ticker not in requested_tickers:
            continue
        seen_catalog_tickers.add(ticker)

        try:
            feed_path = _resolve_feed_path(catalog_path, feed_path_text)
        except ValueError as exc:
            issues.append(
                AiBriefSourceCollectIssue(
                    ticker=ticker,
                    code="feed_catalog_invalid_row",
                    message=f"feeds[{idx}] ignored because {exc}",
                )
            )
            continue
        feed_rows, feed_issues = _load_feed_rows(ticker=ticker, feed_path=feed_path)
        issues.extend(feed_issues)
        rows_by_ticker.setdefault(ticker, []).extend(feed_rows)
    for missing_ticker in sorted(requested_tickers - seen_catalog_tickers):
        issues.append(
            AiBriefSourceCollectIssue(
                ticker=missing_ticker,
                code="feed_catalog_missing_ticker",
                message="requested ticker was not found in the feed catalog",
            )
        )

    sources, normalize_issues = _normalize_feed_rows(
        rows_by_ticker=rows_by_ticker,
        now=resolved_now,
        freshness_hours=freshness_hours,
        max_sources_per_ticker=max_sources_per_ticker,
    )
    issues.extend(normalize_issues)
    return AiBriefSourceCollectResult(
        generated_at=resolved_now,
        sources=sources,
        issues=issues,
    )


def _load_feed_catalog(path: Path) -> Mapping[str, Any]:
    try:
        with open(path, "rb") as fp:
            data = fp.read(MAX_FEED_CATALOG_BYTES + 1)
        if len(data) > MAX_FEED_CATALOG_BYTES:
            raise AiBriefSourceCollectorError(
                "feed catalog is too large "
                f"({len(data)} bytes > {MAX_FEED_CATALOG_BYTES} bytes)"
            )
        payload = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise AiBriefSourceCollectorError(
            f"failed to load feed catalog: {exc}"
        ) from exc
    except AiBriefSourceCollectorError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise AiBriefSourceCollectorError(
            f"failed to load feed catalog: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise AiBriefSourceCollectorError("feed catalog must contain a JSON object")
    schema = str(payload.get("schema") or "").strip()
    if schema and schema != SOURCE_FEED_CATALOG_SCHEMA:
        raise AiBriefSourceCollectorError(f"unsupported feed catalog schema {schema!r}")
    return cast(Mapping[str, Any], payload)


def _resolve_feed_path(catalog_path: Path, feed_path_text: str) -> Path:
    feed_path = Path(feed_path_text)
    if feed_path.is_absolute():
        raise ValueError("feed path must be relative to the feed catalog directory")
    catalog_dir = catalog_path.parent.resolve()
    resolved_feed_path = (catalog_dir / feed_path).resolve()
    if not resolved_feed_path.is_relative_to(catalog_dir):
        raise ValueError("feed path must stay within the feed catalog directory")
    return resolved_feed_path


def _display_feed_path(feed_path: Path) -> str:
    return feed_path.name or "<feed>"


def _load_feed_rows(
    *,
    ticker: str,
    feed_path: Path,
) -> tuple[list[_FeedSourceRow], list[AiBriefSourceCollectIssue]]:
    try:
        root = _parse_feed_root(feed_path)
    except _FeedFileTooLargeError as exc:
        return [], [
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code="feed_file_too_large",
                message=f"feed ignored because file is too large: {exc}",
            )
        ]
    except _UnsafeFeedXmlError as exc:
        return [], [
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code="feed_file_unsafe_xml",
                message=f"feed ignored because XML is unsafe: {exc}",
            )
        ]
    except OSError:
        return [], [
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code="feed_file_failed",
                message=f"failed to read feed {_display_feed_path(feed_path)}",
            )
        ]
    except ET.ParseError as exc:
        return [], [
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code="feed_file_failed",
                message=(
                    f"failed to parse feed {_display_feed_path(feed_path)}: {exc}"
                ),
            )
        ]

    root_name = _local_name(root.tag).lower()
    if root_name in {"rss", "rdf"}:
        raw_entries = _rss_items(root)
        feed_kind = "rss"
    elif root_name == "feed":
        raw_entries = _children_named(root, "entry")
        feed_kind = "atom"
    else:
        return [], [
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code="feed_format_unsupported",
                message=f"unsupported feed root {root.tag!r}",
            )
        ]

    rows: list[_FeedSourceRow] = []
    issues: list[AiBriefSourceCollectIssue] = []
    if not raw_entries:
        issues.append(
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code="feed_file_empty",
                message="feed ignored because it contains no entries",
            )
        )
    for idx, raw_entry in enumerate(raw_entries):
        if feed_kind == "rss":
            parsed, issue = _parse_rss_item(ticker, idx, raw_entry)
        else:
            parsed, issue = _parse_atom_entry(ticker, idx, raw_entry)
        if issue is not None:
            issues.append(issue)
            continue
        assert parsed is not None
        rows.append(parsed)
    return rows, issues


def _parse_feed_root(feed_path: Path) -> ET.Element:
    with open(feed_path, "rb") as fp:
        data = fp.read(MAX_FEED_BYTES + 1)
    if len(data) > MAX_FEED_BYTES:
        raise _FeedFileTooLargeError(
            f"{len(data)} bytes exceeds {MAX_FEED_BYTES} byte limit"
        )
    _reject_unsafe_xml_declarations(data)
    return ET.fromstring(data)


def _reject_unsafe_xml_declarations(data: bytes) -> None:
    parser = expat.ParserCreate()

    def reject_doctype(*_args: object) -> None:
        raise _UnsafeFeedXmlError("DOCTYPE declarations are not allowed")

    def reject_entity(*_args: object) -> None:
        raise _UnsafeFeedXmlError("ENTITY declarations are not allowed")

    def reject_external_entity(
        _context: str,
        _base: str | None,
        _system_id: str | None,
        _public_id: str | None,
    ) -> int:
        raise _UnsafeFeedXmlError("external entity references are not allowed")

    parser.StartDoctypeDeclHandler = reject_doctype
    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_external_entity
    try:
        parser.Parse(data, True)
    except _UnsafeFeedXmlError:
        raise
    except expat.ExpatError:
        pass


def _rss_items(root: ET.Element) -> list[ET.Element]:
    channel = _first_child(root, "channel")
    if channel is not None:
        return _children_named(channel, "item")
    return _children_named(root, "item")


def _parse_rss_item(
    ticker: str,
    idx: int,
    item: ET.Element,
) -> tuple[_FeedSourceRow, None] | tuple[None, AiBriefSourceCollectIssue]:
    title = _first_child_text(item, "title")
    url = _first_child_text(item, "link")
    published_text = (
        _first_child_text(item, "pubDate")
        or _first_child_text(item, "published")
        or _first_child_text(item, "updated")
        or _first_child_text(item, "date")
    )
    return _build_feed_row(
        ticker=ticker,
        idx=idx,
        title=title,
        url=url,
        published_text=published_text,
    )


def _parse_atom_entry(
    ticker: str,
    idx: int,
    entry: ET.Element,
) -> tuple[_FeedSourceRow, None] | tuple[None, AiBriefSourceCollectIssue]:
    published_text = _first_child_text(entry, "published") or _first_child_text(
        entry, "updated"
    )
    return _build_feed_row(
        ticker=ticker,
        idx=idx,
        title=_first_child_text(entry, "title"),
        url=_atom_entry_url(entry),
        published_text=published_text,
    )


def _atom_entry_url(entry: ET.Element) -> str:
    fallback_url = ""
    for link in _children_named(entry, "link"):
        url = str(link.attrib.get("href") or "").strip() or _element_text(link)
        if not url:
            continue
        rel = str(link.attrib.get("rel") or "alternate").strip().lower()
        if rel == "alternate":
            return url
        if not fallback_url:
            fallback_url = url
    return fallback_url


def _build_feed_row(
    *,
    ticker: str,
    idx: int,
    title: str,
    url: str,
    published_text: str,
) -> tuple[_FeedSourceRow, None] | tuple[None, AiBriefSourceCollectIssue]:
    if not title or not url or not published_text:
        return None, AiBriefSourceCollectIssue(
            ticker=ticker,
            code="feed_item_invalid_row",
            message=(
                f"feed item {idx} ignored because title, url, "
                "and published_at are required"
            ),
        )
    try:
        url = validate_ai_brief_source_url(url)
    except ValueError as exc:
        return None, AiBriefSourceCollectIssue(
            ticker=ticker,
            code="feed_item_invalid_row",
            message=f"feed item {idx} ignored because {exc}",
        )
    try:
        published_at = _parse_feed_datetime(published_text)
    except ValueError as exc:
        return None, AiBriefSourceCollectIssue(
            ticker=ticker,
            code="feed_item_invalid_row",
            message=f"feed item {idx} ignored because {exc}",
        )
    return (
        _FeedSourceRow(
            ticker=ticker,
            title=title,
            url=url,
            published_at=published_at,
        ),
        None,
    )


def _normalize_feed_rows(
    *,
    rows_by_ticker: Mapping[str, list[_FeedSourceRow]],
    now: dt.datetime,
    freshness_hours: float,
    max_sources_per_ticker: int,
) -> tuple[list[dict[str, object]], list[AiBriefSourceCollectIssue]]:
    sources: list[dict[str, object]] = []
    issues: list[AiBriefSourceCollectIssue] = []
    for ticker in sorted(rows_by_ticker):
        emitted_count = 0
        seen_urls: set[str] = set()
        rows = sorted(
            rows_by_ticker[ticker],
            key=lambda row: row.published_at.astimezone(dt.UTC),
            reverse=True,
        )
        for row in rows:
            if is_ai_brief_source_stale(
                row.published_at,
                now=now,
                freshness_hours=freshness_hours,
            ):
                issues.append(
                    AiBriefSourceCollectIssue(
                        ticker=ticker,
                        code="feed_item_stale",
                        message=(
                            "feed item ignored because published_at is older than "
                            f"{freshness_hours:g}h"
                        ),
                    )
                )
                continue
            if is_ai_brief_source_future(row.published_at, now=now):
                issues.append(
                    AiBriefSourceCollectIssue(
                        ticker=ticker,
                        code="feed_item_future",
                        message=(
                            "feed item ignored because published_at is more than "
                            f"{SOURCE_FUTURE_SKEW_MINUTES}m in the future"
                        ),
                    )
                )
                continue
            if row.url in seen_urls:
                issues.append(
                    AiBriefSourceCollectIssue(
                        ticker=ticker,
                        code="feed_item_duplicate_url",
                        message=f"duplicate feed item URL ignored: {row.url}",
                    )
                )
                continue
            seen_urls.add(row.url)
            if emitted_count >= max_sources_per_ticker:
                issues.append(
                    AiBriefSourceCollectIssue(
                        ticker=ticker,
                        code="feed_item_cap_exceeded",
                        message=(
                            "feed item ignored because ticker already has "
                            f"{max_sources_per_ticker} sources"
                        ),
                    )
                )
                continue
            sources.append(
                {
                    "ticker": row.ticker,
                    "title": row.title,
                    "url": row.url,
                    "published_at": row.published_at.isoformat(),
                }
            )
            emitted_count += 1
    return sources, issues


def _normalize_requested_tickers(tickers: set[str] | None) -> set[str]:
    if tickers is None:
        return set()
    return {ticker.strip() for ticker in tickers if ticker.strip()}


def _parse_feed_datetime(value: str) -> dt.datetime:
    text = value.strip()
    if not text:
        raise ValueError("published_at is required")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                "published_at must be an ISO 8601 or RFC 2822 datetime"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must include a UTC offset")
    return parsed


def _children_named(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _local_name(child.tag) == name]


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in list(element):
        if _local_name(child.tag) == name:
            return child
    return None


def _first_child_text(element: ET.Element, name: str) -> str:
    child = _first_child(element, name)
    if child is None:
        return ""
    return _element_text(child)


def _element_text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def parse_collect_now(value: str) -> dt.datetime:
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
    "MAX_FEED_BYTES",
    "MAX_FEED_CATALOG_BYTES",
    "SOURCE_FEED_CATALOG_SCHEMA",
    "SOURCE_REPORT_SCHEMA",
    "SOURCE_REPORT_TYPE",
    "AiBriefSourceCollectIssue",
    "AiBriefSourceCollectResult",
    "AiBriefSourceCollectorError",
    "collect_ai_brief_sources",
    "parse_collect_now",
]
