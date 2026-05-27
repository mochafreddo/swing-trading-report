from __future__ import annotations

import datetime as dt
import email.utils
import json
import math
import socket
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from xml.parsers import expat

import requests  # type: ignore[import-untyped]

from . import ai_brief_url_safety as url_safety
from .ai_brief_sources import (
    MAX_SOURCES_PER_TICKER,
    SOURCE_DNS_PIN_LOCK,
    SOURCE_FRESHNESS_HOURS,
    SOURCE_FUTURE_SKEW_MINUTES,
    SOURCE_REPORT_SCHEMA,
    SOURCE_REPORT_TYPE,
    is_ai_brief_source_future,
    is_ai_brief_source_stale,
    validate_ai_brief_source_url,
)
from .utils.closing import close_quietly

SOURCE_FEED_CATALOG_SCHEMA = "sab.ai_brief_source_feed_catalog.v1"
MAX_FEED_CATALOG_BYTES = 1_000_000
MAX_FEED_BYTES = 1_000_000
DEFAULT_FEED_TIMEOUT_SECONDS = 10.0
FEED_ITEM_DNS_TIMEOUT_SECONDS = 1.0
FEED_DNS_RESOLVER_WORKERS = 4
FEED_RESPONSE_READ_TIMEOUT_SECONDS = 1.0
_FEED_DNS_RESOLVER_SLOTS = threading.BoundedSemaphore(FEED_DNS_RESOLVER_WORKERS)

AiBriefSourceCollectStatus = Literal["PASS", "WARN"]


class AiBriefSourceCollectorError(RuntimeError):
    pass


class _UnsafeFeedXmlError(RuntimeError):
    pass


class _FeedFileTooLargeError(RuntimeError):
    pass


class _FeedUrlFetchError(RuntimeError):
    pass


class _FeedUrlTimeoutError(RuntimeError):
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


@dataclass(frozen=True)
class _ValidatedFeedUrl:
    url: str
    hostnames: tuple[str, ...]
    addrinfos: tuple[Any, ...]


def _feed_rows_single_issue(
    *,
    ticker: str | None,
    code: str,
    message: str,
) -> tuple[list[_FeedSourceRow], list[AiBriefSourceCollectIssue]]:
    return [], [AiBriefSourceCollectIssue(ticker=ticker, code=code, message=message)]


