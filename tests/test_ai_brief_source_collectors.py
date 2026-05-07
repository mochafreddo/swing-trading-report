from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from sab import ai_brief_source_collectors as collectors
from sab.ai_brief_source_collectors import (
    MAX_FEED_BYTES,
    MAX_FEED_CATALOG_BYTES,
    AiBriefSourceCollectorError,
    collect_ai_brief_sources,
    parse_collect_now,
)
from sab.ai_brief_source_eval import evaluate_ai_brief_source_report
from scripts.collect_ai_brief_sources import main as collect_sources_main

FEED_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_brief_source_feeds"
SOURCE_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_brief_sources"
COLLECT_NOW = dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC)


def _feed_fixture(name: str) -> str:
    return (FEED_FIXTURE_DIR / name).as_posix()


def _source_fixture(name: str) -> str:
    return (SOURCE_FIXTURE_DIR / name).as_posix()


def _issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_collects_rss_and_atom_feeds_into_eval_compatible_payload(
    tmp_path: Path,
) -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == [
        "AAPL.NAS",
        "MSFT.NAS",
        "NVDA.NAS",
    ]
    assert result.sources[0]["published_at"] == "2026-05-06T11:30:00+00:00"
    assert result.sources[1]["url"] == "https://news.example.test/msft-cloud-bookings"

    payload = result.to_dict()
    assert payload["type"] == "ai_brief_sources"
    source_report = tmp_path / "collected.sources.json"
    source_report.write_text(json.dumps(payload), encoding="utf-8")
    eval_result = evaluate_ai_brief_source_report(
        entry_report_path=_source_fixture("entry.us.json"),
        source_report_path=source_report.as_posix(),
        now=COLLECT_NOW,
    )

    assert eval_result.status == "PASS"
    assert eval_result.summary["covered_ticker_count"] == 3


def test_collect_filters_requested_tickers() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        tickers={"AAPL.NAS"},
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert [source["ticker"] for source in result.sources] == ["AAPL.NAS"]
    payload = result.to_dict()
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["covered_tickers"] == ["AAPL.NAS"]


def test_collect_reports_missing_requested_ticker() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        tickers={"TSLA.NAS"},
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_catalog_missing_ticker"}


def test_collect_rejects_options_that_exceed_source_report_contract() -> None:
    with pytest.raises(ValueError, match="freshness_hours"):
        collect_ai_brief_sources(
            feed_catalog_path=_feed_fixture("feeds.good.json"),
            now=COLLECT_NOW,
            freshness_hours=73,
        )
    with pytest.raises(ValueError, match="max_sources_per_ticker"):
        collect_ai_brief_sources(
            feed_catalog_path=_feed_fixture("feeds.good.json"),
            now=COLLECT_NOW,
            max_sources_per_ticker=4,
        )


def test_collect_respects_custom_freshness_hours() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.good.json"),
        now=COLLECT_NOW,
        freshness_hours=0.25,
    )

    assert result.status == "WARN"
    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_stale"}


def test_collect_reports_invalid_stale_duplicate_and_cap_issues() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.issues.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "WARN"
    assert [source["url"] for source in result.sources] == [
        "https://news.example.test/aapl-newest",
        "https://news.example.test/aapl-second",
        "https://news.example.test/aapl-third",
    ]
    assert _issue_codes(result) == {
        "feed_catalog_invalid_row",
        "feed_file_failed",
        "feed_item_cap_exceeded",
        "feed_item_duplicate_url",
        "feed_item_invalid_row",
        "feed_item_stale",
    }


def test_collect_accepts_rdf_dc_date() -> None:
    result = collect_ai_brief_sources(
        feed_catalog_path=_feed_fixture("feeds.rdf.json"),
        now=COLLECT_NOW,
    )

    assert result.status == "PASS"
    assert result.sources == [
        {
            "ticker": "META.NAS",
            "title": "Meta ad spending outlook improves",
            "url": "https://news.example.test/meta-ad-spend",
            "published_at": "2026-05-06T08:45:00+00:00",
        }
    ]


