# AI Brief Candidate And Source Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand AI Brief from ENTER-only rows to swing-relevant READY candidates and make US source collection resilient through a visible provider chain.

**Architecture:** Add a shared candidate classifier, a thin source-provider chain merger, and explicit artifact roles for recommendable and watch-only candidates. Keep single-provider CLI behavior intact, route scheduled chain configuration through the scheduler, and validate the expanded contract in the artifact writer, evaluator, notification text, and web detail view.

**Tech Stack:** Python 3.14, pytest, ruff, mypy, Next.js 16, React 19, TypeScript, Vitest, GitHub Actions YAML.

---

## Problem Brief

**Context:** The 2026-06-15 US scheduled AI Brief run passed only one `ENTER` candidate (`ELV.NYS`) into the AI/source path, although the entry report contained eight `READY` rows. Benzinga returned zero fresh ticker-filtered rows for the only queried ticker. Live checks showed Finnhub covered more of the same candidate set, while Polygon had an API key but returned HTTP 429.

**Problem:** Current AI Brief candidate selection treats "can enter now" as the same thing as "worth swing review." It drops portfolio-cap and risk-review rows that still matter for a swing trading brief. Source collection also has no provider-chain summary, so zero coverage looks like a downstream quality failure instead of an observable provider coverage issue.

**Goal:** Classify `READY` entry rows into recommendable, watch-only, and excluded roles; collect sources for recommendable plus watch-only rows; merge `finnhub,benzinga-news,polygon-news` for scheduled US; write and evaluate the expanded artifact contract; keep scheduled success fail-closed when final recommendations lack source support.

**Non-Goals:** Do not change entry signal generation, auto-entry behavior, buy/entry ranking rules, source URL safety policy, freshness policy, DNS validation, source caps, OpenAI model selection, or the existing single-provider manual CLI path.

**Constraints:** Keep legacy `sab.ai_brief.v1` artifacts readable. Do not commit secrets or local `.env.scheduler.local`. Preserve existing `--source-provider` behavior unless a source-provider chain is explicitly configured. Do not depend on live network calls in tests.

## Impact Note

This changes AI Brief candidate roles, source loading, artifact JSON, model-provider payloads, evaluator expectations, scheduled source configuration, notification text, web detail rendering, and docs. Likely breakages are stale fixtures missing `entry_state`/`entry_price_status`, provider tests expecting one source call, evaluator fixtures using the legacy ENTER-only contract, GitHub Actions secret injection tied to a single provider, and web state-contract drift. Tests must cover classifier roles, source chain merging/failure isolation, artifact validation, evaluator cross-role rejection, watch-only state inference, scheduler env precedence, notifications, web detail display, and docs contract updates.

## Scope Check

The design touches several files, but it is one pipeline contract: classify entry rows, enrich the resulting source universe, constrain model output, and display/evaluate the artifact. Keep it in one plan with separate commits per boundary. Do not split database work because no schema migration is involved.

Execution order is strict except for Task 3 and Task 4, which form one provider/integration boundary. Execute Task 4 before Task 3 Step 8, then return to Task 3 Step 8 through Step 10. This keeps provider signature changes available before `run_ai_brief` calls the expanded contract.

## File Structure

- Create `sab/ai_brief_candidates.py`: shared classifier for recommendable/watch-only/excluded AI roles derived from entry rows.
- Create `tests/test_ai_brief_candidates.py`: focused classifier tests, including the 2026-06-15-style row mix.
- Create `sab/ai_brief_source_chain.py`: provider-chain parser, source merge logic, no-result diagnostics, provider summary construction, and provider failure conversion.
- Create `tests/test_ai_brief_source_chain.py`: deterministic provider-chain unit tests with monkeypatched provider calls.
- Modify `sab/ai_brief.py`: use classifier, resolve chain after market is known, collect sources for recommendable plus watch-only candidates, call model provider with both roles, and write new artifact fields.
- Modify `tests/test_ai_brief.py`: update entry-row helpers to current entry report fields and add end-to-end artifact regressions.
- Modify `sab/ai_brief_providers.py`: add `watch_candidates` to `AiBriefProviderResult`, fake provider output, OpenAI request payload/schema, and provider contract validation.
- Create `tests/test_ai_brief_providers.py`: direct fake/OpenAI contract tests.
- Modify `sab/report/ai_brief_report.py`: validate optional/new watch fields, source provider summary shape, watch source rows, and cross-role ticker constraints.
- Modify `tests/test_ai_brief_report.py`: writer/validator regressions for watch-only fields and provider summary.
- Modify `sab/report/ai_brief_state.py`: add `NEEDS_REVIEW_WATCH_ONLY/watch_only_trigger_pending` state inference.
- Modify `web/src/components/reports/ai-brief-state-contract.json` and `web/src/components/reports/ai-brief-state.ts`: keep frontend inference in sync with Python state export.
- Modify `web/src/components/reports/__tests__/ai-brief-state.test.ts` and `tests/test_docs_state_contract.py`: state contract drift tests.
- Modify `sab/ai_brief_eval.py`: shared classifier expectations, watch contract validation, legacy artifact fallback, and chain-failure quality issue handling.
- Modify `tests/test_ai_brief_eval.py` and `tests/fixtures/ai_brief_eval/*.json`: expanded-contract and legacy-contract evaluator tests.
- Modify `sab/scheduler/runner.py`, `.github/workflows/ai-brief.yml`, and scheduler tests: chain env resolution, chain logging, provider-secret injection for chain members, and default scheduled US docs.
- Modify `sab/report/notification_text.py`, `tests/test_notification_text.py`, `web/src/components/reports/report-detail.tsx`, `web/src/components/reports/use-reports-state.ts`, and `web/src/lib/__tests__/report-detail-component.test.ts`: display watch-only candidates and provider coverage separately.
- Modify `docs/STRATEGY.md`, `docs/ARCHITECTURE.md`, `docs/operations.md`, `docs/configuration.md`, `docs/config-reference.md`, and `docs/ai-brief-us-source-provider-decision.md`: document expanded candidate contract and source-provider chain diagnostics.

## Task 1: Shared Candidate Classifier

**Files:**
- Create: `sab/ai_brief_candidates.py`
- Create: `tests/test_ai_brief_candidates.py`

- [ ] **Step 1: Write failing classifier tests**

Add `tests/test_ai_brief_candidates.py`:

```python
from __future__ import annotations

from sab.ai_brief_candidates import classify_ai_brief_entry_rows


def _row(
    ticker: str,
    *,
    action: str,
    reasons: list[str] | None = None,
    entry_state: str | None = "READY",
    entry_price_status: str | None = "available",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reasons": reasons or [],
        "entry_state": entry_state,
        "entry_price_status": entry_price_status,
    }


def test_classifier_maps_2026_06_15_ready_rows_to_ai_roles() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row("ELV.NYS", action="ENTER"),
            _row(
                "MO.NYS",
                action="SKIP",
                reasons=["hybrid trigger guard failed (70.43 < ema10 71.59)"],
            ),
            _row(
                "CAT.NYS",
                action="SKIP",
                reasons=["portfolio market cap reached (US)"],
            ),
            _row(
                "TSM.NYS",
                action="SKIP",
                reasons=["portfolio market cap reached (US)"],
            ),
            _row(
                "CIFR.NAS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _row(
                "IREN.NAS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _row(
                "COHR.NYS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _row(
                "ANET.NYS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
        ]
    )

    assert [row.ticker for row in result.recommendable] == [
        "ELV.NYS",
        "CAT.NYS",
        "TSM.NYS",
        "CIFR.NAS",
        "IREN.NAS",
        "COHR.NYS",
        "ANET.NYS",
    ]
    assert [row.ticker for row in result.watch_only] == ["MO.NYS"]
    assert result.excluded == []


def test_classifier_excludes_rows_that_fail_base_ready_gates() -> None:
    result = classify_ai_brief_entry_rows(
        [
            _row(
                "MISSING.NAS",
                action="ENTER",
                entry_state="READY",
                entry_price_status="missing",
            ),
            _row(
                "WATCH.NAS",
                action="ENTER",
                entry_state="WATCH",
                entry_price_status="available",
            ),
            _row("UNKNOWN.NAS", action="HOLD"),
        ]
    )

    assert result.recommendable == []
    assert result.watch_only == []
    assert [(row.ticker, row.action) for row in result.excluded] == [
        ("MISSING.NAS", "ENTER"),
        ("WATCH.NAS", "ENTER"),
        ("UNKNOWN.NAS", "HOLD"),
    ]
    assert "entry_price_status=missing" in result.excluded[0].reason
    assert "entry_state=WATCH" in result.excluded[1].reason
    assert "unsupported action HOLD" in result.excluded[2].reason
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_candidates.py -q
```

Expected: fail during import with `ModuleNotFoundError: No module named 'sab.ai_brief_candidates'`.

- [ ] **Step 3: Create the classifier module**

Create `sab/ai_brief_candidates.py`:

```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

AiBriefCandidateRole = Literal["recommendable", "watch_only", "excluded"]

_PORTFOLIO_CAP_REASON_PREFIX = "portfolio market cap reached"
_RISK_ALIGNMENT_REASON = "risk_alignment=tight_stop_vs_volatility"
_HYBRID_TRIGGER_GUARD_REASON = "hybrid trigger guard failed"


@dataclass(frozen=True)
class AiBriefEntryCandidate:
    ticker: str
    action: str
    role: AiBriefCandidateRole
    reason: str
    entry: Mapping[str, object]


@dataclass(frozen=True)
class AiBriefEntryClassification:
    recommendable: list[AiBriefEntryCandidate]
    watch_only: list[AiBriefEntryCandidate]
    excluded: list[AiBriefEntryCandidate]


def entry_reasons(entry: Mapping[str, object]) -> list[str]:
    raw_reasons = entry.get("reasons")
    if not isinstance(raw_reasons, list):
        return []
    return [str(reason).strip() for reason in raw_reasons if str(reason).strip()]


def _has_reason_prefix(reasons: Iterable[str], prefix: str) -> bool:
    return any(reason.lower().startswith(prefix) for reason in reasons)


def _has_reason_text(reasons: Iterable[str], text: str) -> bool:
    return any(text in reason.lower() for reason in reasons)


def _base_gate_failure(entry: Mapping[str, object]) -> str | None:
    entry_state = str(entry.get("entry_state") or "").strip().upper()
    entry_price_status = str(entry.get("entry_price_status") or "").strip().lower()
    failures: list[str] = []
    if entry_state != "READY":
        failures.append(f"entry_state={entry_state or '-'}")
    if entry_price_status != "available":
        failures.append(f"entry_price_status={entry_price_status or '-'}")
    if failures:
        return "entry row failed AI brief base gates: " + ", ".join(failures)
    return None


def classify_ai_brief_entry_row(entry: Mapping[str, object]) -> AiBriefEntryCandidate:
    ticker = str(entry.get("ticker") or "").strip()
    action = str(entry.get("action") or "").strip().upper()
    reasons = entry_reasons(entry)

    if not ticker:
        return AiBriefEntryCandidate(
            ticker="",
            action=action,
            role="excluded",
            reason="entry row ticker is required",
            entry=entry,
        )

    base_gate_failure = _base_gate_failure(entry)
    if base_gate_failure is not None:
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="excluded",
            reason=base_gate_failure,
            entry=entry,
        )

    if action == "ENTER":
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="recommendable",
            reason="entry report action was ENTER",
            entry=entry,
        )
    if action == "SKIP" and _has_reason_prefix(reasons, _PORTFOLIO_CAP_REASON_PREFIX):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="recommendable",
            reason="portfolio policy blocked automatic entry",
            entry=entry,
        )
    if action == "REVIEW" and _has_reason_text(reasons, _RISK_ALIGNMENT_REASON):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="recommendable",
            reason="risk alignment requires manual review",
            entry=entry,
        )
    if action == "SKIP" and _has_reason_text(reasons, _HYBRID_TRIGGER_GUARD_REASON):
        return AiBriefEntryCandidate(
            ticker=ticker,
            action=action,
            role="watch_only",
            reason="entry trigger is pending re-confirmation",
            entry=entry,
        )

    return AiBriefEntryCandidate(
        ticker=ticker,
        action=action,
        role="excluded",
        reason=f"unsupported action {action or '-'} for AI brief role",
        entry=entry,
    )


def classify_ai_brief_entry_rows(
    rows: Iterable[Mapping[str, object]],
) -> AiBriefEntryClassification:
    recommendable: list[AiBriefEntryCandidate] = []
    watch_only: list[AiBriefEntryCandidate] = []
    excluded: list[AiBriefEntryCandidate] = []
    for row in rows:
        classified = classify_ai_brief_entry_row(row)
        if classified.role == "recommendable":
            recommendable.append(classified)
        elif classified.role == "watch_only":
            watch_only.append(classified)
        else:
            excluded.append(classified)
    return AiBriefEntryClassification(
        recommendable=recommendable,
        watch_only=watch_only,
        excluded=excluded,
    )


__all__ = [
    "AiBriefCandidateRole",
    "AiBriefEntryCandidate",
    "AiBriefEntryClassification",
    "classify_ai_brief_entry_row",
    "classify_ai_brief_entry_rows",
    "entry_reasons",
]
```

