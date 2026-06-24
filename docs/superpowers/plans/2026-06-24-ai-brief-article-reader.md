# AI Brief Article Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Lightpanda article reader that enriches AI Brief source rows and lets recommendation evaluation report metadata/accessed/verified source-backed tiers.

**Architecture:** Keep the existing source provider chain as the discovery layer, then enrich selected source rows with optional `article_read` metadata before model candidate attachment. Add deterministic local verification in a new `sab.article_reader` module, validate the optional artifact shape in the report contract, and extend the evaluator summary without making article access a hard scheduled dependency.

**Tech Stack:** Python 3.14, `uv`, pytest, existing `sab` package, `lightpanda fetch` via subprocess, existing AI Brief source/report/evaluator contracts.

---

## File Structure

- Create `sab/article_reader.py`: owns article reader settings, Lightpanda subprocess adapter, bounded excerpt extraction, deterministic ticker/company matching, source-row enrichment, and source-read summary metrics.
- Create `tests/test_article_reader.py`: unit tests for settings normalization, excerpt extraction, verification, subprocess result mapping, cap behavior, and source-row enrichment.
- Modify `sab/ai_brief.py`: normalize article reader config, call article enrichment after `load_ai_brief_source_chain()`, add article read issues to `source_issues`, and include article summary counts.
- Modify `sab/report/ai_brief_report.py`: validate optional `sources[].article_read` metadata for recommendations and watch candidates.
- Modify `sab/ai_brief_eval.py`: compute recommendation source backing tiers and summary counts.
- Modify `sab/__main__.py`: add manual CLI flags and pass them to `run_ai_brief()`.
- Modify tests in `tests/test_ai_brief.py`, `tests/test_ai_brief_eval.py`, `tests/test_cli_dispatch.py`, and `tests/test_ai_brief_report.py` or the closest existing report validation test section.
- Optional docs update after behavior is implemented: `docs/config-reference.md` if it already lists AI Brief env vars.

### Task 1: Article Reader Core Types And Local Verification

**Files:**
- Create: `sab/article_reader.py`
- Test: `tests/test_article_reader.py`

- [ ] **Step 1: Write failing tests for result serialization, excerpt bounds, and verification tiers**

Add `tests/test_article_reader.py`:

```python
from __future__ import annotations

import datetime as dt

from sab.article_reader import (
    ArticleReadResult,
    ArticleReaderSettings,
    article_read_summary,
    extract_bounded_excerpt,
    verify_article_text,
)

NOW = dt.datetime(2026, 6, 24, 9, 35, tzinfo=dt.UTC)


def test_article_read_result_serializes_without_empty_optional_values() -> None:
    result = ArticleReadResult(
        status="verified",
        tier="article_verified",
        checked_at=NOW,
        reader="lightpanda",
        excerpt="Apple expanded AI infrastructure capacity.",
        matched_terms=("AAPL", "Apple"),
        issue_code=None,
    )

    assert result.to_dict() == {
        "status": "verified",
        "tier": "article_verified",
        "checked_at": "2026-06-24T09:35:00+00:00",
        "reader": "lightpanda",
        "excerpt": "Apple expanded AI infrastructure capacity.",
        "matched_terms": ["AAPL", "Apple"],
        "issue_code": None,
    }


def test_extract_bounded_excerpt_collapses_whitespace_and_bounds_length() -> None:
    text = "  Apple\\n\\nexpanded   AI capacity for its device roadmap.  "

    assert extract_bounded_excerpt(text, max_chars=32) == (
        "Apple expanded AI capacity for..."
    )


def test_verify_article_text_returns_verified_for_ticker_or_company_match() -> None:
    result = verify_article_text(
        "Apple said AAPL infrastructure spending increased.",
        ticker="AAPL.NAS",
        company_terms=("Apple",),
    )

    assert result.tier == "article_verified"
    assert result.matched_terms == ("AAPL", "Apple")


def test_verify_article_text_returns_accessed_when_no_terms_match() -> None:
    result = verify_article_text(
        "The market opened higher after broad technology gains.",
        ticker="AAPL.NAS",
        company_terms=("Apple",),
    )

    assert result.tier == "article_accessed"
    assert result.matched_terms == ()


def test_article_read_summary_counts_statuses_and_tiers() -> None:
    rows = {
        "AAPL.NAS": [
            {
                "title": "AAPL source",
                "url": "https://news.example/aapl",
                "published_at": "2026-06-24T09:00:00+00:00",
                "article_read": {
                    "status": "verified",
                    "tier": "article_verified",
                    "checked_at": "2026-06-24T09:35:00+00:00",
                    "reader": "lightpanda",
                    "excerpt": "Apple expanded capacity.",
                    "matched_terms": ["AAPL", "Apple"],
                    "issue_code": None,
                },
            }
        ],
        "MSFT.NAS": [
            {
                "title": "MSFT source",
                "url": "https://news.example/msft",
                "published_at": "2026-06-24T09:00:00+00:00",
                "article_read": {
                    "status": "blocked",
                    "tier": "metadata_backed",
                    "checked_at": "2026-06-24T09:35:00+00:00",
                    "reader": "lightpanda",
                    "excerpt": "",
                    "matched_terms": [],
                    "issue_code": "article_access_blocked",
                },
            }
        ],
    }

    assert article_read_summary(rows) == {
        "article_read_attempted_count": 2,
        "article_accessed_count": 0,
        "article_verified_count": 1,
        "article_read_issue_count": 1,
    }


def test_article_reader_settings_disabled_by_default() -> None:
    settings = ArticleReaderSettings()

    assert settings.reader == "none"
    assert settings.enabled is False
```