def test_collect_rejects_doctype_entity_feed_before_xml_parse(
    tmp_path: Path,
) -> None:
    feed = tmp_path / "unsafe.rss"
    feed.write_bytes(
        """<?xml version="1.0" encoding="UTF-16"?>
<!DOCTYPE rss [<!ENTITY unsafe "expanded">]>
<rss version="2.0">
  <channel>
    <item>
      <title>&unsafe;</title>
      <link>https://news.example.test/unsafe</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-16"),
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "unsafe.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_file_unsafe_xml"}


def test_collect_rejects_feed_file_over_size_limit(tmp_path: Path) -> None:
    feed = tmp_path / "oversized.rss"
    feed.write_bytes(b"x" * (MAX_FEED_BYTES + 1))
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "oversized.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_file_too_large"}


def test_collect_rejects_feed_catalog_over_size_limit(tmp_path: Path) -> None:
    catalog = tmp_path / "oversized-feeds.json"
    catalog.write_bytes(b"x" * (MAX_FEED_CATALOG_BYTES + 1))

    with pytest.raises(AiBriefSourceCollectorError, match="feed catalog is too large"):
        collect_ai_brief_sources(
            feed_catalog_path=catalog.as_posix(),
            now=COLLECT_NOW,
        )


def test_parse_feed_root_reads_only_size_limit_plus_sentinel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    feed = tmp_path / "oversized.rss"
    read_sizes: list[int] = []

    class _BoundedRead:
        def __enter__(self) -> _BoundedRead:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            read_sizes.append(size)
            return b"x" * size

    monkeypatch.setattr(
        collectors,
        "open",
        lambda *_args, **_kwargs: _BoundedRead(),
        raising=False,
    )

    with pytest.raises(collectors._FeedFileTooLargeError):
        collectors._parse_feed_root(feed)

    assert read_sizes == [MAX_FEED_BYTES + 1]


def test_collect_rejects_feed_path_outside_catalog_dir(tmp_path: Path) -> None:
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "../outside.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_catalog_invalid_row"}
    assert "within the feed catalog directory" in result.issues[0].message


def test_collect_does_not_preserve_absolute_feed_paths_in_issues(
    tmp_path: Path,
) -> None:
    feed = tmp_path / "bad.xml"
    feed.write_text("<rss><channel><item>", encoding="utf-8")
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "bad.xml"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_file_failed"}
    assert "bad.xml" in result.issues[0].message
    assert tmp_path.as_posix() not in result.issues[0].message


def test_collect_rejects_invalid_urls_and_future_dates(tmp_path: Path) -> None:
    feed = tmp_path / "bad-source.rss"
    feed.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Unsupported URL scheme</title>
      <link>file:///private/news.html</link>
      <pubDate>Wed, 06 May 2026 11:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Credential URL</title>
      <link>https://token@example.test/secret</link>
      <pubDate>Wed, 06 May 2026 11:20:00 GMT</pubDate>
    </item>
    <item>
      <title>Future source</title>
      <link>https://news.example.test/future</link>
      <pubDate>Wed, 06 May 2026 12:16:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    catalog = tmp_path / "feeds.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "sab.ai_brief_source_feed_catalog.v1",
                "feeds": [{"ticker": "AAPL.NAS", "path": "bad-source.rss"}],
            }
        ),
        encoding="utf-8",
    )

    result = collect_ai_brief_sources(
        feed_catalog_path=catalog.as_posix(),
        now=COLLECT_NOW,
    )

    assert result.sources == []
    assert _issue_codes(result) == {"feed_item_future", "feed_item_invalid_row"}
    assert any("userinfo" in issue.message for issue in result.issues)


def test_collect_script_outputs_json(capsys) -> None:
    exit_code = collect_sources_main(
        [
            "--feed-catalog",
            _feed_fixture("feeds.good.json"),
            "--ticker",
            "MSFT.NAS",
            "--now",
            "2026-05-06T12:00:00+00:00",
            "--pretty",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["schema"] == "sab.ai_brief_sources.v1"
    assert payload["type"] == "ai_brief_sources"
    assert payload["summary"]["covered_tickers"] == ["MSFT.NAS"]
    assert payload["sources"][0]["title"] == "Microsoft cloud bookings accelerate"


def test_collect_script_creates_output_parent(tmp_path: Path) -> None:
    output_path = tmp_path / "reports" / "collected.sources.json"

    exit_code = collect_sources_main(
        [
            "--feed-catalog",
            _feed_fixture("feeds.good.json"),
            "--ticker",
            "AAPL.NAS",
            "--output",
            output_path.as_posix(),
            "--now",
            "2026-05-06T12:00:00+00:00",
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["type"] == "ai_brief_sources"
    assert payload["summary"]["covered_tickers"] == ["AAPL.NAS"]


def test_parse_collect_now_requires_utc_offset() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        parse_collect_now("2026-05-06T12:00:00")