def collect_ai_brief_sources(
    *,
    feed_catalog_path: str,
    tickers: set[str] | None = None,
    now: dt.datetime | None = None,
    freshness_hours: float = SOURCE_FRESHNESS_HOURS,
    max_sources_per_ticker: int = MAX_SOURCES_PER_TICKER,
    feed_timeout_seconds: float = DEFAULT_FEED_TIMEOUT_SECONDS,
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
    if not math.isfinite(feed_timeout_seconds) or feed_timeout_seconds <= 0:
        raise ValueError("feed_timeout_seconds must be positive")

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
        if requested_tickers and (not ticker or ticker not in requested_tickers):
            continue
        feed_path_text = _first_non_empty_text(
            raw_feed.get("path"),
            raw_feed.get("feed_path"),
        )
        feed_url_text = _first_non_empty_text(
            raw_feed.get("url"),
            raw_feed.get("feed_url"),
        )
        if not ticker or bool(feed_path_text) == bool(feed_url_text):
            issues.append(
                AiBriefSourceCollectIssue(
                    ticker=ticker or None,
                    code="feed_catalog_invalid_row",
                    message=(
                        f"feeds[{idx}] ignored because ticker and exactly one of "
                        "path/feed_path or url/feed_url are required"
                    ),
                )
            )
            continue
        seen_catalog_tickers.add(ticker)

        if feed_path_text:
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
            feed_rows, feed_issues = _load_feed_rows(
                ticker=ticker,
                feed_path=feed_path,
            )
        else:
            feed_rows, feed_issues = _load_feed_url_rows(
                ticker=ticker,
                feed_url_text=feed_url_text,
                feed_timeout_seconds=feed_timeout_seconds,
            )
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


def _first_non_empty_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


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


def _validate_feed_url(
    value: object,
    *,
    deadline: float | None = None,
) -> _ValidatedFeedUrl:
    try:
        url = validate_ai_brief_source_url(value, field_name="feed URL")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("feed URL must use https")
    port = url_safety.validated_url_port(parsed, field_name="feed URL")
    hostname = parsed.hostname or ""
    hostnames = _feed_url_fetch_hostname_aliases(hostname, field_name="feed URL")
    addrinfos = _resolve_feed_url_addrinfos(hostnames, port, deadline=deadline)
    return _ValidatedFeedUrl(
        url=url,
        hostnames=hostnames,
        addrinfos=addrinfos,
    )


def _feed_url_hostname_aliases(hostname: str) -> tuple[str, ...]:
    return url_safety.hostname_aliases(hostname)


def _feed_url_fetch_hostname_aliases(
    hostname: str,
    *,
    field_name: str,
) -> tuple[str, ...]:
    return url_safety.fetch_hostname_aliases(hostname, field_name=field_name)


def _resolve_feed_url_addrinfos(
    hostnames: tuple[str, ...],
    port: int,
    *,
    deadline: float | None,
) -> tuple[Any, ...]:
    if any(url_safety.is_blocked_hostname(hostname) for hostname in hostnames):
        raise ValueError("feed URL must not target local or private hosts")
    resolution_hostname = hostnames[-1] if hostnames else ""
    try:
        with _feed_dns_pin_lock(deadline):
            addrinfos = _getaddrinfo_with_timeout(
                resolution_hostname,
                port,
                timeout=_feed_dns_timeout(deadline),
            )
    except TimeoutError as exc:
        raise _FeedUrlTimeoutError("feed URL DNS resolution timed out") from exc
    except OSError as exc:
        raise ValueError("feed URL hostname could not be resolved") from exc
    if not addrinfos:
        raise ValueError("feed URL hostname could not be resolved")
    if any(url_safety.is_blocked_addrinfo(addrinfo) for addrinfo in addrinfos):
        raise ValueError("feed URL must not target local or private hosts")
    return tuple(addrinfos)


def _getaddrinfo_with_timeout(
    hostname: str,
    port: int,
    *,
    timeout: float,
) -> list[Any]:
    return url_safety.getaddrinfo_with_timeout(
        hostname,
        port,
        timeout=timeout,
        slots=_FEED_DNS_RESOLVER_SLOTS,
        resolver=socket.getaddrinfo,
        thread_factory=threading.Thread,
        monotonic=time.monotonic,
        thread_name="ai-brief-feed-dns",
    )


def _feed_dns_timeout(deadline: float | None) -> float:
    timeout = FEED_ITEM_DNS_TIMEOUT_SECONDS
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("DNS resolution timed out")
    return min(timeout, remaining)


def _load_feed_rows(
    *,
    ticker: str,
    feed_path: Path,
) -> tuple[list[_FeedSourceRow], list[AiBriefSourceCollectIssue]]:
    try:
        root = _parse_feed_root(feed_path)
    except _FeedFileTooLargeError as exc:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_file_too_large",
            message=f"feed ignored because file is too large: {exc}",
        )
    except _UnsafeFeedXmlError as exc:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_file_unsafe_xml",
            message=f"feed ignored because XML is unsafe: {exc}",
        )
    except OSError:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_file_failed",
            message=f"failed to read feed {_display_feed_path(feed_path)}",
        )
    except ET.ParseError as exc:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_file_failed",
            message=f"failed to parse feed {_display_feed_path(feed_path)}: {exc}",
        )

    return _rows_from_feed_root(
        ticker=ticker,
        root=root,
        empty_issue_code="feed_file_empty",
        empty_issue_message="feed ignored because it contains no entries",
        source_url_deadline=None,
        resolve_source_url_hostnames=False,
    )


def _load_feed_url_rows(
    *,
    ticker: str,
    feed_url_text: str,
    feed_timeout_seconds: float,
) -> tuple[list[_FeedSourceRow], list[AiBriefSourceCollectIssue]]:
    deadline = time.monotonic() + feed_timeout_seconds
    try:
        feed_url = _validate_feed_url(feed_url_text, deadline=deadline)
    except _FeedUrlTimeoutError as exc:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_url_timeout",
            message=f"feed URL request timed out: {exc}",
        )
    except ValueError as exc:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_url_invalid",
            message=f"feed URL ignored because {exc}",
        )

    session = requests.Session()
    session.trust_env = False
    try:
        try:
            with _pin_feed_url_dns(
                feed_url.hostnames,
                feed_url.addrinfos,
                deadline=deadline,
            ):
                response = session.get(
                    feed_url.url,
                    timeout=_feed_request_timeout(deadline),
                    stream=True,
                    allow_redirects=False,
                )
        except requests.Timeout as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_timeout",
                message=f"feed URL request timed out: {_exception_type_name(exc)}",
            )
        except _FeedUrlTimeoutError as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_timeout",
                message=f"feed URL request timed out: {exc}",
            )
        except requests.RequestException as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_failed",
                message=f"feed URL request failed: {_exception_type_name(exc)}",
            )

        status_code = int(getattr(response, "status_code", 0) or 0)
        if 300 <= status_code < 400:
            close_quietly(response)
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_redirect",
                message=f"feed URL redirect was not followed (HTTP {status_code})",
            )
        if status_code >= 400:
            close_quietly(response)
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_failed",
                message=f"feed URL request failed with HTTP {status_code}",
            )

        try:
            root = _parse_feed_response_root(response, deadline=deadline)
        except _FeedFileTooLargeError as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_too_large",
                message=f"feed URL ignored because body is too large: {exc}",
            )
        except _FeedUrlTimeoutError as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_timeout",
                message=f"feed URL response body timed out: {exc}",
            )
        except _UnsafeFeedXmlError as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_unsafe_xml",
                message=f"feed URL ignored because XML is unsafe: {exc}",
            )
        except _FeedUrlFetchError as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_failed",
                message=f"feed URL response body failed: {exc}",
            )
        except ET.ParseError as exc:
            return _feed_rows_single_issue(
                ticker=ticker,
                code="feed_url_failed",
                message=f"failed to parse feed URL response: {exc}",
            )

        return _rows_from_feed_root(
            ticker=ticker,
            root=root,
            empty_issue_code="feed_url_empty",
            empty_issue_message="feed URL ignored because it contains no entries",
            source_url_deadline=deadline,
            resolve_source_url_hostnames=True,
        )
    except _FeedUrlTimeoutError as exc:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_url_timeout",
            message=f"feed URL response item URL timed out: {exc}",
        )
    finally:
        close_quietly(session)