- [ ] **Step 4: Run classifier tests and verify they pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_candidates.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit classifier boundary**

Run:

```bash
git add sab/ai_brief_candidates.py tests/test_ai_brief_candidates.py
git commit -m "feat(ai-brief): 후보 역할 분류기 추가" -m "AI Brief가 entry READY 행을 recommendable, watch-only, excluded 역할로 나눌 수 있도록 공유 분류기를 추가합니다."
```

## Task 2: Source Provider Chain

**Files:**
- Create: `sab/ai_brief_source_chain.py`
- Create: `tests/test_ai_brief_source_chain.py`

- [ ] **Step 1: Write failing source-chain tests**

Add `tests/test_ai_brief_source_chain.py`:

```python
from __future__ import annotations

import datetime as dt

import pytest

import sab.ai_brief_source_chain as source_chain
from sab.ai_brief_sources import AiBriefSourceProviderError, AiBriefSourceProviderResult


def _source(ticker: str, suffix: str) -> dict[str, object]:
    return {
        "title": f"{ticker} source {suffix}",
        "url": f"https://news.example/{ticker}/{suffix}",
        "published_at": "2026-06-15T12:00:00+00:00",
    }


def test_source_chain_merges_remaining_tickers_and_records_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, set[str]]] = []

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        tickers = set(kwargs["eligible_tickers"])  # type: ignore[arg-type]
        calls.append((provider, tickers))
        if provider == "finnhub":
            return AiBriefSourceProviderResult(
                sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "finnhub")]}
            )
        if provider == "benzinga-news":
            return AiBriefSourceProviderResult(
                sources_by_ticker={"MSFT.NAS": [_source("MSFT.NAS", "benzinga")]}
            )
        return AiBriefSourceProviderResult()

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("finnhub", "benzinga-news"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS", "MSFT.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers={"MSFT.NAS"},
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert calls == [
        ("finnhub", {"AAPL.NAS", "MSFT.NAS"}),
        ("benzinga-news", {"MSFT.NAS"}),
    ]
    assert sorted(result.sources_by_ticker) == ["AAPL.NAS", "MSFT.NAS"]
    assert result.source_issues == []
    assert result.system_issues == []
    assert result.summary["chain"] == ["finnhub", "benzinga-news"]
    assert result.summary["final"] == {
        "recommendable_covered": 1,
        "recommendable_total": 1,
        "watch_covered": 1,
        "watch_total": 1,
    }


def test_source_chain_records_provider_zero_results_per_remaining_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        source_chain,
        "load_ai_brief_sources",
        lambda **_kwargs: AiBriefSourceProviderResult(),
    )

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("benzinga-news",),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS", "MSFT.NAS"},
        recommendable_tickers={"AAPL.NAS", "MSFT.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert {issue["ticker"] for issue in result.source_issues} == {
        "AAPL.NAS",
        "MSFT.NAS",
    }
    assert {issue["code"] for issue in result.source_issues} == {
        "benzinga_news_source_no_results"
    }
    assert result.summary["providers"][0] == {
        "provider": "benzinga-news",
        "status": "success",
        "covered": 0,
        "total": 2,
    }


def test_source_chain_converts_http_429_to_provider_failure_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_load(**kwargs: object) -> AiBriefSourceProviderResult:
        provider = str(kwargs["source_provider"])
        calls.append(provider)
        if provider == "polygon-news":
            raise AiBriefSourceProviderError(
                "Polygon News source request failed with HTTP 429"
            )
        return AiBriefSourceProviderResult(
            sources_by_ticker={"AAPL.NAS": [_source("AAPL.NAS", "fallback")]}
        )

    monkeypatch.setattr(source_chain, "load_ai_brief_sources", fake_load)

    result = source_chain.load_ai_brief_source_chain(
        source_providers=("polygon-news", "finnhub"),
        source_report_path=None,
        source_api_url=None,
        source_timeout_seconds=2.0,
        source_universe_tickers={"AAPL.NAS"},
        recommendable_tickers={"AAPL.NAS"},
        watch_tickers=set(),
        ticker_names={},
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert calls == ["polygon-news", "finnhub"]
    assert result.system_issues[0]["code"] == "http_429"
    assert result.summary["providers"][0] == {
        "provider": "polygon-news",
        "status": "failed",
        "code": "http_429",
        "covered": 0,
        "total": 1,
    }
    assert "AAPL.NAS" in result.sources_by_ticker
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_source_chain.py -q
```

Expected: fail during import with `ModuleNotFoundError: No module named 'sab.ai_brief_source_chain'`.

- [ ] **Step 3: Create source-chain merger**

Create `sab/ai_brief_source_chain.py`:

```python
from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .ai_brief_source_report import source_issue
from .ai_brief_sources import (
    MAX_SOURCES_PER_TICKER,
    SOURCE_PROVIDER_NONE,
    AiBriefSourceProviderError,
    AiBriefSourceProviderResult,
    load_ai_brief_sources,
)

_PROVIDER_ISSUE_PREFIX = {
    "local-json": "local_source",
    "http-json": "http_source",
    "finnhub": "finnhub_source",
    "polygon-news": "polygon_news_source",
    "alpha-vantage-news": "alpha_vantage_news_source",
    "marketaux-news": "marketaux_news_source",
    "benzinga-news": "benzinga_news_source",
    "naver-news": "naver_news_source",
}


@dataclass(frozen=True)
class AiBriefSourceChainResult:
    sources_by_ticker: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    source_issues: list[dict[str, object]] = field(default_factory=list)
    system_issues: list[dict[str, object]] = field(default_factory=list)
    summary: dict[str, object] = field(default_factory=dict)


def parse_source_provider_chain(value: str | None) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    providers = tuple(part.strip().lower() for part in text.split(",") if part.strip())
    if len(set(providers)) != len(providers):
        raise ValueError("source provider chain must not contain duplicate providers")
    if SOURCE_PROVIDER_NONE in providers and len(providers) > 1:
        raise ValueError("source provider chain cannot combine none with providers")
    return providers


def _provider_issue_prefix(provider: str) -> str:
    return _PROVIDER_ISSUE_PREFIX.get(provider, provider.replace("-", "_"))


def _failure_code(exc: AiBriefSourceProviderError) -> str:
    message = str(exc)
    if "HTTP 429" in message:
        return "http_429"
    return exc.code


def _provider_system_issue(
    *,
    provider: str,
    exc: AiBriefSourceProviderError,
) -> dict[str, object]:
    code = _failure_code(exc)
    return {
        "ticker": None,
        "code": "source_provider_chain_failed" if code != "http_429" else code,
        "severity": "WARN",
        "message": f"{provider} source provider failed: {exc}",
    }


def _no_result_issues(
    *,
    provider: str,
    requested_tickers: set[str],
    covered_tickers: set[str],
) -> list[dict[str, object]]:
    prefix = _provider_issue_prefix(provider)
    missing = sorted(requested_tickers - covered_tickers)
    return [
        source_issue(
            ticker=ticker,
            code=f"{prefix}_no_results",
            message=f"{provider} returned no usable sources for {ticker}",
        )
        for ticker in missing
    ]


def _merge_sources(
    target: dict[str, list[dict[str, object]]],
    incoming: Mapping[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    merge_issues: list[dict[str, object]] = []
    seen_urls = {
        ticker: {str(source.get("url") or "") for source in sources}
        for ticker, sources in target.items()
    }
    for ticker in sorted(incoming):
        target_rows = target.setdefault(ticker, [])
        ticker_seen_urls = seen_urls.setdefault(ticker, set())
        for source in incoming[ticker]:
            url = str(source.get("url") or "")
            if url and url in ticker_seen_urls:
                continue
            if len(target_rows) >= MAX_SOURCES_PER_TICKER:
                merge_issues.append(
                    source_issue(
                        ticker=ticker,
                        code="source_chain_cap_exceeded",
                        message=(
                            "source chain row ignored because ticker already has "
                            f"{MAX_SOURCES_PER_TICKER} sources"
                        ),
                    )
                )
                continue
            target_rows.append(dict(source))
            if url:
                ticker_seen_urls.add(url)
    return merge_issues


def _remaining_tickers(
    *,
    source_universe_tickers: set[str],
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> set[str]:
    return {
        ticker
        for ticker in source_universe_tickers
        if len(sources_by_ticker.get(ticker, [])) < MAX_SOURCES_PER_TICKER
    }


def _coverage(
    tickers: set[str],
    sources_by_ticker: Mapping[str, list[dict[str, object]]],
) -> int:
    return sum(1 for ticker in tickers if sources_by_ticker.get(ticker))


def load_ai_brief_source_chain(
    *,
    source_providers: Sequence[str],
    source_report_path: str | None,
    source_api_url: str | None,
    source_timeout_seconds: float | None,
    source_universe_tickers: set[str],
    recommendable_tickers: set[str],
    watch_tickers: set[str],
    ticker_names: Mapping[str, str],
    now: dt.datetime | None = None,
) -> AiBriefSourceChainResult:
    chain = tuple(source_providers)
    if not chain or chain == (SOURCE_PROVIDER_NONE,):
        return AiBriefSourceChainResult(
            summary={
                "chain": [SOURCE_PROVIDER_NONE],
                "providers": [],
                "final": {
                    "recommendable_covered": 0,
                    "recommendable_total": len(recommendable_tickers),
                    "watch_covered": 0,
                    "watch_total": len(watch_tickers),
                },
            }
        )

    sources_by_ticker: dict[str, list[dict[str, object]]] = {}
    source_issues: list[dict[str, object]] = []
    system_issues: list[dict[str, object]] = []
    provider_summaries: list[dict[str, object]] = []
    resolved_now = now or dt.datetime.now().astimezone()

    for provider in chain:
        requested_tickers = _remaining_tickers(
            source_universe_tickers=source_universe_tickers,
            sources_by_ticker=sources_by_ticker,
        )
        if not requested_tickers:
            provider_summaries.append(
                {
                    "provider": provider,
                    "status": "skipped",
                    "covered": 0,
                    "total": 0,
                }
            )
            continue
        try:
            provider_result = load_ai_brief_sources(
                source_provider=provider,
                source_report_path=source_report_path,
                source_api_url=source_api_url,
                source_timeout_seconds=source_timeout_seconds,
                eligible_tickers=requested_tickers,
                ticker_names=ticker_names,
                now=resolved_now,
            )
        except AiBriefSourceProviderError as exc:
            code = _failure_code(exc)
            system_issues.append(_provider_system_issue(provider=provider, exc=exc))
            provider_summaries.append(
                {
                    "provider": provider,
                    "status": "failed",
                    "code": code,
                    "covered": 0,
                    "total": len(requested_tickers),
                }
            )
            continue

        covered_tickers = {
            ticker
            for ticker, sources in provider_result.sources_by_ticker.items()
            if sources
        }
        source_issues.extend(provider_result.source_issues)
        source_issues.extend(
            _merge_sources(sources_by_ticker, provider_result.sources_by_ticker)
        )
        source_issues.extend(
            _no_result_issues(
                provider=provider,
                requested_tickers=requested_tickers,
                covered_tickers=covered_tickers,
            )
        )
        provider_summaries.append(
            {
                "provider": provider,
                "status": "success",
                "covered": len(covered_tickers),
                "total": len(requested_tickers),
            }
        )

    return AiBriefSourceChainResult(
        sources_by_ticker=sources_by_ticker,
        source_issues=source_issues,
        system_issues=system_issues,
        summary={
            "chain": list(chain),
            "providers": provider_summaries,
            "final": {
                "recommendable_covered": _coverage(
                    recommendable_tickers,
                    sources_by_ticker,
                ),
                "recommendable_total": len(recommendable_tickers),
                "watch_covered": _coverage(watch_tickers, sources_by_ticker),
                "watch_total": len(watch_tickers),
            },
        },
    )


__all__ = [
    "AiBriefSourceChainResult",
    "load_ai_brief_source_chain",
    "parse_source_provider_chain",
]
```

