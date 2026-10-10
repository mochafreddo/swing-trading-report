"""Collect issuer IR evidence and judge the next confirmed results release."""

import base64
import binascii
import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from decimal import InvalidOperation
from html.parser import HTMLParser
from urllib.parse import unquote, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

from execution_record import DataError

NEWS = "https://www.micron.com/about/press/news"
NY = ZoneInfo("America/New_York")
# Human-reviewed issuer paths; matching a Q4 endpoint alone is not a scope review.
REVIEWED_ARCHIVES = {
    (
        "Repligen",
        "https://investors.repligen.com/press-releases/default.aspx",
        "https://investors.repligen.com/press-releases/news-details/",
    ): {
        "reviewed_on": "2026-10-10",
        "source": "https://investors.repligen.com/financials/quarterly-results/default.aspx",
        "document_routes": {
            "https://investors.repligen.com/files/doc_news/": "https://s205.q4cdn.com/906585988/files/doc_news/",
        },
        "required_text": [
            '"News": {',
            "type: 'news'",
            "tags: ['earnings', 'financials']",
        ],
    }
}


def source_review(source):
    return REVIEWED_ARCHIVES.get(
        tuple(source[key] for key in ("company", "listing_url", "article_prefix")), {}
    )


def public_hosts(source):
    review = source_review(source)
    return tuple(
        {urlparse(source[key]).netloc for key in ("listing_url", "article_prefix")}
        | {
            urlparse(value).netloc
            for value in review.get("document_routes", {}).values()
        }
        | ({urlparse(review["source"]).netloc} if review else set())
    )


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise DataError("invalid_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DataError("timezone_missing")
    return parsed


def document_text(body):
    """Extract complete issuer text; unsupported or oversized documents stay held."""
    if body.startswith("data:application/pdf;base64,"):
        try:
            raw = base64.b64decode(body.split(",", 1)[1], validate=True)
            if not raw.startswith(b"%PDF-"):
                raise DataError("earnings_pdf_invalid")
            with tempfile.TemporaryFile() as output:
                process = subprocess.run(
                    ["pdftotext", "-", "-"],
                    input=raw,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=20,
                    check=False,
                )
                if process.returncode:
                    raise DataError("earnings_pdf_extraction_failed")
                output.seek(0)
                text = output.read(4_000_001).decode("utf-8")
        except OSError, subprocess.TimeoutExpired, UnicodeError, binascii.Error:
            raise DataError("earnings_pdf_extraction_unavailable") from None
        if len(text.encode("utf-8")) > 4_000_000:
            raise DataError("earnings_document_too_large")
    else:
        page = NewsPage()
        page.feed(body)
        text = "".join(page.text)
    if not text.strip():
        raise DataError("earnings_document_empty")
    return text


class NewsPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.articles: list[dict] = []
        self.in_article = False
        self.parts: list[str] = []
        self.next_links = []
        self.anchor = None
        self.metadata = {}
        self.text = []
        self.heading = []
        self.in_heading = False
        self.skip_text = 0
        self.event_calendars = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "cascade-events-render-component":
            self.event_calendars.append(
                (attributes.get("eventssection"), json.loads(attributes["eventsdata"]))
            )
        if tag == "a":
            self.anchor = [attributes.get("href", ""), [], attributes.get("rel", "")]
        if tag == "link" and "next" in attributes.get("rel", "").split():
            self.next_links.append(attributes.get("href", ""))
        if tag == "meta":
            self.metadata[attributes.get("property", attributes.get("name", ""))] = (
                attributes.get("content", "")
            )
        if tag == "h1":
            self.in_heading = True
        if tag in ("p", "div", "br", "h1", "li"):
            self.text.append("\n")
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self.in_article = True
            self.parts = []
        if tag in ("script", "style"):
            self.skip_text += 1

    def handle_data(self, data):
        if self.in_article:
            self.parts.append(data)
        elif not self.skip_text:
            self.text.append(data)
        if self.anchor:
            self.anchor[1].append(data)
        if self.in_heading:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip_text = max(0, self.skip_text - 1)
        if tag == "a" and self.anchor:
            href, label, rel = self.anchor
            self.links.append(href)
            if "next" in rel.split() or "".join(label).strip().lower() in (
                "next",
                "next page",
            ):
                self.next_links.append(href)
            self.anchor = None
        if tag == "h1":
            self.in_heading = False
        if tag in ("p", "div", "li", "h1"):
            self.text.append("\n")
        if tag == "script" and self.in_article:
            self.in_article = False
            try:
                value = json.loads("".join(self.parts))
            except ValueError:
                return

            def visit(value):
                if isinstance(value, dict):
                    if value.get("@type") in ("NewsArticle", "Article", "BlogPosting"):
                        self.articles.append(value)
                    for child in value.values():
                        visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)

            visit(value)