def _rows_from_feed_root(
    *,
    ticker: str,
    root: ET.Element,
    empty_issue_code: str,
    empty_issue_message: str,
    source_url_deadline: float | None,
    resolve_source_url_hostnames: bool,
) -> tuple[list[_FeedSourceRow], list[AiBriefSourceCollectIssue]]:
    root_name = _local_name(root.tag).lower()
    if root_name in {"rss", "rdf"}:
        raw_entries = _rss_items(root)
        feed_kind = "rss"
    elif root_name == "feed":
        raw_entries = _children_named(root, "entry")
        feed_kind = "atom"
    else:
        return _feed_rows_single_issue(
            ticker=ticker,
            code="feed_format_unsupported",
            message=f"unsupported feed root {root.tag!r}",
        )

    rows: list[_FeedSourceRow] = []
    issues: list[AiBriefSourceCollectIssue] = []
    if not raw_entries:
        issues.append(
            AiBriefSourceCollectIssue(
                ticker=ticker,
                code=empty_issue_code,
                message=empty_issue_message,
            )
        )
    for idx, raw_entry in enumerate(raw_entries):
        if feed_kind == "rss":
            parsed, issue = _parse_rss_item(
                ticker,
                idx,
                raw_entry,
                source_url_deadline=source_url_deadline,
                resolve_source_url_hostnames=resolve_source_url_hostnames,
            )
        else:
            parsed, issue = _parse_atom_entry(
                ticker,
                idx,
                raw_entry,
                source_url_deadline=source_url_deadline,
                resolve_source_url_hostnames=resolve_source_url_hostnames,
            )
        if issue is not None:
            issues.append(issue)
            continue
        assert parsed is not None
        rows.append(parsed)
    return rows, issues


def _parse_feed_root(feed_path: Path) -> ET.Element:
    with open(feed_path, "rb") as fp:
        data = fp.read(MAX_FEED_BYTES + 1)
    return _parse_feed_root_data(data)


def _parse_feed_response_root(response: object, *, deadline: float) -> ET.Element:
    data = _read_bounded_feed_response_body(response, deadline=deadline)
    return _parse_feed_root_data(data)


def _parse_feed_root_data(data: bytes) -> ET.Element:
    if len(data) > MAX_FEED_BYTES:
        raise _FeedFileTooLargeError(
            f"{len(data)} bytes exceeds {MAX_FEED_BYTES} byte limit"
        )
    _reject_unsafe_xml_declarations(data)
    return ET.fromstring(data)


def _read_bounded_feed_response_body(response: object, *, deadline: float) -> bytes:
    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        chunks: list[bytes] = []
        total_size = 0
        try:
            for chunk in iter_content(chunk_size=64 * 1024):
                if time.monotonic() > deadline:
                    raise _FeedUrlTimeoutError("feed response body timed out")
                if not chunk:
                    continue
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                total_size += len(chunk)
                if total_size > MAX_FEED_BYTES:
                    raise _FeedFileTooLargeError(
                        f"{total_size} bytes exceeds {MAX_FEED_BYTES} byte limit"
                    )
                chunks.append(bytes(chunk))
        except requests.Timeout as exc:
            raise _FeedUrlTimeoutError("feed response body timed out") from exc
        except requests.RequestException as exc:
            raise _FeedUrlFetchError(_exception_type_name(exc)) from exc
        finally:
            close_quietly(response)
        return b"".join(chunks)

    try:
        content = getattr(response, "content", None)
        if isinstance(content, bytes | bytearray):
            body = bytes(content)
        else:
            text = getattr(response, "text", None)
            if isinstance(text, str):
                body = text.encode("utf-8")
            else:
                raise _FeedUrlFetchError("feed response body is unavailable")
        if len(body) > MAX_FEED_BYTES:
            raise _FeedFileTooLargeError(
                f"{len(body)} bytes exceeds {MAX_FEED_BYTES} byte limit"
            )
        return body
    finally:
        close_quietly(response)