- [ ] **Step 4: Run source-chain tests and verify they pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_source_chain.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit source-chain boundary**

Run:

```bash
git add sab/ai_brief_source_chain.py tests/test_ai_brief_source_chain.py
git commit -m "feat(ai-brief): source provider chain 병합 추가" -m "AI Brief source provider 결과를 ticker별로 병합하고 zero-result와 provider 실패를 summary와 issues에 남기는 chain 레이어를 추가합니다."
```

## Task 3: Integrate Candidate Roles And Chain Into `run_ai_brief`

**Files:**
- Modify: `sab/ai_brief.py`
- Modify: `tests/test_ai_brief.py`

- [ ] **Step 1: Write failing `run_ai_brief` artifact tests**

Modify the helper in `tests/test_ai_brief.py` so current entry rows satisfy the new base gates by default:

```python
def _entry_row(
    ticker: str,
    *,
    action: str = "ENTER",
    reasons: list[str] | None = None,
    entry_price: float | None = 101.0,
    entry_state: str | None = "READY",
    entry_price_status: str | None = "available",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": action,
        "reasons": reasons or ["entry conditions satisfied"],
        "signal_close": 100.0,
        "entry_price": entry_price,
        "entry_price_status": entry_price_status,
        "gap_pct": 0.01,
        "gap_guard_pct": 0.03,
        "gap_guard_up_price": 103.0,
        "gap_guard_down_price": 97.0,
        "strategy_mode": "ema_cross",
        "pattern": None,
        "entry_state": entry_state,
    }
```

Add this test near the existing `run_ai_brief` artifact tests:

```python
def test_run_ai_brief_expands_ready_candidates_by_ai_role(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        entries=[
            _entry_row("ELV.NYS", action="ENTER"),
            _entry_row(
                "MO.NYS",
                action="SKIP",
                reasons=["hybrid trigger guard failed (70.43 < ema10 71.59)"],
            ),
            _entry_row(
                "CAT.NYS",
                action="SKIP",
                reasons=["portfolio market cap reached (US)"],
            ),
            _entry_row(
                "TSM.NYS",
                action="SKIP",
                reasons=["portfolio market cap reached (US)"],
            ),
            _entry_row(
                "CIFR.NAS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _entry_row(
                "IREN.NAS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _entry_row(
                "COHR.NYS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
            _entry_row(
                "ANET.NYS",
                action="REVIEW",
                reasons=["risk_alignment=tight_stop_vs_volatility"],
            ),
        ],
    )
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market=None,
        model_provider="fake",
        model_name="fake-ai-brief-v1",
        source_provider=None,
        source_report_path=None,
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["summary"]["recommendable_count"] == 7
    assert payload["summary"]["watch_count"] == 1
    assert payload["eligible_tickers"] == [
        "ELV.NYS",
        "CAT.NYS",
        "TSM.NYS",
        "CIFR.NAS",
        "IREN.NAS",
    ]
    assert payload["watch_tickers"] == ["MO.NYS"]
    assert [row["ticker"] for row in payload["cap_excluded_candidates"]] == [
        "COHR.NYS",
        "ANET.NYS",
    ]
    assert payload["excluded_candidates"] == []
    assert payload["watch_candidates"][0]["ticker"] == "MO.NYS"
    assert payload["source_provider_summary"]["chain"] == ["none"]
```

Add a source-universe regression:

```python
def test_run_ai_brief_source_chain_uses_recommendable_plus_watch_universe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entry_report = _write_entry_report(
        tmp_path,
        entries=[
            _entry_row("AAPL.NAS", action="ENTER"),
            _entry_row(
                "MSFT.NAS",
                action="SKIP",
                reasons=["hybrid trigger guard failed (302.00 < ema10 303.00)"],
            ),
        ],
    )
    report_dir = tmp_path / "reports"
    captured: dict[str, object] = {}

    def fake_chain(**kwargs: object):
        captured.update(kwargs)
        return SimpleNamespace(
            sources_by_ticker={},
            source_issues=[],
            system_issues=[],
            summary={
                "chain": ["finnhub", "benzinga-news"],
                "providers": [],
                "final": {
                    "recommendable_covered": 0,
                    "recommendable_total": 1,
                    "watch_covered": 0,
                    "watch_total": 1,
                },
            },
        )

    monkeypatch.setattr("sab.ai_brief.load_ai_brief_source_chain", fake_chain)
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", "finnhub,benzinga-news")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )

    assert (
        run_ai_brief(
            entry_report_path=entry_report.as_posix(),
            buy_report_path=None,
            market=None,
            model_provider="fake",
            model_name="fake-ai-brief-v1",
            source_provider=None,
            source_report_path=None,
        )
        == 0
    )

    assert captured["source_providers"] == ("finnhub", "benzinga-news")
    assert captured["source_universe_tickers"] == {"AAPL.NAS", "MSFT.NAS"}
    assert captured["recommendable_tickers"] == {"AAPL.NAS"}
    assert captured["watch_tickers"] == {"MSFT.NAS"}
```

- [ ] **Step 2: Run targeted tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief.py::test_run_ai_brief_expands_ready_candidates_by_ai_role tests/test_ai_brief.py::test_run_ai_brief_source_chain_uses_recommendable_plus_watch_universe -q
```

Expected: fail because `watch_tickers`, `watch_candidates`, `source_provider_summary`, and expanded `eligible_tickers` are not produced.

- [ ] **Step 3: Update `sab/ai_brief.py` imports and summary**

Add imports:

```python
from .ai_brief_candidates import (
    AiBriefEntryCandidate,
    classify_ai_brief_entry_rows,
)
from .ai_brief_source_chain import (
    load_ai_brief_source_chain,
    parse_source_provider_chain,
)
```

Extend `_build_summary`:

```python
def _build_summary(
    *,
    entry_count: int,
    recommendable_count: int,
    watch_count: int,
    preselected_count: int,
    recommendation_count: int,
    excluded_count: int,
    vetoed_count: int,
    cap_excluded_count: int,
    source_issue_count: int,
    system_issue_count: int,
) -> dict[str, object]:
    return {
        "entry_count": entry_count,
        "recommendable_count": recommendable_count,
        "watch_count": watch_count,
        "preselected_count": preselected_count,
        "recommendation_count": recommendation_count,
        "excluded_count": excluded_count,
        "vetoed_count": vetoed_count,
        "cap_excluded_count": cap_excluded_count,
        "source_issue_count": source_issue_count,
        "system_issue_count": system_issue_count,
    }
```

- [ ] **Step 4: Add candidate builders for roles**

Replace `_build_model_candidate`, `_build_excluded_candidate`, and `_build_cap_excluded_candidate` with role-aware versions:

```python
def _build_model_candidate(
    classified: AiBriefEntryCandidate,
    buy_candidate: Mapping[str, Any] | None,
) -> dict[str, object]:
    entry = classified.entry
    ticker = classified.ticker
    name = None
    if buy_candidate is not None:
        raw_name = buy_candidate.get("name")
        if raw_name is not None and str(raw_name).strip():
            name = str(raw_name).strip()
    return {
        "ticker": ticker,
        "name": name,
        "action": classified.action,
        "ai_role": classified.role,
        "ai_role_reason": classified.reason,
        "entry_reasons": [
            str(reason).strip()
            for reason in entry.get("reasons", [])
            if str(reason).strip()
        ]
        if isinstance(entry.get("reasons"), list)
        else [],
        "buy_reason_labels": _extract_buy_reason_labels(buy_candidate),
        "entry_price": entry.get("entry_price"),
        "gap_pct": entry.get("gap_pct"),
        "gap_guard_pct": entry.get("gap_guard_pct"),
        "strategy_mode": entry.get("strategy_mode"),
        "pattern": entry.get("pattern"),
        "entry_state": entry.get("entry_state"),
        "sources": [],
    }


def _build_excluded_candidate(classified: AiBriefEntryCandidate) -> dict[str, object]:
    return {
        "ticker": classified.ticker,
        "action": classified.action,
        "reason": classified.reason,
    }


def _build_cap_excluded_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "ticker": str(candidate["ticker"]),
        "action": str(candidate.get("action") or "ENTER").upper(),
        "reason": f"preselection cap {_PRESELECTION_LIMIT} exceeded",
    }
```

- [ ] **Step 5: Resolve source chain after target market is known**

Add `source_provider_chain` to the `run_ai_brief` signature:

```python
    source_provider_chain: str | None = None,
```

Add helpers:

```python
def _source_chain_env_value(market: str, explicit_chain: str | None) -> str | None:
    explicit = str(explicit_chain or "").strip()
    if explicit:
        return explicit
    market_value = os.getenv(f"AI_BRIEF_SOURCE_PROVIDER_CHAIN_{market}")
    if market_value and market_value.strip():
        return market_value
    global_value = os.getenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN")
    if global_value and global_value.strip():
        return global_value
    return None


def _resolve_source_provider_chain(
    *,
    target_market: str,
    normalized_source_provider: str,
    source_provider_chain: str | None,
) -> tuple[str, ...]:
    configured = parse_source_provider_chain(
        _source_chain_env_value(target_market, source_provider_chain)
    )
    if configured:
        return configured
    return (normalized_source_provider,)
```

Do not read chain env before `target_market` is known.

- [ ] **Step 6: Replace ENTER-only classification block**

In `run_ai_brief`, replace the loop that builds `eligible_candidates` and `excluded_candidates`:

```python
    classified_rows = classify_ai_brief_entry_rows(target_rows)
    eligible_candidates = [
        _build_model_candidate(classified, buy_enrichment.get(classified.ticker))
        for classified in classified_rows.recommendable
    ]
    watch_candidates = [
        _build_model_candidate(classified, buy_enrichment.get(classified.ticker))
        for classified in classified_rows.watch_only
    ]
    excluded_candidates = [
        _build_excluded_candidate(classified)
        for classified in classified_rows.excluded
    ]

    preselected_candidates = eligible_candidates[:_PRESELECTION_LIMIT]
    cap_excluded_candidates = [
        _build_cap_excluded_candidate(candidate)
        for candidate in eligible_candidates[_PRESELECTION_LIMIT:]
    ]