- [ ] **Step 2: Run tests and confirm they fail because module is missing**

Run: `just test tests/test_article_reader.py`

Expected: FAIL with `ModuleNotFoundError: No module named 'sab.article_reader'`.

- [ ] **Step 3: Implement minimal core types and deterministic verification**

Create `sab/article_reader.py`:

```python
from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

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
    collapsed = re.sub(r"\\s+", " ", text).strip()
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
        if normalized and normalized not in matched and _contains_term(text, normalized):
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
```

- [ ] **Step 4: Run tests and fix only Task 1 failures**

Run: `just test tests/test_article_reader.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add sab/article_reader.py tests/test_article_reader.py
git commit -m "feat(ai-brief): 기사 읽기 검증 타입 추가"
```

### Task 2: Lightpanda Adapter And Source Row Enrichment

**Files:**
- Modify: `sab/article_reader.py`
- Test: `tests/test_article_reader.py`

- [ ] **Step 1: Add failing tests for Lightpanda mapping and enrichment caps**

Append tests:

```python
from sab.article_reader import enrich_sources_with_article_reads


class _FakeLightpandaRunner:
    def __init__(self, responses: dict[str, tuple[int, str, str]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout_seconds: float) -> tuple[int, str, str]:
        self.calls.append((url, timeout_seconds))
        return self.responses[url]


def test_enrich_sources_marks_verified_from_lightpanda_markdown() -> None:
    sources = {
        "AAPL.NAS": [
            {
                "title": "Apple source",
                "url": "https://news.example/aapl",
                "published_at": "2026-06-24T09:00:00+00:00",
            }
        ]
    }
    runner = _FakeLightpandaRunner(
        {"https://news.example/aapl": (0, "# Apple\\nAAPL expanded AI capacity.", "")}
    )

    enriched, issues = enrich_sources_with_article_reads(
        sources,
        ticker_names={"AAPL.NAS": "Apple"},
        settings=ArticleReaderSettings(reader="lightpanda", max_urls=8),
        now=NOW,
        lightpanda_runner=runner,
    )

    assert issues == []
    assert enriched["AAPL.NAS"][0]["article_read"]["status"] == "verified"
    assert enriched["AAPL.NAS"][0]["article_read"]["tier"] == "article_verified"
    assert runner.calls == [("https://news.example/aapl", 8.0)]


def test_enrich_sources_preserves_rows_and_records_blocked_issue() -> None:
    sources = {
        "MSFT.NAS": [
            {
                "title": "MSFT source",
                "url": "https://news.example/msft",
                "published_at": "2026-06-24T09:00:00+00:00",
            }
        ]
    }
    runner = _FakeLightpandaRunner(
        {"https://news.example/msft": (1, "", "HTTP 403 forbidden")}
    )

    enriched, issues = enrich_sources_with_article_reads(
        sources,
        ticker_names={"MSFT.NAS": "Microsoft"},
        settings=ArticleReaderSettings(reader="lightpanda", max_urls=8),
        now=NOW,
        lightpanda_runner=runner,
    )

    assert enriched["MSFT.NAS"][0]["url"] == "https://news.example/msft"
    assert enriched["MSFT.NAS"][0]["article_read"]["status"] == "blocked"
    assert enriched["MSFT.NAS"][0]["article_read"]["issue_code"] == (
        "article_access_blocked"
    )
    assert issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "article_access_blocked",
            "severity": "WARN",
            "message": "article reader could not access source URL",
        }
    ]


def test_enrich_sources_marks_remaining_rows_not_attempted_after_cap() -> None:
    sources = {
        "AAPL.NAS": [
            {
                "title": "AAPL source 1",
                "url": "https://news.example/aapl-1",
                "published_at": "2026-06-24T09:00:00+00:00",
            },
            {
                "title": "AAPL source 2",
                "url": "https://news.example/aapl-2",
                "published_at": "2026-06-24T09:00:00+00:00",
            },
        ]
    }
    runner = _FakeLightpandaRunner(
        {"https://news.example/aapl-1": (0, "Apple mentions AAPL.", "")}
    )

    enriched, issues = enrich_sources_with_article_reads(
        sources,
        ticker_names={"AAPL.NAS": "Apple"},
        settings=ArticleReaderSettings(reader="lightpanda", max_urls=1),
        now=NOW,
        lightpanda_runner=runner,
    )

    assert issues == []
    assert enriched["AAPL.NAS"][0]["article_read"]["status"] == "verified"
    assert enriched["AAPL.NAS"][1]["article_read"]["status"] == "not_attempted"
    assert runner.calls == [("https://news.example/aapl-1", 8.0)]
```

