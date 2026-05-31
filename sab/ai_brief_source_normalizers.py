from __future__ import annotations

import datetime as dt
import email.utils
import html
import math
import re
from collections.abc import Callable, Mapping
from typing import Any

_HTML_TAG_RE = re.compile(r"<[^>]*>")


def normalize_finnhub_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    return _normalize_news_rows(
        ticker,
        payload,
        extract=lambda item: (
            _optional_text(item.get("headline")),
            _optional_text(item.get("url")),
            _finnhub_published_at_iso(item.get("datetime")),
        ),
    )


def normalize_polygon_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    return _normalize_news_rows(
        ticker,
        payload,
        extract=lambda item: (
            _optional_text(item.get("title")),
            _optional_text(item.get("article_url")),
            _optional_text(item.get("published_utc")),
        ),
    )


def normalize_alpha_vantage_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    return _normalize_news_rows(
        ticker,
        payload,
        extract=lambda item: (
            _optional_text(item.get("title")),
            _optional_text(item.get("url")),
            _alpha_vantage_news_published_at_iso(item.get("time_published")),
        ),
    )


def normalize_marketaux_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    return _normalize_news_rows(
        ticker,
        payload,
        extract=lambda item: (
            _optional_text(item.get("title")),
            _optional_text(item.get("url")),
            _optional_text(item.get("published_at")),
        ),
    )


def normalize_benzinga_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    return _normalize_news_rows(
        ticker,
        payload,
        extract=lambda item: (
            _optional_text(item.get("title")),
            _optional_text(item.get("url")),
            _benzinga_news_published_at_iso(_benzinga_news_publication_value(item)),
        ),
    )


def normalize_naver_news_rows(
    ticker: str,
    payload: list[object],
) -> list[dict[str, object]]:
    return _normalize_news_rows(
        ticker,
        payload,
        extract=lambda item: (
            _clean_naver_news_text(item.get("title")),
            _naver_news_url(item),
            _naver_news_published_at_iso(item.get("pubDate")),
        ),
    )


def _normalize_news_rows(
    ticker: str,
    payload: list[object],
    *,
    extract: Callable[[Mapping[str, Any]], tuple[str, str, str]],
) -> list[dict[str, object]]:
    """Build normalized source rows, emitting an empty row for non-mapping items."""
    rows: list[dict[str, object]] = []
    for item in payload:
        if isinstance(item, Mapping):
            title, url, published_at = extract(item)
        else:
            title, url, published_at = "", "", ""
        rows.append(
            {
                "ticker": ticker,
                "title": title,
                "url": url,
                "published_at": published_at,
            }
        )
    return rows


def _optional_text(value: object) -> str:
    return str(value or "").strip()


def _finnhub_published_at_iso(value: object) -> str:
    if isinstance(value, bool):
        return ""
    try:
        timestamp = float(str(value).strip())
    except TypeError, ValueError:
        return ""
    if not math.isfinite(timestamp):
        return ""
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).isoformat()


def _alpha_vantage_news_published_at_iso(value: object) -> str:
    text = _optional_text(value)
    if not text:
        return ""
    for date_format in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            parsed = dt.datetime.strptime(text, date_format)
        except ValueError:
            continue
        return parsed.replace(tzinfo=dt.UTC).isoformat()
    return ""


def _benzinga_news_publication_value(item: Mapping[str, Any]) -> object:
    created = item.get("created")
    if created is not None and str(created).strip():
        return created
    return item.get("updated")


def _benzinga_news_published_at_iso(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        timestamp = float(text)
    except ValueError:
        pass
    else:
        if math.isfinite(timestamp):
            return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).isoformat()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(text)
        except TypeError, ValueError:
            return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.isoformat()


def _clean_naver_news_text(value: object) -> str:
    text = _optional_text(value)
    if not text:
        return ""
    return _HTML_TAG_RE.sub("", html.unescape(text)).strip()


def _naver_news_url(item: Mapping[str, Any]) -> str:
    originallink = _optional_text(item.get("originallink"))
    if originallink:
        return originallink
    return _optional_text(item.get("link"))


def _naver_news_published_at_iso(value: object) -> str:
    text = _optional_text(value)
    if not text:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except TypeError, ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.isoformat()


__all__ = [
    "normalize_alpha_vantage_news_rows",
    "normalize_benzinga_news_rows",
    "normalize_finnhub_news_rows",
    "normalize_marketaux_news_rows",
    "normalize_naver_news_rows",
    "normalize_polygon_news_rows",
]