```

- [ ] **Step 7: Replace direct source provider call with source chain call**

Replace the `load_ai_brief_sources(...)` call and related success/failure assignment with:

```python
    source_provider_chain = _resolve_source_provider_chain(
        target_market=target_market,
        normalized_source_provider=normalized_source_provider,
        source_provider_chain=source_provider_chain,
    )
    source_provider_summary: dict[str, object] = {}
    source_universe_candidates = [*preselected_candidates, *watch_candidates]
    source_universe_tickers = {
        str(candidate["ticker"]) for candidate in source_universe_candidates
    }
    ticker_names = {
        str(candidate["ticker"]): str(candidate.get("name") or "").strip()
        for candidate in source_universe_candidates
        if str(candidate.get("name") or "").strip()
    }
    source_chain_result = load_ai_brief_source_chain(
        source_providers=source_provider_chain,
        source_report_path=source_report_path,
        source_api_url=normalized_source_api_url,
        source_timeout_seconds=normalized_source_timeout_seconds,
        source_universe_tickers=source_universe_tickers,
        recommendable_tickers={
            str(candidate["ticker"]) for candidate in preselected_candidates
        },
        watch_tickers={str(candidate["ticker"]) for candidate in watch_candidates},
        ticker_names=ticker_names,
    )
    preselected_candidates = _attach_candidate_sources(
        preselected_candidates,
        source_chain_result.sources_by_ticker,
    )
    watch_candidates = _attach_candidate_sources(
        watch_candidates,
        source_chain_result.sources_by_ticker,
    )
    source_provider_issues = source_chain_result.source_issues
    system_issues.extend(source_chain_result.system_issues)
    source_provider_summary = source_chain_result.summary
```

Keep the existing `try/except AiBriefSourceProviderError` block around this call for single-provider compatibility errors raised before the chain helper handles a provider. In the exception block, attach empty sources to both `preselected_candidates` and `watch_candidates`, and set `source_provider_summary` to:

```python
{
    "chain": list(source_provider_chain),
    "providers": [
        {
            "provider": source_provider_chain[0] if source_provider_chain else "none",
            "status": "failed",
            "code": exc.code,
            "covered": 0,
            "total": len(source_universe_tickers),
        }
    ],
    "final": {
        "recommendable_covered": 0,
        "recommendable_total": len(preselected_candidates),
        "watch_covered": 0,
        "watch_total": len(watch_candidates),
    },
}
```

- [ ] **Step 8: Call model provider with both candidate roles and write artifact fields**

After Task 4 changes the provider signature, update the model call:

```python
        provider_result = provider.build_recommendations(
            recommendable_candidates=preselected_candidates,
            watch_candidates=watch_candidates,
        )
        recommendations = provider_result.recommendations
        source_issues = [*source_provider_issues, *provider_result.source_issues]
        vetoed_candidates = provider_result.vetoed_candidates
        model_watch_candidates = provider_result.watch_candidates
```

In the provider exception block:

```python
        model_watch_candidates = []
```

Add fields to the artifact:

```python
        "watch_tickers": [str(candidate["ticker"]) for candidate in watch_candidates],
        "watch_candidates": model_watch_candidates,
        "source_provider_summary": source_provider_summary,
```

Pass the new summary counts:

```python
            recommendable_count=len(eligible_candidates),
            watch_count=len(watch_candidates),
```

- [ ] **Step 9: Run targeted `run_ai_brief` tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief.py::test_run_ai_brief_expands_ready_candidates_by_ai_role tests/test_ai_brief.py::test_run_ai_brief_source_chain_uses_recommendable_plus_watch_universe tests/test_ai_brief.py::test_run_ai_brief_writes_recommendations_from_entry_report_only tests/test_ai_brief.py::test_run_ai_brief_local_source_provider_enriches_fake_recommendation_sources -q
```

Expected: pass after Task 4 provider signature changes are present. If this step is reached before Task 4, expect a provider signature failure and continue with Task 4 before rerunning.

- [ ] **Step 10: Commit `run_ai_brief` integration**

Run after Task 4 and Task 5 targeted tests pass:

```bash
git add sab/ai_brief.py tests/test_ai_brief.py
git commit -m "feat(ai-brief): READY 후보를 AI brief 입력으로 확장" -m "AI Brief가 recommendable과 watch-only 후보를 분리해 source universe와 artifact에 반영하도록 run_ai_brief 경로를 확장합니다."
```

## Task 4: Model Provider Role Contract

**Files:**
- Modify: `sab/ai_brief_providers.py`
- Create: `tests/test_ai_brief_providers.py`

- [ ] **Step 1: Write failing provider contract tests**

Add `tests/test_ai_brief_providers.py`:

```python
from __future__ import annotations

import json

import pytest

from sab.ai_brief_providers import (
    AiBriefProviderContractError,
    FakeAiBriefProvider,
    OpenAiBriefProvider,
)


def _candidate(ticker: str, *, role: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "name": None,
        "action": "ENTER" if role == "recommendable" else "SKIP",
        "ai_role": role,
        "ai_role_reason": "test role reason",
        "entry_reasons": ["entry reason"],
        "buy_reason_labels": [],
        "entry_price": 100.0,
        "gap_pct": 0.01,
        "gap_guard_pct": 0.03,
        "strategy_mode": "ema_cross",
        "pattern": None,
        "entry_state": "READY",
        "sources": [
            {
                "title": f"{ticker} source",
                "url": f"https://news.example/{ticker}",
                "published_at": "2026-06-15T12:00:00+00:00",
            }
        ],
    }


def test_fake_provider_returns_watch_candidates_separately() -> None:
    provider = FakeAiBriefProvider(model_name="fake-ai-brief-v1")

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    assert [row["ticker"] for row in result.recommendations] == ["AAPL.NAS"]
    assert [row["ticker"] for row in result.watch_candidates] == ["MSFT.NAS"]
    assert result.watch_candidates[0]["action"] == "WATCH"


def test_openai_payload_separates_recommendable_and_watch_candidates() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [
                    {
                        "ticker": "AAPL.NAS",
                        "action": "SKIP",
                        "reason": "source risk",
                    }
                ],
                "watch_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "sources": [
                            {
                                "title": "MSFT source",
                                "url": "https://news.example/MSFT.NAS",
                                "published_at": "2026-06-15T12:00:00+00:00",
                            }
                        ],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    request = provider._session.requests[0]["json"]  # type: ignore[attr-defined]
    user_payload = json.loads(request["input"][1]["content"])
    assert [row["ticker"] for row in user_payload["recommendable_candidates"]] == [
        "AAPL.NAS"
    ]
    assert [row["ticker"] for row in user_payload["watch_candidates"]] == ["MSFT.NAS"]
    assert result.watch_candidates[0]["ticker"] == "MSFT.NAS"


def test_openai_rejects_watch_candidate_returned_as_recommendation() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [
                    {
                        "ticker": "MSFT.NAS",
                        "rank": 1,
                        "confidence": "LOW",
                        "rationale": ["bad role"],
                        "checklist": ["manual check"],
                        "sources": [],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [
                    {
                        "ticker": "MSFT.NAS",
                        "code": "openai_no_source",
                        "severity": "WARN",
                        "message": "no source",
                    }
                ],
            }
        ),
    )

    with pytest.raises(AiBriefProviderContractError, match="ineligible ticker"):
        provider.build_recommendations(
            recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
            watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
        )


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, object]:
        return {
            "output_text": json.dumps(self._payload),
        }


class _CapturingSession:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> _Response:
        self.requests.append({"url": url, **kwargs})
        return _Response(self.payload)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py -q
```

Expected: fail because `build_recommendations` does not accept `recommendable_candidates` and `watch_candidates`.

- [ ] **Step 3: Extend provider result and method signatures**

In `sab/ai_brief_providers.py`, change the result dataclass:

```python
@dataclass(frozen=True)
class AiBriefProviderResult:
    recommendations: list[dict[str, object]]
    source_issues: list[dict[str, object]]
    vetoed_candidates: list[dict[str, object]] = field(default_factory=list)
    watch_candidates: list[dict[str, object]] = field(default_factory=list)
```

Change both provider methods:

```python
def build_recommendations(
    self,
    *,
    recommendable_candidates: list[dict[str, object]],
    watch_candidates: list[dict[str, object]],
) -> AiBriefProviderResult:
```

Return empty result only when both lists are empty.

- [ ] **Step 4: Update fake provider output**

In `FakeAiBriefProvider.build_recommendations`, iterate only `recommendable_candidates` for recommendations, and add:

```python
        watch_rows: list[dict[str, object]] = []
        for candidate in watch_candidates:
            ticker = str(candidate["ticker"])
            watch_rows.append(
                {
                    "ticker": ticker,
                    "action": "WATCH",
                    "reason": str(
                        candidate.get("ai_role_reason")
                        or "entry trigger requires re-confirmation"
                    ),
                    "retrigger_conditions": [
                        "price must satisfy the original entry trigger again",
                        "manual review must confirm source and market context",
                    ],
                    "sources": _candidate_sources(candidate),
                    "as_of": as_of,
                }
            )
```

Return:

```python
return AiBriefProviderResult(
    recommendations=recommendations,
    source_issues=source_issues,
    watch_candidates=watch_rows,
)
```

- [ ] **Step 5: Update OpenAI payload and schema**

Change `_build_openai_request_payload` signature:

```python
def _build_openai_request_payload(
    *,
    model_name: str,
    recommendable_candidates: list[dict[str, object]],
    watch_candidates: list[dict[str, object]],
) -> dict[str, _JsonValue]:
```

Change the user JSON:

```python
{
    "task": (
        "Rank up to three recommendable swing-trading candidates. "
        "Summarize watch candidates separately; never place watch candidates "
        "in recommendations or vetoed_candidates."
    ),
    "recommendable_candidates": recommendable_candidates,
    "watch_candidates": watch_candidates,
}
```

In `_openai_result_schema`, add `"watch_candidates"` to `required`, with this property:

```python
"watch_candidates": {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "ticker",
            "action",
            "reason",
            "retrigger_conditions",
            "sources",
        ],
        "properties": {
            "ticker": {"type": "string"},
            "action": {"type": "string", "enum": ["WATCH"]},
            "reason": {"type": "string"},
            "retrigger_conditions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "sources": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "url", "published_at"],
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "published_at": {"type": "string"},
                    },
                },
            },
        },
    },
},
```

- [ ] **Step 6: Normalize and validate watch candidates**

Add `watch_candidates` extraction in `_normalize_openai_provider_result`:

```python
watch_candidate_by_ticker = {
    str(candidate["ticker"]): candidate for candidate in watch_candidates
}
normalized_watch_candidates: list[dict[str, object]] = []
for raw_watch in _as_provider_mapping_rows(
    parsed.get("watch_candidates"), field_name="watch_candidates"
):
    ticker = str(raw_watch.get("ticker") or "").strip()
    if ticker not in watch_candidate_by_ticker:
        raise AiBriefProviderContractError(
            f"OpenAI output included ineligible watch ticker {ticker!r}"
        )
    normalized_watch_candidates.append(
        {
            "ticker": ticker,
            "action": "WATCH",
            "reason": str(raw_watch.get("reason") or "").strip(),
            "retrigger_conditions": string_list(
                raw_watch.get("retrigger_conditions")
            ),
            "sources": _canonicalize_provider_sources(
                _as_provider_mapping_rows(
                    raw_watch.get("sources"), field_name="watch_candidates.sources"
                ),
                canonical_sources_by_url=source_rows_by_ticker.get(ticker, {}),
            ),
        }
    )
```