def earnings(
    read: Callable[[str], str], report_day: date, as_of: datetime, source=None
) -> dict:
    """Return IR collection outcomes; replay and execution failures still propagate."""
    source = source or {
        "listing_url": NEWS,
        "article_prefix": "https://investors.micron.com/news/press-release/",
        "company": "Micron Technology",
    }
    try:
        collected = _collect_articles(read, report_day, as_of, source)
        if "articles" not in collected:
            return collected
        result = evaluate_articles(collected["articles"], report_day, as_of, source)
        scope = collected["scope"]
        if scope["status"] == "verified" and not collected["articles"]:
            result = {
                "status": "unconfirmed",
                "source": source["listing_url"],
                "collection_status": "complete",
                "reason": "next_confirmed_earnings_not_found",
            }
        if scope["status"] != "verified" and result["status"] == "confirmed":
            result = result | {
                "status": "unconfirmed",
                "reason": scope["reason"],
            }
        return result | {"scope_status": scope["status"], "scope": scope}
    except DataError as error:
        reason = str(error)
        if reason in ("replay_response_missing", "replay_request_mismatch"):
            raise
    except KeyError, IndexError, TypeError, ValueError, InvalidOperation:
        reason = "invalid_response"
    return {
        "status": "unconfirmed",
        "collection_status": "failed",
        "source": source["listing_url"],
        "reason": reason,
    }