- [ ] **Step 2: Run tests and confirm missing functions fail**

Run: `just test tests/test_article_reader.py`

Expected: FAIL with import or attribute errors for enrichment functions.

- [ ] **Step 3: Implement Lightpanda subprocess adapter and enrichment**

Extend `sab/article_reader.py` with:

```python
import subprocess

from .ai_brief_source_report import source_issue

type LightpandaRunner = callable


def _default_lightpanda_runner(url: str, timeout_seconds: float) -> tuple[int, str, str]:
    completed = subprocess.run(
        [
            "lightpanda",
            "fetch",
            url,
            "--dump",
            "markdown",
            "--block-private-networks",
            "--disable-subframes",
            "--disable-workers",
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


def _issue_code_for_failure(returncode: int, stderr: str) -> tuple[ArticleReadStatus, str]:
    text = stderr.lower()
    if "403" in text or "429" in text or "forbidden" in text or "rate" in text:
        return "blocked", "article_access_blocked"
    if "captcha" in text or "challenge" in text:
        return "blocked", "article_bot_challenge"
    if "paywall" in text or "login" in text:
        return "blocked", "article_paywalled"
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


def _read_one_source(
    *,
    ticker: str,
    source: Mapping[str, object],
    company_terms: Sequence[str],
    settings: ArticleReaderSettings,
    now: dt.datetime,
    lightpanda_runner,
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
        return result, source_issue(
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
        return result, source_issue(
            ticker=ticker,
            code="article_reader_failed",
            message="article reader failed before reading source URL",
        )
    if returncode != 0:
        status, issue_code = _issue_code_for_failure(returncode, stderr)
        result = _metadata_only_result(
            status=status,
            checked_at=now,
            reader=settings.reader,
            issue_code=issue_code,
        )
        return result, source_issue(
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
        return result, source_issue(
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
    lightpanda_runner=_default_lightpanda_runner,
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
            if not settings.enabled:
                row["article_read"] = _metadata_only_result(
                    status="not_attempted",
                    checked_at=now,
                    reader=settings.reader,
                ).to_dict()
            elif attempted >= settings.max_urls:
                row["article_read"] = _metadata_only_result(
                    status="not_attempted",
                    checked_at=now,
                    reader=settings.reader,
                ).to_dict()
            else:
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
```