Pass both `eligible_tickers` and `watch_tickers` into `_validate_provider_result_contract`, and add a `_validate_provider_watch_candidates` helper that enforces ticker membership, `action == "WATCH"`, non-empty reason, non-empty `retrigger_conditions`, and source URLs from the watch candidate's supplied sources.

- [ ] **Step 7: Run provider tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py -q
```

Expected: `3 passed`.

- [ ] **Step 8: Commit provider contract**

Run:

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py
git commit -m "feat(ai-brief): 모델 provider watch 후보 계약 추가" -m "Fake/OpenAI provider가 recommendable 후보와 watch-only 후보를 분리해 처리하고 watch_candidates를 반환하도록 계약을 확장합니다."
```

## Task 5: Artifact Validation And Brief State

**Files:**
- Modify: `sab/report/ai_brief_report.py`
- Modify: `tests/test_ai_brief_report.py`
- Modify: `sab/report/ai_brief_state.py`
- Modify: `web/src/components/reports/ai-brief-state-contract.json`
- Modify: `web/src/components/reports/ai-brief-state.ts`
- Modify: `web/src/components/reports/__tests__/ai-brief-state.test.ts`
- Modify: `tests/test_docs_state_contract.py`

- [ ] **Step 1: Write failing artifact/state tests**

Add Python state test in the existing AI Brief state test area:

```python
def test_infer_ai_brief_state_marks_watch_only_without_recommendable_candidates() -> None:
    payload = {
        "summary": {
            "preselected_count": 0,
            "watch_count": 1,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": [],
        "watch_tickers": ["MSFT.NAS"],
        "recommendations": [],
        "watch_candidates": [
            {
                "ticker": "MSFT.NAS",
                "action": "WATCH",
                "reason": "trigger pending",
                "retrigger_conditions": ["price above trigger"],
                "sources": [],
            }
        ],
        "source_issues": [],
        "system_issues": [],
    }

    assert infer_ai_brief_state(payload).state == "NEEDS_REVIEW_WATCH_ONLY"
    assert infer_ai_brief_state(payload).reason == "watch_only_trigger_pending"
```

Add artifact validation tests in `tests/test_ai_brief_report.py`:

```python
def test_ai_brief_report_validates_watch_candidates_in_watch_tickers() -> None:
    artifact = _valid_ai_brief_artifact()
    artifact["summary"]["watch_count"] = 1
    artifact["watch_tickers"] = ["MSFT.NAS"]
    artifact["watch_candidates"] = [
        {
            "ticker": "MSFT.NAS",
            "action": "WATCH",
            "reason": "trigger pending",
            "retrigger_conditions": ["price above trigger"],
            "sources": [],
        }
    ]
    artifact["source_provider_summary"] = {
        "chain": ["finnhub"],
        "providers": [{"provider": "finnhub", "status": "success", "covered": 0, "total": 1}],
        "final": {
            "recommendable_covered": 0,
            "recommendable_total": 1,
            "watch_covered": 0,
            "watch_total": 1,
        },
    }

    validate_ai_brief_artifact(
        artifact,
        now=dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC),
    )


def test_ai_brief_report_rejects_watch_candidate_in_eligible_tickers_only() -> None:
    artifact = _valid_ai_brief_artifact()
    artifact["watch_tickers"] = []
    artifact["watch_candidates"] = [
        {
            "ticker": "AAPL.NAS",
            "action": "WATCH",
            "reason": "trigger pending",
            "retrigger_conditions": ["price above trigger"],
            "sources": [],
        }
    ]

    with pytest.raises(AiBriefValidationError, match="watch_candidates"):
        validate_ai_brief_artifact(
            artifact,
            now=dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.UTC),
        )
```

Add frontend state test:

```ts
it("infers watch-only review state when only watch candidates exist", () => {
  const detail: ReportJson = {
    summary: {
      preselected_count: 0,
      watch_count: 1,
      recommendation_count: 0,
      source_issue_count: 0,
      system_issue_count: 0,
    },
    eligible_tickers: [],
    watch_tickers: ["MSFT.NAS"],
    recommendations: [],
    watch_candidates: [{ ticker: "MSFT.NAS", action: "WATCH" }],
    source_issues: [],
    system_issues: [],
  };

  expect(resolveAiBriefState(detail)).toEqual({
    state: "NEEDS_REVIEW_WATCH_ONLY",
    reason: "watch_only_trigger_pending",
  });
});
```

- [ ] **Step 2: Run targeted tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_report.py tests/test_docs_state_contract.py -q
pnpm --dir web run test -- --run web/src/components/reports/__tests__/ai-brief-state.test.ts
```

Expected: Python tests fail on unknown state/reason or missing watch validation; web test fails because the contract lacks the new rule.

- [ ] **Step 3: Add watch-only state in Python**

In `sab/report/ai_brief_state.py`, add:

```python
BRIEF_STATE_NEEDS_REVIEW_WATCH_ONLY = "NEEDS_REVIEW_WATCH_ONLY"
BRIEF_REASON_WATCH_ONLY_TRIGGER_PENDING = "watch_only_trigger_pending"
BRIEF_RULE_WATCH_ONLY = "watch_only"
```

Include the state/reason/rule in `AI_BRIEF_STATES`, `AI_BRIEF_REASONS`, `AI_BRIEF_STATE_RULES`, `AI_BRIEF_STATE_ORDER`, `AI_BRIEF_REASON_ORDER`, and `AI_BRIEF_INFERENCE_PRECEDENCE` immediately after `no_signal`.

Extend `AiBriefStateInputs`:

```python
watch_count: int
```

Read the count:

```python
watch_candidates = _mapping_rows(payload.get("watch_candidates"))
watch_tickers = payload.get("watch_tickers")
watch_ticker_count = len(watch_tickers) if isinstance(watch_tickers, list) else 0
watch_count = _count_with_row_floor(
    summary.get("watch_count"),
    payload.get("watch_count"),
    row_count=max(watch_ticker_count, len(watch_candidates)),
)
```

Update inference:

```python
    if inputs.preselected_count == 0 and inputs.watch_count == 0:
        return _state_for_rule(BRIEF_RULE_NO_SIGNAL)
    if inputs.preselected_count == 0 and inputs.watch_count > 0:
        return _state_for_rule(BRIEF_RULE_WATCH_ONLY)
```

- [ ] **Step 4: Regenerate or edit frontend contract JSON**

Update `web/src/components/reports/ai-brief-state-contract.json` to match `export_ai_brief_state_contract()` output. The JSON must include:

```json
{
  "states": [
    "NO_SIGNAL",
    "NEEDS_REVIEW_WATCH_ONLY",
    "FINAL_JUDGMENT",
    "NEEDS_REVIEW_WEAK_NEWS"
  ],
  "reasons": [
    "no_enter_candidates",
    "watch_only_trigger_pending",
    "source_backed_final",
    "weak_news_coverage",
    "model_or_system_issue",
    "model_deferred"
  ],
  "inference_precedence": [
    "no_signal",
    "watch_only",
    "source_backed_final",
    "system_issue",
    "weak_news_coverage",
    "model_deferred"
  ]
}
```

Keep the existing `rules` and `reasons_by_state` structure, with `watch_only` mapping to `NEEDS_REVIEW_WATCH_ONLY/watch_only_trigger_pending`.

- [ ] **Step 5: Update frontend state inference**

In `web/src/components/reports/ai-brief-state.ts`, extend `AiBriefStateInputsView`:

```ts
watchCount: number;
```

Update predicates:

```ts
no_signal: (inputs) =>
  inputs.preselectedCount === 0 && inputs.watchCount === 0,
watch_only: (inputs) =>
  inputs.preselectedCount === 0 && inputs.watchCount > 0,
```

Read watch count in `resolveAiBriefState`:

```ts
const watchCandidates = asRecordArray(detail?.watch_candidates);
const watchTickers = Array.isArray(detail?.watch_tickers)
  ? detail.watch_tickers
  : [];
const watchCount = readCountAtLeast(
  detail,
  "watch_count",
  Math.max(watchCandidates.length, watchTickers.length),
);
```

Pass `watchCount` to `inferAiBriefStateFromContract`.

- [ ] **Step 6: Add artifact validation for watch fields and provider summary**

In `sab/report/ai_brief_report.py`, add optional list helpers:

```python
def _optional_ticker_set(payload: Mapping[str, Any], field_name: str) -> set[str]:
    raw = payload.get(field_name)
    if raw is None:
        return set()
    return {str(item).strip() for item in _require_list(raw, field_name=field_name) if str(item).strip()}
```

Add `_validate_watch_candidates`:

```python
def _validate_watch_candidates(payload: Mapping[str, Any], *, now: dt.datetime) -> None:
    watch_tickers = _optional_ticker_set(payload, "watch_tickers")
    rows = payload.get("watch_candidates")
    if rows is None:
        return
    for idx, raw_row in enumerate(_require_list(rows, field_name="watch_candidates")):
        row = _require_mapping(raw_row, field_name=f"watch_candidates[{idx}]")
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker not in watch_tickers:
            raise AiBriefValidationError("watch_candidates[].ticker must be in watch_tickers")
        if str(row.get("action") or "").strip().upper() != "WATCH":
            raise AiBriefValidationError("watch_candidates[].action must be WATCH")
        if not str(row.get("reason") or "").strip():
            raise AiBriefValidationError("watch_candidates[].reason is required")
        if not _require_list(row.get("retrigger_conditions"), field_name=f"watch_candidates[{idx}].retrigger_conditions"):
            raise AiBriefValidationError("watch_candidates[].retrigger_conditions is required")
        _validate_sources_for_field(
            row=row,
            field_name=f"watch_candidates[{idx}].sources",
            now=now,
        )
```

Extract the existing recommendation source validation into `_validate_sources_for_field` so recommendations and watch rows share URL/time validation.

Add `_validate_source_provider_summary` that accepts an absent field for legacy artifacts and validates object shape when present:

```python
def _validate_source_provider_summary(payload: Mapping[str, Any]) -> None:
    raw_summary = payload.get("source_provider_summary")
    if raw_summary is None:
        return
    summary = _require_mapping(raw_summary, field_name="source_provider_summary")
    _require_list(summary.get("chain"), field_name="source_provider_summary.chain")
    _require_list(summary.get("providers"), field_name="source_provider_summary.providers")
    _require_mapping(summary.get("final"), field_name="source_provider_summary.final")
```

Call both validators from `validate_ai_brief_artifact`.

- [ ] **Step 7: Run artifact/state tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_report.py tests/test_docs_state_contract.py -q
pnpm --dir web run test -- --run web/src/components/reports/__tests__/ai-brief-state.test.ts
```

Expected: pass.

- [ ] **Step 8: Commit artifact/state contract**

Run:

```bash
git add sab/report/ai_brief_report.py sab/report/ai_brief_state.py web/src/components/reports/ai-brief-state-contract.json web/src/components/reports/ai-brief-state.ts tests/test_ai_brief_report.py tests/test_docs_state_contract.py web/src/components/reports/__tests__/ai-brief-state.test.ts
git commit -m "feat(ai-brief): watch-only 상태와 artifact 계약 추가" -m "AI Brief artifact가 watch-only 후보와 provider summary를 검증하고 watch-only 전용 brief_state를 추론하도록 계약을 확장합니다."
```

## Task 6: Evaluator And Quality Gate