def _remaining_feed_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _FeedUrlTimeoutError("feed URL request timed out")
    return remaining


def _feed_request_timeout(deadline: float) -> tuple[float, float]:
    remaining = _remaining_feed_timeout(deadline)
    return remaining, min(remaining, FEED_RESPONSE_READ_TIMEOUT_SECONDS)


@contextmanager
def _pin_feed_url_dns(
    hostnames: tuple[str, ...],
    addrinfos: tuple[Any, ...],
    *,
    deadline: float | None = None,
) -> Iterator[None]:
    with url_safety.pin_dns(
        hostnames,
        addrinfos,
        lock=SOURCE_DNS_PIN_LOCK,
        deadline=deadline,
        remaining_timeout=_remaining_feed_timeout,
        timeout_error=lambda: _FeedUrlTimeoutError("feed URL DNS pin lock timed out"),
        socket_module=socket,
    ):
        yield


@contextmanager
def _feed_dns_pin_lock(deadline: float | None) -> Iterator[None]:
    with url_safety.dns_pin_lock(
        SOURCE_DNS_PIN_LOCK,
        deadline=deadline,
        remaining_timeout=_remaining_feed_timeout,
        timeout_error=lambda: _FeedUrlTimeoutError("feed URL DNS pin lock timed out"),
    ):
        yield


def _exception_type_name(exc: BaseException) -> str:
    return type(exc).__name__


def _validate_feed_item_url(
    value: object,
    *,
    deadline: float | None = None,
    resolve_hostname: bool = False,
) -> str:
    url = validate_ai_brief_source_url(value)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    port = url_safety.validated_url_port(parsed, field_name="url")
    hostnames = _feed_url_hostname_aliases(hostname)
    if _is_blocked_feed_item_hostname(hostname):
        raise ValueError("url must not target local or private hosts")
    if resolve_hostname:
        hostnames = _feed_url_fetch_hostname_aliases(hostname, field_name="url")
        _resolve_feed_item_addrinfos(hostnames, port, deadline=deadline)
    return url


def _resolve_feed_item_addrinfos(
    hostnames: tuple[str, ...],
    port: int,
    *,
    deadline: float | None,
) -> tuple[Any, ...]:
    if any(url_safety.is_blocked_hostname(hostname) for hostname in hostnames):
        raise ValueError("url must not target local or private hosts")
    resolution_hostname = hostnames[-1] if hostnames else ""
    try:
        with _feed_dns_pin_lock(deadline):
            addrinfos = _getaddrinfo_with_timeout(
                resolution_hostname,
                port,
                timeout=_feed_dns_timeout(deadline),
            )
    except TimeoutError as exc:
        raise _FeedUrlTimeoutError("feed item URL DNS resolution timed out") from exc
    except OSError as exc:
        raise ValueError("url hostname could not be resolved") from exc
    if not addrinfos:
        raise ValueError("url hostname could not be resolved")
    if any(url_safety.is_blocked_addrinfo(addrinfo) for addrinfo in addrinfos):
        raise ValueError("url must not target local or private hosts")
    return tuple(addrinfos)


def _is_blocked_feed_item_hostname(hostname: str) -> bool:
    return any(
        url_safety.is_blocked_hostname(alias)
        for alias in _feed_url_hostname_aliases(hostname)
    )


def _is_blocked_feed_url_hostname(normalized_hostname: str) -> bool:
    return url_safety.is_blocked_hostname(normalized_hostname)


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
    *,
    source_url_deadline: float | None,
    resolve_source_url_hostnames: bool,
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
        source_url_deadline=source_url_deadline,
        resolve_source_url_hostnames=resolve_source_url_hostnames,
    )


def _parse_atom_entry(
    ticker: str,
    idx: int,
    entry: ET.Element,
    *,
    source_url_deadline: float | None,
    resolve_source_url_hostnames: bool,
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
        source_url_deadline=source_url_deadline,
        resolve_source_url_hostnames=resolve_source_url_hostnames,
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
    source_url_deadline: float | None,
    resolve_source_url_hostnames: bool,
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
        url = _validate_feed_item_url(
            url,
            deadline=source_url_deadline,
            resolve_hostname=resolve_source_url_hostnames,
        )
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
                        message="duplicate feed item URL ignored",
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
    "DEFAULT_FEED_TIMEOUT_SECONDS",
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