Adjust typing while implementing: use `Callable[[str, float], tuple[int, str, str]]`
instead of the sketch's `type LightpandaRunner = callable`.

- [ ] **Step 4: Run focused tests**

Run: `just test tests/test_article_reader.py`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add sab/article_reader.py tests/test_article_reader.py
git commit -m "feat(ai-brief): 기사 원문 읽기 보강 추가"
```

### Task 3: AI Brief Pipeline Configuration And Enrichment Hook

**Files:**
- Modify: `sab/ai_brief.py`
- Modify: `sab/__main__.py`
- Test: `tests/test_ai_brief.py`
- Test: `tests/test_cli_dispatch.py`

- [ ] **Step 1: Add failing tests for opt-in config and CLI plumbing**

Add or extend tests near existing AI Brief timeout/source provider tests:

```python
def test_run_ai_brief_enriches_sources_with_article_reader(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured_settings: dict[str, object] = {}

    def fake_enrich(sources_by_ticker, *, ticker_names, settings, now):
        captured_settings["settings"] = settings
        captured_settings["ticker_names"] = dict(ticker_names)
        enriched = {
            ticker: [
                {
                    **source,
                    "article_read": {
                        "status": "verified",
                        "tier": "article_verified",
                        "checked_at": now.isoformat(),
                        "reader": "lightpanda",
                        "excerpt": "Apple mentions AAPL.",
                        "matched_terms": ["AAPL", "Apple"],
                        "issue_code": None,
                    },
                }
                for source in sources
            ]
            for ticker, sources in sources_by_ticker.items()
        }
        return enriched, []

    monkeypatch.setattr("sab.ai_brief.enrich_sources_with_article_reads", fake_enrich)
    # Use the existing helper pattern in tests/test_ai_brief.py to create entry,
    # buy, and local source reports with an AAPL.NAS source and name "Apple".
    # Then call run_ai_brief(..., article_reader="lightpanda", report_path_callback=...).
    # Assert generated recommendations[0].sources[0].article_read.tier == "article_verified".
```

Add CLI dispatch test:

```python
def test_cli_ai_brief_passes_article_reader_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_ai_brief(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("sab.__main__.run_ai_brief", fake_run_ai_brief)

    exit_code = main(
        [
            "ai-brief",
            "--entry-report",
            "reports/entry.json",
            "--article-reader",
            "lightpanda",
            "--article-reader-max-urls",
            "3",
            "--article-reader-timeout-seconds",
            "4.5",
            "--article-reader-max-excerpt-chars",
            "900",
        ]
    )

    assert exit_code == 0
    assert captured["article_reader"] == "lightpanda"
    assert captured["article_reader_max_urls"] == 3
    assert captured["article_reader_timeout_seconds"] == 4.5
    assert captured["article_reader_max_excerpt_chars"] == 900
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `just test tests/test_cli_dispatch.py tests/test_ai_brief.py -k article_reader`

Expected: FAIL because `run_ai_brief` and CLI do not accept article reader options.

- [ ] **Step 3: Add normalization and hook to `run_ai_brief()`**

Modify `sab/ai_brief.py`:

```python
from .article_reader import (
    ArticleReaderSettings,
    article_read_summary,
    enrich_sources_with_article_reads,
)


def _normalize_article_reader(value: str | None) -> str:
    reader = str(value or os.getenv("AI_BRIEF_ARTICLE_READER") or "none").strip().lower()
    if reader not in {"none", "lightpanda"}:
        raise ValueError("article_reader must be one of ['lightpanda', 'none']")
    return reader


def _normalize_article_reader_int(
    value: int | None,
    *,
    env_name: str,
    default: int,
    field_name: str,
) -> int:
    if value is None:
        raw = os.getenv(env_name)
        value = int(raw) if raw and raw.strip() else default
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _normalize_article_reader_float(
    value: float | None,
    *,
    env_name: str,
    default: float,
    field_name: str,
) -> float:
    if value is None:
        raw = os.getenv(env_name)
        value = float(raw) if raw and raw.strip() else default
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return float(value)


def _article_reader_settings(
    *,
    article_reader: str | None,
    article_reader_max_urls: int | None,
    article_reader_timeout_seconds: float | None,
    article_reader_max_excerpt_chars: int | None,
) -> ArticleReaderSettings:
    return ArticleReaderSettings(
        reader=_normalize_article_reader(article_reader),
        max_urls=_normalize_article_reader_int(
            article_reader_max_urls,
            env_name="AI_BRIEF_ARTICLE_READER_MAX_URLS",
            default=8,
            field_name="article_reader_max_urls",
        ),
        timeout_seconds=_normalize_article_reader_float(
            article_reader_timeout_seconds,
            env_name="AI_BRIEF_ARTICLE_READER_TIMEOUT_SECONDS",
            default=8.0,
            field_name="article_reader_timeout_seconds",
        ),
        max_excerpt_chars=_normalize_article_reader_int(
            article_reader_max_excerpt_chars,
            env_name="AI_BRIEF_ARTICLE_READER_MAX_EXCERPT_CHARS",
            default=1200,
            field_name="article_reader_max_excerpt_chars",
        ),
    )
```

Add parameters to `run_ai_brief()`:

```python
article_reader: str | None = None,
article_reader_max_urls: int | None = None,
article_reader_timeout_seconds: float | None = None,
article_reader_max_excerpt_chars: int | None = None,
```

After `source_chain_result` and before `_attach_candidate_sources()`:

```python
article_settings = _article_reader_settings(...)
article_now = dt.datetime.now().astimezone()
sources_by_ticker, article_issues = enrich_sources_with_article_reads(
    source_chain_result.sources_by_ticker,
    ticker_names=ticker_names,
    settings=article_settings,
    now=article_now,
)
preselected_candidates = _attach_candidate_sources(preselected_candidates, sources_by_ticker)
watch_candidates = _attach_candidate_sources(watch_candidates, sources_by_ticker)
source_provider_issues = [*source_chain_result.source_issues, *article_issues]
article_summary = article_read_summary(sources_by_ticker)
```

Pass `article_summary` into `_build_summary()` by adding optional fields with default
zero counts.

- [ ] **Step 4: Add CLI options**

Modify `sab/__main__.py` AI Brief parser:

```python
ai_brief.add_argument(
    "--article-reader",
    choices=["none", "lightpanda"],
    default=None,
    help="Optional article reader for source URL content verification",
)
ai_brief.add_argument("--article-reader-max-urls", type=int, default=None)
ai_brief.add_argument("--article-reader-timeout-seconds", type=float, default=None)
ai_brief.add_argument("--article-reader-max-excerpt-chars", type=int, default=None)
```

Pass the four values to `run_ai_brief()`.

- [ ] **Step 5: Run focused tests**

Run: `just test tests/test_cli_dispatch.py tests/test_ai_brief.py -k article_reader`

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add sab/ai_brief.py sab/__main__.py tests/test_ai_brief.py tests/test_cli_dispatch.py
git commit -m "feat(ai-brief): 기사 읽기 설정을 파이프라인에 연결"
```

### Task 4: Artifact Validation For Optional Article Read Metadata

**Files:**
- Modify: `sab/report/ai_brief_report.py`
- Test: existing AI Brief report validation tests, likely `tests/test_ai_brief_report.py`

- [ ] **Step 1: Add failing validation tests**

Add tests:

```python
def test_ai_brief_report_accepts_source_article_read_metadata(tmp_path: Path) -> None:
    artifact = _valid_ai_brief_artifact()
    artifact["recommendations"][0]["sources"][0]["article_read"] = {
        "status": "verified",
        "tier": "article_verified",
        "checked_at": "2026-05-06T12:00:00+00:00",
        "reader": "lightpanda",
        "excerpt": "Apple mentions AAPL.",
        "matched_terms": ["AAPL", "Apple"],
        "issue_code": None,
    }

    validate_ai_brief_artifact(artifact, now=EVAL_NOW)


def test_ai_brief_report_rejects_invalid_article_read_tier() -> None:
    artifact = _valid_ai_brief_artifact()
    artifact["recommendations"][0]["sources"][0]["article_read"] = {
        "status": "verified",
        "tier": "unknown",
        "checked_at": "2026-05-06T12:00:00+00:00",
        "reader": "lightpanda",
        "excerpt": "Apple mentions AAPL.",
        "matched_terms": ["AAPL"],
        "issue_code": None,
    }

    with pytest.raises(AiBriefValidationError, match="article_read.tier"):
        validate_ai_brief_artifact(artifact, now=EVAL_NOW)
```

Use existing helper names in the file instead of creating duplicate fixtures.

- [ ] **Step 2: Run report tests and confirm failure**

Run: `just test tests/test_ai_brief_report.py -k article_read`

Expected: FAIL because validator ignores or rejects unknown nested shape depending on current helpers.

- [ ] **Step 3: Validate optional `article_read`**

Modify `_validate_source_rows()` to call a helper:

```python
_ALLOWED_ARTICLE_READ_STATUSES = frozenset(
    {"not_attempted", "metadata_only", "accessed", "verified", "blocked", "failed"}
)
_ALLOWED_SOURCE_BACKING_TIERS = frozenset(
    {"metadata_backed", "article_accessed", "article_verified"}
)
_ALLOWED_ARTICLE_READERS = frozenset({"none", "lightpanda"})


def _validate_article_read(value: object, *, field_name: str) -> None:
    if value is None:
        return
    row = _require_mapping(value, field_name=field_name)
    status = str(row.get("status") or "").strip()
    if status not in _ALLOWED_ARTICLE_READ_STATUSES:
        raise AiBriefValidationError(
            f"{field_name}.status must be one of {sorted(_ALLOWED_ARTICLE_READ_STATUSES)}"
        )
    tier = str(row.get("tier") or "").strip()
    if tier not in _ALLOWED_SOURCE_BACKING_TIERS:
        raise AiBriefValidationError(
            f"{field_name}.tier must be one of {sorted(_ALLOWED_SOURCE_BACKING_TIERS)}"
        )
    _parse_offset_datetime(row.get("checked_at"), field_name=f"{field_name}.checked_at")
    reader = str(row.get("reader") or "").strip()
    if reader not in _ALLOWED_ARTICLE_READERS:
        raise AiBriefValidationError(
            f"{field_name}.reader must be one of {sorted(_ALLOWED_ARTICLE_READERS)}"
        )
    excerpt = row.get("excerpt")
    if excerpt is not None and not isinstance(excerpt, str):
        raise AiBriefValidationError(f"{field_name}.excerpt must be a string")
    matched_terms = _require_list(row.get("matched_terms"), field_name=f"{field_name}.matched_terms")
    for idx, raw_term in enumerate(matched_terms):
        if not isinstance(raw_term, str):
            raise AiBriefValidationError(
                f"{field_name}.matched_terms[{idx}] must be a string"
            )
    issue_code = row.get("issue_code")
    if issue_code is not None and not str(issue_code).strip():
        raise AiBriefValidationError(f"{field_name}.issue_code must not be blank")
```

Inside `_validate_source_rows()`:

```python
if "article_read" in source:
    _validate_article_read(
        source.get("article_read"),
        field_name=f"{field_name}[{source_index}].article_read",
    )
```

- [ ] **Step 4: Run focused tests**

Run: `just test tests/test_ai_brief_report.py -k article_read`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add sab/report/ai_brief_report.py tests/test_ai_brief_report.py
git commit -m "feat(ai-brief): 기사 검증 메타데이터 검증 추가"
```

### Task 5: Evaluator Source-Backing Tiers

**Files:**
- Modify: `sab/ai_brief_eval.py`
- Test: `tests/test_ai_brief_eval.py`

- [ ] **Step 1: Add failing evaluator tests**

Add tests:

```python
def _with_article_read(
    recommendation: dict[str, object],
    *,
    status: str,
    tier: str,
) -> dict[str, object]:
    updated = dict(recommendation)
    sources = _copy_mapping_rows(updated["sources"])
    sources[0] = {
        **sources[0],
        "article_read": {
            "status": status,
            "tier": tier,
            "checked_at": "2026-05-06T12:00:00+00:00",
            "reader": "lightpanda",
            "excerpt": "Apple mentions AAPL.",
            "matched_terms": ["AAPL"],
            "issue_code": None,
        },
    }
    updated["sources"] = sources
    return updated


def test_ai_brief_eval_reports_article_verified_ratio(tmp_path: Path) -> None:
    payload = _load_good_ai_brief()
    recommendations = _copy_mapping_rows(payload["recommendations"])
    recommendations[0] = _with_article_read(
        recommendations[0],
        status="verified",
        tier="article_verified",
    )
    payload["recommendations"] = recommendations
    report_path = _write_payload(tmp_path, "verified.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "PASS"
    assert result.summary["source_backing_tiers"] == {
        "metadata_backed": 2,
        "article_accessed": 0,
        "article_verified": 1,
    }
    assert result.summary["article_verified_ratio"] == pytest.approx(1 / 3)


def test_ai_brief_eval_warns_when_metadata_backed_lacks_verified_article(
    tmp_path: Path,
) -> None:
    payload = _load_good_ai_brief()
    report_path = _write_payload(tmp_path, "metadata-only.ai-brief.json", payload)

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=_fixture("entry.us.json"),
        ai_brief_report_path=report_path,
        now=EVAL_NOW,
    )

    assert result.status == "WARN"
    assert "article_verified_ratio_below_recommendation_count" in _issue_codes(result)
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `just test tests/test_ai_brief_eval.py -k article`

Expected: FAIL because tier summary and warning do not exist.

- [ ] **Step 3: Implement tier calculation**

Add helpers to `sab/ai_brief_eval.py`:

```python
_SOURCE_BACKING_TIER_ORDER = {
    "metadata_backed": 0,
    "article_accessed": 1,
    "article_verified": 2,
}


def _source_backing_tier(recommendation: Mapping[str, Any]) -> str | None:
    sources = recommendation.get("sources")
    if not isinstance(sources, list) or not sources:
        return None
    best = "metadata_backed"
    for raw_source in sources:
        if not isinstance(raw_source, Mapping):
            continue
        raw_read = raw_source.get("article_read")
        if not isinstance(raw_read, Mapping):
            continue
        tier = str(raw_read.get("tier") or "").strip()
        if tier in _SOURCE_BACKING_TIER_ORDER and (
            _SOURCE_BACKING_TIER_ORDER[tier] > _SOURCE_BACKING_TIER_ORDER[best]
        ):
            best = tier
    return best
```

Replace source-backed counting loop with tier-aware counting:

```python
source_backing_tiers = {
    "metadata_backed": 0,
    "article_accessed": 0,
    "article_verified": 0,
}
source_backed_count = 0
for recommendation in recommendations:
    tier = _source_backing_tier(recommendation)
    if tier is not None:
        source_backed_count += 1
        source_backing_tiers[tier] += 1
        continue
    # keep existing unbacked confidence/source issue logic
```

After ratio check:

```python
article_verified_count = source_backing_tiers["article_verified"]
article_verified_ratio = _source_backed_ratio(
    recommendation_count=len(recommendations),
    source_backed_count=article_verified_count,
)
if recommendations and article_verified_count < len(recommendations):
    issues.append(
        AiBriefRecommendationEvalIssue(
            code="article_verified_ratio_below_recommendation_count",
            severity="WARN",
            message=(
                "not every source-backed recommendation has an article-verified source"
            ),
        )
    )
```

Add to summary:

```python
"source_backing_tiers": source_backing_tiers,
"article_verified_recommendation_count": article_verified_count,
"article_verified_ratio": article_verified_ratio,
```

- [ ] **Step 4: Run focused tests**

Run: `just test tests/test_ai_brief_eval.py -k article`

Expected: PASS.

- [ ] **Step 5: Reconcile existing tests**

Run: `just test tests/test_ai_brief_eval.py`

Expected: PASS. If existing `test_ai_brief_eval_passes_source_backed_artifact`
expects `PASS`, update that expectation only if the new policy intentionally returns
`WARN` for metadata-only artifacts.

- [ ] **Step 6: Commit Task 5**

```bash
git add sab/ai_brief_eval.py tests/test_ai_brief_eval.py
git commit -m "feat(ai-brief): source-backed tier 평가 추가"
```

### Task 6: Summary Counts And Documentation Surface

**Files:**
- Modify: `sab/report/ai_brief_report.py`
- Modify: `sab/ai_brief.py`
- Modify: `docs/config-reference.md` if AI Brief env vars are documented there
- Test: `tests/test_ai_brief.py`
- Test: report validation tests

- [ ] **Step 1: Add failing tests for summary fields**

Add a test that generated AI Brief artifacts include:

```python
summary = payload["summary"]
assert summary["article_read_attempted_count"] == 1
assert summary["article_accessed_count"] == 0
assert summary["article_verified_count"] == 1
assert summary["article_read_issue_count"] == 0
```

Add validation test that summary fields must be non-negative integers when present:

```python
artifact["summary"]["article_verified_count"] = -1
with pytest.raises(AiBriefValidationError, match="summary.article_verified_count"):
    validate_ai_brief_artifact(artifact, now=EVAL_NOW)
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `just test tests/test_ai_brief.py tests/test_ai_brief_report.py -k article`

Expected: FAIL until summary wiring and validation are complete.

- [ ] **Step 3: Add optional summary validation**

In `sab/report/ai_brief_report.py`, define:

```python
_ARTICLE_READ_SUMMARY_COUNT_FIELDS = (
    "article_read_attempted_count",
    "article_accessed_count",
    "article_verified_count",
    "article_read_issue_count",
)
```

In `_validate_summary_counts()`:

```python
for field_name in _ARTICLE_READ_SUMMARY_COUNT_FIELDS:
    if field_name in summary:
        _summary_int(summary, field_name)
```

- [ ] **Step 4: Ensure `_build_summary()` includes article counts**

In `sab/ai_brief.py`, update `_build_summary()` with optional `article_summary`:

```python
def _build_summary(..., article_summary: Mapping[str, int] | None = None) -> dict[str, object]:
    summary = {...existing fields...}
    if article_summary:
        summary.update(article_summary)
    return summary
```

- [ ] **Step 5: Run focused tests**

Run: `just test tests/test_ai_brief.py tests/test_ai_brief_report.py -k article`

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add sab/ai_brief.py sab/report/ai_brief_report.py tests/test_ai_brief.py tests/test_ai_brief_report.py docs/config-reference.md
git commit -m "feat(ai-brief): 기사 검증 요약 지표 추가"
```

### Task 7: Final Verification

**Files:**
- No new files unless previous tasks uncover focused fixes.

- [ ] **Step 1: Run targeted Python tests**

Run:

```bash
just test \
  tests/test_article_reader.py \
  tests/test_ai_brief.py \
  tests/test_ai_brief_eval.py \
  tests/test_ai_brief_report.py \
  tests/test_cli_dispatch.py
```

Expected: PASS.

- [ ] **Step 2: Run quality gate**

Run: `just quality`

Expected: PASS.

- [ ] **Step 3: Inspect final diff**

Run: `git status --short` and `git log --oneline -n 8`

Expected: worktree clean, branch contains plan and feature commits after the design commit.

- [ ] **Step 4: Final response**

Report branch name, commits created, tests run, and any skipped checks or follow-up risks.