**Files:**
- Modify: `sab/ai_brief_eval.py`
- Modify: `tests/test_ai_brief_eval.py`
- Modify: `tests/fixtures/ai_brief_eval/entry.us.json`
- Modify: `tests/fixtures/ai_brief_eval/ai-brief.good.json`

- [ ] **Step 1: Write failing evaluator tests**

Add tests in `tests/test_ai_brief_eval.py`:

```python
def test_ai_brief_eval_accepts_expanded_ready_candidate_contract(tmp_path: Path) -> None:
    entry_report = tmp_path / "expanded.entry.json"
    entry_report.write_text(
        json.dumps(
            {
                "schema": "sab.report.v1",
                "type": "entry",
                "market": "US",
                "entries": [
                    {
                        "ticker": "AAPL.NAS",
                        "action": "ENTER",
                        "entry_state": "READY",
                        "entry_price_status": "available",
                        "reasons": [],
                    },
                    {
                        "ticker": "MSFT.NAS",
                        "action": "SKIP",
                        "entry_state": "READY",
                        "entry_price_status": "available",
                        "reasons": ["hybrid trigger guard failed (302 < 303)"],
                    },
                    {
                        "ticker": "CAT.NYS",
                        "action": "SKIP",
                        "entry_state": "READY",
                        "entry_price_status": "available",
                        "reasons": ["portfolio market cap reached (US)"],
                    },
                ],
                "summary": {"entry_count": 3},
                "system_issues": [],
            }
        ),
        encoding="utf-8",
    )
    ai_brief_report = tmp_path / "expanded.ai-brief.json"
    ai_brief_report.write_text(
        json.dumps(
            _expanded_ai_brief_payload(
                eligible_tickers=["AAPL.NAS", "CAT.NYS"],
                watch_tickers=["MSFT.NAS"],
            )
        ),
        encoding="utf-8",
    )

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_report.as_posix(),
        ai_brief_report_path=ai_brief_report.as_posix(),
        market="US",
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.status == "PASS"
    assert result.summary["expected_preselected_count"] == 2
    assert result.summary["expected_watch_count"] == 1


def test_ai_brief_eval_rejects_watch_ticker_as_recommendation(tmp_path: Path) -> None:
    entry_report, ai_brief_report = _write_expanded_eval_reports(tmp_path)
    payload = json.loads(ai_brief_report.read_text(encoding="utf-8"))
    payload["recommendations"][0]["ticker"] = "MSFT.NAS"
    ai_brief_report.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_report.as_posix(),
        ai_brief_report_path=ai_brief_report.as_posix(),
        market="US",
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.status == "FAIL"
    assert "recommendation_ticker_not_preselected" in _issue_codes(result)


def test_ai_brief_eval_fails_when_source_provider_chain_reports_total_failure(
    tmp_path: Path,
) -> None:
    entry_report, ai_brief_report = _write_expanded_eval_reports(tmp_path)
    payload = json.loads(ai_brief_report.read_text(encoding="utf-8"))
    payload["system_issues"] = [
        {
            "ticker": None,
            "code": "source_provider_chain_failed",
            "severity": "ERROR",
            "message": "all source providers failed",
        }
    ]
    payload["summary"]["system_issue_count"] = 1
    ai_brief_report.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_ai_brief_recommendation_report(
        entry_report_path=entry_report.as_posix(),
        ai_brief_report_path=ai_brief_report.as_posix(),
        market="US",
        now=dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC),
    )

    assert result.status == "FAIL"
    assert "ai_brief_system_issue_error" in _issue_codes(result)
```

Add helper payloads in the same test file:

```python
def _expanded_ai_brief_payload(
    *,
    eligible_tickers: list[str],
    watch_tickers: list[str],
) -> dict[str, object]:
    return {
        "schema": "sab.ai_brief.v1",
        "type": "ai_brief",
        "generated_at": "2026-06-15T12:00:00+00:00",
        "report_date": "2026-06-15",
        "source_entry_report": "expanded.entry.json",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "entry_count": 3,
            "recommendable_count": len(eligible_tickers),
            "watch_count": len(watch_tickers),
            "preselected_count": len(eligible_tickers),
            "recommendation_count": 1,
            "excluded_count": 0,
            "vetoed_count": 1,
            "cap_excluded_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": eligible_tickers,
        "watch_tickers": watch_tickers,
        "recommendations": [
            {
                "ticker": eligible_tickers[0],
                "name": None,
                "rank": 1,
                "action": "ENTER",
                "confidence": "MEDIUM",
                "rationale": ["entry report marked this candidate ENTER"],
                "checklist": ["manual pre-order check"],
                "sources": [
                    {
                        "title": "AAPL source",
                        "url": "https://news.example.test/aapl",
                        "published_at": "2026-06-15T10:00:00+00:00",
                    }
                ],
                "as_of": "2026-06-15T12:00:00+00:00",
            }
        ],
        "vetoed_candidates": [
            {"ticker": eligible_tickers[-1], "action": "SKIP", "reason": "manual risk"}
        ],
        "watch_candidates": [
            {
                "ticker": watch_tickers[0],
                "action": "WATCH",
                "reason": "trigger pending",
                "retrigger_conditions": ["price above trigger"],
                "sources": [],
            }
        ],
        "excluded_candidates": [],
        "cap_excluded_candidates": [],
        "source_issues": [],
        "system_issues": [],
        "source_provider_summary": {
            "chain": ["finnhub"],
            "providers": [{"provider": "finnhub", "status": "success", "covered": 1, "total": 3}],
            "final": {
                "recommendable_covered": 1,
                "recommendable_total": len(eligible_tickers),
                "watch_covered": 0,
                "watch_total": len(watch_tickers),
            },
        },
    }
```

- [ ] **Step 2: Run evaluator tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_eval.py::test_ai_brief_eval_accepts_expanded_ready_candidate_contract tests/test_ai_brief_eval.py::test_ai_brief_eval_rejects_watch_ticker_as_recommendation tests/test_ai_brief_eval.py::test_ai_brief_eval_fails_when_source_provider_chain_reports_total_failure -q
```

Expected: fail because the evaluator still expects ENTER-only preselection and no watch contract.

- [ ] **Step 3: Use shared classifier in evaluator**

In `sab/ai_brief_eval.py`, import:

```python
from .ai_brief_candidates import classify_ai_brief_entry_rows
```

Extend `_EntryContext`:

```python
expected_watch_tickers: list[str]
```

Add contract detector:

```python
def _uses_expanded_candidate_contract(ai_brief_report: Mapping[str, Any]) -> bool:
    return any(
        field_name in ai_brief_report
        for field_name in (
            "watch_tickers",
            "watch_candidates",
            "source_provider_summary",
        )
    )
```

Pass `expanded_contract=_uses_expanded_candidate_contract(ai_brief_report)` into `_load_entry_context`.

- [ ] **Step 4: Update `_load_entry_context` with legacy fallback**

Change signature:

```python
def _load_entry_context(
    entry_report_path: str,
    *,
    market: str | None,
    expanded_contract: bool,
) -> tuple[_EntryContext | None, AiBriefRecommendationEvalIssue | None]:
```

After `target_rows` are collected, branch:

```python
if expanded_contract:
    classified = classify_ai_brief_entry_rows(target_rows)
    recommendable_tickers = [row.ticker for row in classified.recommendable]
    excluded_candidates = [
        (row.ticker, row.action) for row in classified.excluded
    ]
    return _EntryContext(
        market=market,
        target_entry_count=target_entry_count,
        expected_preselected_tickers=recommendable_tickers[:PRESELECTION_LIMIT],
        expected_watch_tickers=[row.ticker for row in classified.watch_only],
        expected_excluded_candidates=excluded_candidates,
        expected_cap_excluded_candidates=[
            (row.ticker, row.action)
            for row in classified.recommendable[PRESELECTION_LIMIT:]
        ],
    ), None
```

Keep the existing ENTER-only logic in the `else` branch and return `expected_watch_tickers=[]`.

- [ ] **Step 5: Validate watch fields and counts**

Read:

```python
watch_candidates = _mapping_rows(ai_brief_report.get("watch_candidates"))
watch_tickers = string_list(ai_brief_report.get("watch_tickers"))
```

Add mismatches:

```python
if watch_tickers != entry_context.expected_watch_tickers:
    issues.append(
        AiBriefRecommendationEvalIssue(
            code="watch_tickers_mismatch",
            severity="FAIL",
            message="AI brief watch_tickers must match expected watch-only tickers",
        )
    )
```

Add `_watch_candidate_ticker_issues` mirroring `_recommendation_ticker_issues`, but checking membership in `expected_watch_tickers`, duplicate tickers, and `action == "WATCH"`.

Include summary count:

```python
"watch_count": len(watch_tickers),
```

Include summary output:

```python
"expected_watch_count": len(entry_context.expected_watch_tickers),
"watch_count": len(watch_candidates),
```

- [ ] **Step 6: Update fixtures for new-contract tests without breaking legacy tests**

Keep `tests/fixtures/ai_brief_eval/ai-brief.good.json` legacy-compatible by not adding watch fields if existing tests use it for legacy behavior. Add new inline expanded fixtures through test helpers from Step 1. Only update `tests/fixtures/ai_brief_eval/entry.us.json` if an existing test explicitly expects current entry report fields; when updating, add `entry_state: "READY"`, `entry_price_status: "available"`, and empty `reasons: []` to ENTER rows, and portfolio/risk/trigger reasons only in new inline tests.

- [ ] **Step 7: Run evaluator suite**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_eval.py -q
```

Expected: pass.

- [ ] **Step 8: Commit evaluator contract**

Run:

```bash
git add sab/ai_brief_eval.py tests/test_ai_brief_eval.py tests/fixtures/ai_brief_eval/entry.us.json tests/fixtures/ai_brief_eval/ai-brief.good.json
git commit -m "feat(ai-brief): 평가기에 후보 역할 계약 추가" -m "AI Brief evaluator가 expanded artifact에서는 shared classifier 기준으로 eligible/watch/excluded 후보를 검증하고 legacy artifact는 기존 ENTER-only 계약으로 평가하도록 확장합니다."
```

## Task 7: Scheduled Source Provider Chain Configuration

**Files:**
- Modify: `sab/scheduler/runner.py`
- Modify: `tests/test_scheduled_ai_brief_runner.py`
- Modify: `.github/workflows/ai-brief.yml`
- Modify: `tests/test_ai_brief_workflow.py`

- [ ] **Step 1: Write failing scheduler tests**

Update `_SCHEDULED_SOURCE_ENV_KEYS` in `tests/test_scheduled_ai_brief_runner.py`:

```python
_SCHEDULED_SOURCE_ENV_KEYS = (
    "AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR",
    "AI_BRIEF_SOURCE_PROVIDER_CHAIN_US",
    "AI_BRIEF_SOURCE_PROVIDER_CHAIN",
    "AI_BRIEF_SOURCE_PROVIDER_KR",
    "AI_BRIEF_SOURCE_PROVIDER_US",
    "AI_BRIEF_SOURCE_PROVIDER",
    "AI_BRIEF_SOURCE_API_URL_KR",
    "AI_BRIEF_SOURCE_API_URL_US",
    "AI_BRIEF_SOURCE_API_URL",
)
```

Add tests near existing source-provider env tests:

```python
def test_runner_source_provider_chain_env_wins_over_single_provider_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AI_BRIEF_SOURCE_PROVIDER_CHAIN_US",
        "finnhub,benzinga-news,polygon-news",
    )
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_US", "finnhub")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-chain-env",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] is None
    assert pipeline.calls[0][1]["source_provider_chain"] == (
        "finnhub",
        "benzinga-news",
        "polygon-news",
    )


def test_runner_source_provider_request_overrides_chain_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_BRIEF_SOURCE_PROVIDER_CHAIN_US", "finnhub,benzinga-news")
    runner, _state, pipeline, _storage, _notifier = _runner()

    result = runner.run(
        ScheduledAiBriefRequest(
            market="US",
            schedule_role="local-primary",
            runner_role="local-primary",
            scheduled_tick="0810",
            attempt_id="attempt-source-provider-override-chain",
            source_provider="polygon-news",
        )
    )

    assert result.status == "completed"
    assert pipeline.calls[0][1]["source_provider"] == "polygon-news"
    assert pipeline.calls[0][1]["source_provider_chain"] is None
```

Add workflow test in `tests/test_ai_brief_workflow.py`:

```python
def test_ai_brief_workflow_injects_chain_provider_secrets() -> None:
    workflow = Path(".github/workflows/ai-brief.yml").read_text(encoding="utf-8")

    assert "DEFAULT_SOURCE_PROVIDER_CHAIN_US" in workflow
    assert "source_provider_chain" in workflow
    assert "contains(needs.resolve_context.outputs.source_provider_chain, 'finnhub')" in workflow
    assert "contains(needs.resolve_context.outputs.source_provider_chain, 'benzinga-news')" in workflow
    assert "contains(needs.resolve_context.outputs.source_provider_chain, 'polygon-news')" in workflow
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_scheduled_ai_brief_runner.py::test_runner_source_provider_chain_env_wins_over_single_provider_env tests/test_scheduled_ai_brief_runner.py::test_runner_source_provider_request_overrides_chain_env tests/test_ai_brief_workflow.py::test_ai_brief_workflow_injects_chain_provider_secrets -q
```

Expected: fail because scheduler context has no chain field and workflow has no chain output.

- [ ] **Step 3: Extend scheduler source context**

In `sab/scheduler/runner.py`, extend `SchedulerPipeline.run` and `DefaultScheduledPipeline.run`:

```python
source_provider_chain: tuple[str, ...] | None = None,
```

Extend `_ScheduledSourceContext`:

```python
source_provider_chain: tuple[str, ...] | None
source_provider_chain_origin: str
```

Add origins:

```python
_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE = "none"
_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_MARKET = "env_market"
_SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_GLOBAL = "env_global"
```

Add chain env resolution:

```python
def _scheduled_source_provider_chain_candidate(
    *,
    market: str,
    source_provider: str | None,
) -> tuple[tuple[str, ...] | None, str]:
    if _normalize_optional_source_provider(source_provider):
        return None, _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE
    market_chain = parse_source_provider_chain(
        _optional_env(f"AI_BRIEF_SOURCE_PROVIDER_CHAIN_{market}")
    )
    if market_chain:
        return market_chain, _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_MARKET
    global_chain = parse_source_provider_chain(_optional_env("AI_BRIEF_SOURCE_PROVIDER_CHAIN"))
    if global_chain:
        return global_chain, _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_ENV_GLOBAL
    return None, _SCHEDULED_SOURCE_PROVIDER_CHAIN_ORIGIN_NONE
```

Import `parse_source_provider_chain` from `sab.ai_brief_source_chain`.

- [ ] **Step 4: Validate and pass chain to pipeline**

In `_resolve_scheduled_source_context`, resolve chain before single-provider env:

```python
resolved_chain, chain_origin = _scheduled_source_provider_chain_candidate(
    market=market,
    source_provider=source_provider,
)
if resolved_chain:
    source_context = _ScheduledSourceContext(
        source_provider=None,
        source_provider_chain=resolved_chain,
        source_provider_origin=_SCHEDULED_SOURCE_PROVIDER_ORIGIN_NONE,
        source_provider_chain_origin=chain_origin,
        source_api_url=None,
        source_api_url_origin=_SCHEDULED_SOURCE_API_URL_ORIGIN_NONE,
        source_api_url_configured=False,
    )
    _validate_scheduled_source_context(source_context)
    return source_context
```

Update validation:

```python
providers = source_context.source_provider_chain or (
    (source_context.source_provider,) if source_context.source_provider else ()
)
for provider in providers:
    if provider not in _ALLOWED_SCHEDULED_SOURCE_PROVIDERS:
        raise _ScheduledSourceConfigError(
            "unsupported scheduled AI brief source provider",
            error_code="unsupported_source_provider",
            source_context=source_context,
        )
```

Pass to `_start_locked_pipeline`, `_run_locked_pipeline`, and `self._pipeline.run(...)`:

```python
source_provider_chain=source_context.source_provider_chain,
```

In `DefaultScheduledPipeline.run_ai_brief` call:

```python
source_provider_chain=",".join(source_provider_chain)
if source_provider_chain
else None,
```

Add the matching optional parameter to `run_ai_brief` in Task 3 if it is not already present.

- [ ] **Step 5: Update scheduler logging without exposing secrets**

Add chain fields to `_log_source_context_resolved`:

```python
"source_provider_chain": ",".join(source_context.source_provider_chain or ()),
"source_provider_chain_origin": source_context.source_provider_chain_origin,
```

Do not log source API URLs or token values.

- [ ] **Step 6: Update GitHub Actions scheduled source resolution**

In `.github/workflows/ai-brief.yml` Resolve schedule context env, add:

```yaml
DEFAULT_SOURCE_PROVIDER_CHAIN: ${{ vars.AI_BRIEF_SOURCE_PROVIDER_CHAIN }}
DEFAULT_SOURCE_PROVIDER_CHAIN_US: ${{ vars.AI_BRIEF_SOURCE_PROVIDER_CHAIN_US }}
```

In the Python context script, compute:

```python
source_provider_chain = (
    os.environ.get("DEFAULT_SOURCE_PROVIDER_CHAIN_US")
    or os.environ.get("DEFAULT_SOURCE_PROVIDER_CHAIN")
    or ""
).strip().lower()
if source_provider:
    source_provider_chain = ""
source_provider_chain = _single_line_output_value(
    "source_provider_chain",
    source_provider_chain,
)
```

Write:

```python
out.write(f"source_provider_chain={source_provider_chain}\n")
```

Add job output:

```yaml
source_provider_chain: ${{ steps.context.outputs.source_provider_chain }}
```

In scheduled job env, add:

```yaml
SOURCE_PROVIDER_CHAIN: ${{ needs.resolve_context.outputs.source_provider_chain }}
AI_BRIEF_SOURCE_PROVIDER_CHAIN_US: ${{ needs.resolve_context.outputs.source_provider_chain }}
```

Change provider secrets to inject if either single provider equals provider or chain contains provider:

```yaml
FINNHUB_API_KEY: ${{ (needs.resolve_context.outputs.source_provider == 'finnhub' || contains(needs.resolve_context.outputs.source_provider_chain, 'finnhub')) && secrets.FINNHUB_API_KEY || '' }}
POLYGON_API_KEY: ${{ (needs.resolve_context.outputs.source_provider == 'polygon-news' || contains(needs.resolve_context.outputs.source_provider_chain, 'polygon-news')) && secrets.POLYGON_API_KEY || '' }}
BENZINGA_API_TOKEN: ${{ (needs.resolve_context.outputs.source_provider == 'benzinga-news' || contains(needs.resolve_context.outputs.source_provider_chain, 'benzinga-news')) && secrets.BENZINGA_API_TOKEN || '' }}
```

Apply the same pattern for Alpha Vantage, Marketaux, and Naver.