def _collect_articles(
    read: Callable[[str], str], report_day: date, as_of: datetime, source: dict
) -> dict:
    """Return article evidence and its scope, or a terminal collection outcome."""
    pending = [source["listing_url"]]
    visited, links, articles = set(), set(), []
    while pending:
        url = pending.pop(0)
        if url in visited or len(visited) >= 10:
            return {
                "status": "unconfirmed",
                "reason": "earnings_listing_incomplete",
                "collection_status": "incomplete",
            }
        visited.add(url)
        listing = NewsPage()
        body = read(url)
        listing.feed(body)
        if listing.event_calendars:
            if len(listing.event_calendars) != 1 or listing.next_links or pending:
                raise DataError("earnings_event_calendar_incomplete")
            section, payload = listing.event_calendars[0]
            events = payload["Events"]
            if section != "all" or not isinstance(events, list) or not events:
                raise DataError("earnings_event_calendar_incomplete")
            future_earnings = False
            for event in events:
                text = event["EventType"] + " " + event["EventName"]
                if not re.search(r"\b(earnings|results)\b", text, re.I):
                    continue
                # This issuer component labels the otherwise naive timestamp explicitly as UTC.
                raw_date = event["DateTime"]["UTC"]
                if not isinstance(raw_date, str) or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?", raw_date
                ):
                    raise DataError("earnings_event_calendar_invalid_date")
                event_day = (
                    timestamp(raw_date.removesuffix("Z") + "Z").astimezone(NY).date()
                )
                future_earnings |= event_day >= report_day
            # Calendar call dates do not establish the financial results release date.
            return {
                "status": "unconfirmed",
                "source": url,
                "observed_events": len(events),
                "collection_scope": "issuer_event_calendar",
                "reason": "earnings_event_requires_release_announcement"
                if future_earnings
                else "next_confirmed_earnings_not_found",
                "collection_status": "unsupported" if future_earnings else "complete",
            }
        if "q4Api" in body:
            seen_articles = set()
            # TODO: #233 - Full archives can take hundreds of calls; replace with a verified date-bounded feed contract.
            page_number, page_size = 0, 5
            while page_number * page_size < 1000:
                feed = urljoin(
                    url, "/feed/PressRelease.svc/GetPressReleaseList?"
                ) + urlencode(
                    {
                        "LanguageId": 1,
                        "bodyType": 2,
                        "pressReleaseDateFilter": 3,
                        "categoryId": "",
                        "year": -1,
                        "pageNumber": page_number,
                        "pageSize": page_size,
                        "tagList": "",
                        "includeTags": "true",
                        "excludeSelection": 1,
                    }
                )
                try:
                    feed_body = read(feed)
                except DataError as error:
                    if str(error) != "response_too_large" or page_size == 1:
                        raise
                    page_number *= page_size
                    page_size = 1
                    continue
                rows = json.loads(feed_body)["GetPressReleaseListResult"]
                if not isinstance(rows, list):
                    raise DataError("earnings_feed_invalid")
                if not rows:
                    break
                for row in rows:
                    target = urljoin(url, row["LinkToDetailPage"])
                    parsed = urlparse(target)
                    if (
                        parsed.scheme != "https"
                        or parsed.netloc
                        not in {
                            urlparse(source["listing_url"]).netloc,
                            urlparse(source["article_prefix"]).netloc,
                        }
                        or parsed.username
                        or parsed.password
                        or parsed.fragment
                    ):
                        raise DataError("earnings_feed_article_outside_source")
                    if target in seen_articles:
                        raise DataError("earnings_feed_did_not_progress")
                    seen_articles.add(target)
                    article_body = row["Body"]
                    evidence_url = feed
                    if not article_body:
                        evidence_url = target
                        review = source_review(source)
                        if (
                            review
                            and date.fromisoformat(review["reviewed_on"])
                            <= as_of.astimezone(NY).date()
                        ):
                            for original, canonical in review.get(
                                "document_routes", {}
                            ).items():
                                if target.startswith(original):
                                    suffix = unquote(target.removeprefix(original))
                                    if (
                                        parsed.query
                                        or "\\" in suffix
                                        or any(
                                            part in {".", ".."}
                                            for part in suffix.split("/")
                                        )
                                    ):
                                        raise DataError(
                                            "earnings_document_route_invalid"
                                        )
                                    evidence_url = canonical + target.removeprefix(
                                        original
                                    )
                                    break
                        article_body = read(evidence_url)
                    articles.append(
                        (
                            target,
                            evidence_url,
                            {
                                "headline": row["Headline"],
                                "datePublished": row["PressReleaseDate"],
                                "articleBody": document_text(article_body),
                            },
                        )
                    )
                page_number += 1
            else:
                return {
                    "status": "unconfirmed",
                    "reason": "earnings_listing_incomplete",
                    "collection_status": "incomplete",
                }
            count_url = urljoin(
                url, "/feed/PressRelease.svc/GetPressReleaseListCount?"
            ) + urlencode(
                {
                    "LanguageId": 1,
                    "pressReleaseDateFilter": 3,
                    "categoryId": "",
                    "year": -1,
                    "tagList": "",
                    "excludeSelection": 1,
                }
            )
            count = json.loads(read(count_url))["GetPressReleaseListCountResult"]
            if type(count) is not int or count < 0:
                raise DataError("earnings_scope_invalid_count")
            matched = count == len(seen_articles)
            scope = {
                "status": "unverified",
                "kind": "issuer_press_release_archive",
                "count_source": count_url,
                "expected_items": count,
                "observed_items": len(seen_articles),
                "archive_verified": matched,
                "reason": "earnings_scope_unreviewed_source",
            }
            if not matched:
                scope["reason"] = "earnings_scope_count_mismatch"
            else:
                review = source_review(source)
                if (
                    review
                    and date.fromisoformat(review["reviewed_on"])
                    <= as_of.astimezone(NY).date()
                ):
                    scope["source_review"] = review
                    review_body = (
                        body if review["source"] == url else read(review["source"])
                    )
                    if all(text in review_body for text in review["required_text"]):
                        scope["status"] = "verified"
                        del scope["reason"]
                    else:
                        scope["reason"] = "earnings_scope_review_changed"
            return {"articles": articles, "scope": scope}
        for href in listing.links:
            target = urljoin(url, href)
            if (
                target.startswith(source["article_prefix"])
                and target != source["article_prefix"]
                and not urlparse(target).fragment
            ):
                links.add(target)
        for href in dict.fromkeys(listing.next_links):
            target = urljoin(url, href)
            if urlparse(target).netloc != urlparse(source["listing_url"]).netloc:
                return {
                    "status": "unconfirmed",
                    "reason": "earnings_listing_outside_source",
                    "collection_status": "incomplete",
                }
            pending.append(target)
    links.difference_update(visited)
    if len(links) > 100:
        return {
            "status": "unconfirmed",
            "reason": "earnings_article_limit",
            "collection_status": "incomplete",
        }
    for url in sorted(links):
        page = NewsPage()
        page.feed(read(url))
        published_metadata = next(
            (
                page.metadata[key]
                for key in (
                    "article:published_time",
                    "date",
                    "published_time",
                    "pubdate",
                    "publishdate",
                )
                if page.metadata.get(key)
            ),
            None,
        )
        if not page.articles and published_metadata:
            page.articles.append(
                {
                    "headline": page.metadata.get("og:title") or "".join(page.heading),
                    "datePublished": published_metadata,
                    "articleBody": "".join(page.text),
                }
            )
        if not page.articles:
            return {
                "status": "unconfirmed",
                "source": url,
                "reason": "earnings_article_format_unsupported",
                "collection_status": "unsupported",
            }
        articles.extend(
            (
                url,
                url,
                article
                | {
                    "articleBody": article.get("articleBody", "")
                    + "\n"
                    + "".join(page.text)
                },
            )
            for article in page.articles
        )
    return {
        "articles": articles,
        "scope": {
            "status": "unverified",
            "kind": "issuer_link_traversal",
            "reason": "earnings_scope_unverified",
        },
    }