- [ ] **Step 7: Run scheduler/workflow tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_scheduled_ai_brief_runner.py::test_runner_source_provider_chain_env_wins_over_single_provider_env tests/test_scheduled_ai_brief_runner.py::test_runner_source_provider_request_overrides_chain_env tests/test_ai_brief_workflow.py::test_ai_brief_workflow_injects_chain_provider_secrets -q
```

Expected: pass.

- [ ] **Step 8: Commit scheduled chain configuration**

Run:

```bash
git add sab/scheduler/runner.py tests/test_scheduled_ai_brief_runner.py .github/workflows/ai-brief.yml tests/test_ai_brief_workflow.py
git commit -m "feat(ai-brief): scheduled source provider chain 설정 추가" -m "Scheduled AI Brief가 chain env를 단일 provider보다 우선 해석하고 GitHub Actions가 chain 구성 provider의 secret을 주입하도록 확장합니다."
```

## Task 8: Notification And Web Display

**Files:**
- Modify: `sab/report/notification_text.py`
- Modify: `tests/test_notification_text.py`
- Modify: `web/src/components/reports/use-reports-state.ts`
- Modify: `web/src/components/reports/report-detail.tsx`
- Modify: `web/src/lib/__tests__/report-detail-component.test.ts`

- [ ] **Step 1: Write failing notification/web tests**

Add notification tests:

```python
def test_build_ai_brief_telegram_report_text_includes_watch_candidates() -> None:
    report = {
        "generated_at": "2026-06-15T12:00:00+00:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 1,
            "watch_count": 1,
            "recommendation_count": 0,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "eligible_tickers": ["AAPL.NAS"],
        "watch_tickers": ["MSFT.NAS"],
        "recommendations": [],
        "watch_candidates": [
            {
                "ticker": "MSFT.NAS",
                "action": "WATCH",
                "reason": "trigger pending",
                "retrigger_conditions": ["price above trigger"],
                "sources": [],
            }
        ],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(report=report, run_url="https://run")

    assert "Watch 후보 1건" in text
    assert "MSFT.NAS | WATCH | trigger pending" in text
```

Add web detail test:

```ts
it("renders AI brief watch candidates and source provider summary", () => {
  const detail: ReportJson = {
    schema: "sab.ai_brief.v1",
    type: "ai_brief",
    generated_at: "2026-06-15T12:00:00+00:00",
    market: "US",
    model_provider: "openai",
    model_name: "gpt-test",
    brief_state: "NEEDS_REVIEW_WATCH_ONLY",
    brief_reason: "watch_only_trigger_pending",
    source_entry_report: "2026-06-15.entry.json",
    summary: {
      preselected_count: 0,
      watch_count: 1,
      recommendation_count: 0,
      source_issue_count: 0,
      system_issue_count: 0,
    },
    eligible_tickers: [],
    watch_tickers: ["MSFT.NAS"],
    recommendations: [],
    watch_candidates: [
      {
        ticker: "MSFT.NAS",
        action: "WATCH",
        reason: "trigger pending",
        retrigger_conditions: ["price above trigger"],
        sources: [{ title: "MSFT source", url: "https://example.test/msft" }],
      },
    ],
    source_provider_summary: {
      chain: ["finnhub", "benzinga-news"],
      providers: [
        { provider: "finnhub", status: "success", covered: 0, total: 1 },
        { provider: "benzinga-news", status: "success", covered: 0, total: 1 },
      ],
      final: {
        recommendable_covered: 0,
        recommendable_total: 0,
        watch_covered: 0,
        watch_total: 1,
      },
    },
    source_issues: [],
    system_issues: [],
  };

  const html = renderReportDetail(detail);

  expect(html).toContain("Watch candidates (1)");
  expect(html).toContain("MSFT.NAS");
  expect(html).toContain("trigger pending");
  expect(html).toContain("price above trigger");
  expect(html).toContain("Source providers");
  expect(html).toContain("finnhub");
  expect(html).toContain("benzinga-news");
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_includes_watch_candidates -q
pnpm --dir web run test -- --run web/src/lib/__tests__/report-detail-component.test.ts
```

Expected: fail because watch candidates and provider summary are not displayed.

- [ ] **Step 3: Add watch counts to notification helper**

Extend `_AiBriefCounts` with `watch_count` and `watch_candidates`.

In `_ai_brief_counts`:

```python
watch_raw = _as_list(report.get("watch_candidates"))
watch_candidates = [row for row in watch_raw if isinstance(row, dict)]
watch_ticker_count = len(
    [item for item in _as_list(report.get("watch_tickers")) if _safe_str(item)]
)
watch_count = max(
    _safe_int(summary.get("watch_count"), default=0),
    _safe_int(report.get("watch_count"), default=0),
    watch_ticker_count,
    len(watch_candidates),
)
```

Return these fields.

- [ ] **Step 4: Display watch candidates in Telegram and Slack**

In Slack summary, add:

```python
f"watch_count={counts.watch_count}",
```

In Telegram after vetoed candidates:

```python
    watch_total = len(counts.watch_candidates)
    watch_shown = min(watch_total, max(max_items, 0), 3)
    if watch_total > 0:
        lines.append(f"Watch 후보 {watch_total}건")
        for row in counts.watch_candidates[:watch_shown]:
            ticker = _safe_str(row.get("ticker"), default="-")
            action = _safe_str(row.get("action"), default="WATCH").upper()
            reason = _safe_single_line(row.get("reason"), default="-")
            lines.append(f"- {ticker} | {action} | {reason}")
        extra = watch_total - watch_shown
        if extra > 0:
            lines.append(f"Watch 외 {extra}건")
```

- [ ] **Step 5: Pass watch rows to `ReportDetail`**

In `web/src/components/reports/use-reports-state.ts`, add:

```ts
const aiBriefWatchRows = useMemo(
  () => asRecordArray(selectedDetail?.watch_candidates),
  [selectedDetail],
);
```

Extend props and pass this array to `ReportDetail`.

- [ ] **Step 6: Render watch candidates and source provider summary**

In `web/src/components/reports/report-detail.tsx`, add props:

```ts
aiBriefWatchRows: ReportJson[];
```

Read:

```ts
const sourceProviderSummary = asRecord(detail?.source_provider_summary);
const sourceProviderRows = asRecordArray(sourceProviderSummary?.providers);
```

Render after vetoed candidates:

```tsx
{aiBriefWatchRows.length > 0 && (
  <div className={styles.tableWrap}>
    <h3 className={styles.sectionTitle}>
      Watch candidates ({aiBriefWatchRows.length})
    </h3>
    <table>
      <thead>
        <tr>
          <th>Ticker</th>
          <th>Action</th>
          <th>Reason</th>
          <th>Re-trigger</th>
          <th>Sources</th>
        </tr>
      </thead>
      <tbody>
        {aiBriefWatchRows.map((row, idx) => (
          <tr key={`${String(row.ticker ?? "-")}-${idx}`}>
            <td data-label="Ticker">{String(row.ticker ?? "-")}</td>
            <td data-label="Action">{String(row.action ?? "WATCH")}</td>
            <td data-label="Reason">{String(row.reason ?? "-")}</td>
            <td data-label="Re-trigger">
              {asStringArray(row.retrigger_conditions).join(" · ") || "-"}
            </td>
            <td data-label="Sources">{formatSources(row.sources)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)}
```

Render source providers:

```tsx
{sourceProviderRows.length > 0 && (
  <div className={styles.tableWrap}>
    <h3 className={styles.sectionTitle}>Source providers</h3>
    <table>
      <thead>
        <tr>
          <th>Provider</th>
          <th>Status</th>
          <th>Covered</th>
          <th>Total</th>
        </tr>
      </thead>
      <tbody>
        {sourceProviderRows.map((row, idx) => (
          <tr key={`${String(row.provider ?? "-")}-${idx}`}>
            <td data-label="Provider">{String(row.provider ?? "-")}</td>
            <td data-label="Status">{String(row.status ?? "-")}</td>
            <td data-label="Covered">{String(row.covered ?? "-")}</td>
            <td data-label="Total">{String(row.total ?? "-")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)}
```

- [ ] **Step 7: Run notification/web tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_includes_watch_candidates tests/test_notification_text.py::test_build_ai_brief_slack_summary_text_counts_vetoed_candidates -q
pnpm --dir web run test -- --run web/src/lib/__tests__/report-detail-component.test.ts web/src/components/reports/__tests__/ai-brief-state.test.ts
```

Expected: pass.

- [ ] **Step 8: Commit display contract**

Run:

```bash
git add sab/report/notification_text.py tests/test_notification_text.py web/src/components/reports/use-reports-state.ts web/src/components/reports/report-detail.tsx web/src/lib/__tests__/report-detail-component.test.ts
git commit -m "feat(ai-brief): watch 후보 표시 추가" -m "알림과 웹 리포트 상세에서 watch-only 후보와 source provider coverage를 추천과 분리해 보여주도록 표시 계약을 확장합니다."
```

## Task 9: Docs, Contract Sweep, And Quality Gates

**Files:**
- Modify: `docs/STRATEGY.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/operations.md`
- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Modify: `docs/ai-brief-us-source-provider-decision.md`
- Optional modify: `docs/api.md` if CLI/env behavior text is stale

- [ ] **Step 1: Update strategy docs**

In `docs/STRATEGY.md` section `7.1.1 AI Brief report`, replace ENTER-only wording with:

```markdown
- `sab ai-brief`는 전략 신호 생성기가 아니라 `sab entry` 결과의 후속 요약/판단 레이어입니다.
- AI Brief 후보는 `entry_state=READY`, `entry_price_status=available` 행에서 파생됩니다.
  - `recommendable`: `ENTER`, `portfolio market cap reached`로 막힌 `SKIP`, 또는 `risk_alignment=tight_stop_vs_volatility` `REVIEW`.
  - `watch_only`: `hybrid trigger guard failed`로 막힌 `SKIP`.
  - 그 외 행은 `excluded_candidates[]`에 남고 source/model ranking에 들어가지 않습니다.
- `eligible_tickers[]`는 recommendable 후보 중 preselection cap을 통과한 ticker이며, `watch_tickers[]`는 추천 ranking과 분리된 watch-only ticker입니다.
- provider 호출 전 recommendable 후보는 최대 5개로 제한하며, watch-only 후보는 `watch_candidates[]`로만 표시됩니다. 최종 `recommendations[]`는 최대 3개이며 watch-only ticker를 포함할 수 없습니다.
```

Add source chain wording:

```markdown
- Scheduled US AI Brief는 `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US=finnhub,benzinga-news,polygon-news`를 사용할 수 있습니다. Chain 설정은 시장별 chain, 전역 chain, 단일 provider 순서로 해석되며, 단일 provider CLI 경로는 계속 지원됩니다.
- `source_provider_summary`는 provider별 requested/covered/status와 최종 recommendable/watch coverage를 기록합니다. Provider가 성공했지만 특정 ticker source가 0건이면 ticker-level `*_source_no_results` issue로 남깁니다.
```

- [ ] **Step 2: Update architecture and operations docs**

In `docs/ARCHITECTURE.md`, update scheduled source fallback text:

```markdown
Scheduled source provider는 시장별 `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR`/`AI_BRIEF_SOURCE_PROVIDER_CHAIN_US`, 전역 `AI_BRIEF_SOURCE_PROVIDER_CHAIN`, 시장별 단일 provider, 전역 단일 provider, 시장별/전역 `AI_BRIEF_SOURCE_API_URL`, `none` 순서로 fallback합니다.
```

In `docs/operations.md`, replace scheduled source provider table with:

```markdown
| Market | Preferred chain variable | Current documented default | Single-provider fallback |
| --- | --- | --- | --- |
| KR | `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR` | `naver-news` | `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news` |
| US | `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US` | `finnhub,benzinga-news,polygon-news` | `AI_BRIEF_SOURCE_PROVIDER_US=finnhub` |
| fallback | `AI_BRIEF_SOURCE_PROVIDER_CHAIN` | provider-specific | `AI_BRIEF_SOURCE_PROVIDER` |
```

Add diagnostic instruction:

```markdown
When Benzinga returns zero rows, inspect `source_provider_summary.providers[]` and ticker-level `benzinga_news_source_no_results` issues. Treat HTTP 429 on Polygon as provider quota/rate-limit evidence when `source_provider_summary.providers[].code` is `http_429`.
```

- [ ] **Step 3: Update configuration references**

Add these rows to `docs/configuration.md` and `docs/config-reference.md`:

```markdown
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN_KR` | no | none | `naver-news` | scheduled workflow/scheduler | KR scheduled source provider chain. Market-specific chain wins over global chain and single-provider env. |
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US` | no | none | `finnhub,benzinga-news,polygon-news` | scheduled workflow/scheduler | US scheduled source provider chain. Provider secrets must be available for each configured provider. |
| `AI_BRIEF_SOURCE_PROVIDER_CHAIN` | no | none | `finnhub,benzinga-news` | scheduled workflow/scheduler | Global source provider chain fallback. |
```

In `docs/ai-brief-us-source-provider-decision.md`, add a 2026-06-15 update noting:

```markdown
2026-06-15 update: keep Finnhub first for US scheduled coverage, retain Benzinga as incremental provider despite observed 0/7 trade-relevant coverage on the incident set, and place Polygon late because a configured key returned HTTP 429 in live testing.
```

- [ ] **Step 4: Run docs/static tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py tests/test_ai_brief_workflow.py -q
```

Expected: pass.

- [ ] **Step 5: Run focused Python and web suites**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_candidates.py tests/test_ai_brief_source_chain.py tests/test_ai_brief_providers.py tests/test_ai_brief.py tests/test_ai_brief_report.py tests/test_ai_brief_eval.py tests/test_scheduled_ai_brief_runner.py tests/test_notification_text.py -q
pnpm --dir web run test -- --run web/src/components/reports/__tests__/ai-brief-state.test.ts web/src/lib/__tests__/report-detail-component.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 6: Run full recommended gates**

Run:

```bash
just quality
just ci-web
```

Expected: both commands exit 0. If `pnpm` is missing from `PATH`, rerun through `mise exec -- just ci-web`.

- [ ] **Step 7: Commit docs and final sweep**

Run:

```bash
git add docs/STRATEGY.md docs/ARCHITECTURE.md docs/operations.md docs/configuration.md docs/config-reference.md docs/ai-brief-us-source-provider-decision.md docs/api.md
git commit -m "docs(ai-brief): 후보 확장과 source chain 운영 문서화" -m "AI Brief recommendable/watch-only 후보 계약과 scheduled source provider chain 진단 절차를 전략, 아키텍처, 운영 문서에 반영합니다."
```

If `docs/api.md` is unchanged, omit it from `git add`.

## Final Verification Checklist

- [ ] `rg -n "entries\\[\\]\\.action == \"ENTER\"|ENTER 후보" docs sab web tests` shows no stale statement that AI Brief only reviews ENTER rows, except legacy-test names or explicit legacy compatibility text.
- [ ] `rg -n "AI_BRIEF_SOURCE_PROVIDER_CHAIN" docs .github sab tests` shows chain config in docs, workflow, scheduler, and tests.
- [ ] `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_candidates.py tests/test_ai_brief_source_chain.py tests/test_ai_brief_providers.py tests/test_ai_brief.py tests/test_ai_brief_report.py tests/test_ai_brief_eval.py tests/test_scheduled_ai_brief_runner.py tests/test_notification_text.py -q` exits 0.
- [ ] `pnpm --dir web run test -- --run web/src/components/reports/__tests__/ai-brief-state.test.ts web/src/lib/__tests__/report-detail-component.test.ts` exits 0.
- [ ] `just quality` exits 0.
- [ ] `just ci-web` exits 0.
- [ ] `git diff --stat` is focused on AI Brief candidate/source/provider/evaluator/display/docs files.