def evaluate_articles(
    articles: list[tuple[str, str, dict]],
    report_day: date,
    as_of: datetime,
    source: dict,
) -> dict:
    """Judge collected issuer articles without reading a URL or clock.

    Each article carries its URL, evidence URL and announcement fields. The
    collector applies its separately verified scope to the resulting judgment.
    """
    dates = []
    changes = []
    if not articles:
        return {
            "status": "unconfirmed",
            "source": source["listing_url"],
            "reason": "no_supported_listing_items",
            "collection_status": "unsupported",
        }
    for url, evidence_url, article in articles:
        headline = article.get("headline") or article["name"]
        text = (
            headline
            + " "
            + article.get("description", "")
            + " "
            + article.get("articleBody", "")
        )
        if not re.search(r"\b(earnings|quarterly|fiscal|results)\b", text, re.I):
            continue
        raw_published = article["datePublished"]
        try:
            published = timestamp(raw_published)
            precision = "timestamp"
        except ValueError:
            try:
                published_day = datetime.strptime(
                    raw_published, "%m/%d/%Y %H:%M:%S"
                ).date()
            except ValueError:
                published_day = datetime.fromisoformat(raw_published).date()
            if published_day >= as_of.astimezone(NY).date():
                return {
                    "status": "unconfirmed",
                    "reason": "publication_time_unverified",
                    "collection_status": "complete",
                }
            published = datetime.combine(published_day, datetime.min.time(), NY)
            precision = "date"
        if published > as_of:
            continue
        if re.search(r"\b(cancelled|canceled|postponed|rescheduled)\b", text, re.I):
            changes.append(
                {
                    "status": "unconfirmed",
                    "source": url,
                    "published_at": published.isoformat(),
                    "reason": "earnings_schedule_changed",
                }
            )
        if not headline.casefold().startswith(source["company"].casefold()):
            continue
        match = re.fullmatch(
            re.escape(source["company"])
            + r" to Report Fiscal .+?Results(?: and Full Fiscal Year \d{4})? on ([A-Za-z]+ \d{1,2}, \d{4})",
            headline,
        )
        event_dates = [match[1]] if match else []
        schedule_text = headline + " " + article.get("description", "")
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if re.search(
                r"\b(date|schedule|earnings|results|announce|report|release)\b",
                sentence,
                re.I,
            ):
                schedule_text += " " + sentence
            release_clause = re.split(
                r"\b(?:and|then)\s+(?:(?:will|to)\s+)?(?:host|hold)\b|\b(?:conference call|webcast)\b",
                sentence,
                flags=re.I,
            )[0]
            release_clause = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", release_clause)
            date_pattern = r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?([A-Z][a-z]+ \d{1,2}, \d{4})\b"
            release_clause = re.sub(
                r"\b(?:ending|ended|ends)\s+on\s+" + date_pattern, "", release_clause
            )
            if re.search(
                r"\b(?:will|to)\s+(?:release|report|announce|publish)\b.{0,120}\b(?:results|earnings)\b|\b(?:results|earnings)\b.{0,80}\bwill be (?:released|reported|announced|published)\b",
                release_clause,
                re.I,
            ):
                event_dates.extend(
                    re.findall(r"\bon\s+" + date_pattern, release_clause)
                )
        parsed_dates = {
            datetime.strptime(value, "%B %d, %Y").date() for value in event_dates
        }
        if not parsed_dates or max(parsed_dates) < report_day:
            continue
        if len(parsed_dates) > 1:
            return {
                "status": "unconfirmed",
                "reason": "earnings_dates_conflict",
                "collection_status": "complete",
            }
        event_day = parsed_dates.pop()
        if re.search(
            r"\b(estimated|expected|expects|tentative|cancelled|canceled|postponed|rescheduled)\b",
            schedule_text,
            re.I,
        ):
            return {
                "status": "unconfirmed",
                "source": url,
                "reason": "uncertain_earnings_announcement",
            }
        dates.append(
            {
                "status": "confirmed",
                "date": event_day.isoformat(),
                "source": url,
                "published_at": published.isoformat()
                if precision == "timestamp"
                else published.date().isoformat(),
                "publication_precision": precision,
                "evidence_url": evidence_url,
                "title": headline,
                "session": "unknown",
                "collection_status": "complete",
            }
        )
    if not dates:
        return {
            "status": "unconfirmed",
            "source": source["listing_url"],
            "reason": "next_confirmed_earnings_not_found",
            "collection_status": "complete",
        }
    if len({item["date"] for item in dates}) > 1:
        return {
            "status": "unconfirmed",
            "reason": "earnings_dates_conflict",
            "collection_status": "complete",
        }
    next_event = min(dates, key=lambda item: item["date"])
    event_publication = datetime.fromisoformat(next_event["published_at"])
    if event_publication.tzinfo is None:
        event_publication = event_publication.replace(tzinfo=NY)
    newer_changes = [
        item for item in changes if timestamp(item["published_at"]) >= event_publication
    ]
    return (
        max(newer_changes, key=lambda item: timestamp(item["published_at"]))
        if newer_changes
        else next_event
    )
