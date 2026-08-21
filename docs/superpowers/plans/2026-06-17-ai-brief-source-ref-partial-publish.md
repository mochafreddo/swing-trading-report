# AI Brief Source Ref Partial Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking; this artifact now marks completed steps with `- [x]`.

**Goal:** Make AI Brief model outputs choose source references instead of re-creating source objects, and allow scheduled partial publish when candidate-level source-ref errors can be isolated.

**Architecture:** Build a request-local source catalog in `sab/ai_brief_providers.py`, send `source_id` values to OpenAI, accept `source_refs` in structured output, and restore canonical `sources[]` rows in local code. Treat whole-result contract errors as provider failures, but isolate recommendation/watch source-ref errors to the affected candidate before the existing artifact writer and quality gate run.

**Tech Stack:** Python 3.14, pytest, `uv`, existing `sab` package modules, local JSON report artifacts, scheduled runner quality gate.

---

## Implementation Status

Status: Implemented and verified on 2026-06-18.

Final branch commits include the source-ref model contract, recommendation/watch candidate isolation, regression coverage, documentation updates, contract hardening for ref item/rank/duplicate cases, and the final source URL allowlist simplification.

Verification:

- `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py -q` -> 28 passed.
- `just quality` -> ruff, format check, mypy, and 1843 pytest tests passed.

Implemented hardening beyond the initial plan:

- `source_refs[]` must be a list of non-empty strings, may contain at most 3 refs, and must not contain duplicates after trimming.
- Raw recommendation `rank` must be an integer, not bool or float, before local re-ranking after candidate drops.
- Source URL allowlists are now derived directly as `ticker -> set[url]` for provider result validation.

## Scope Check

This is one implementation slice. It touches one subsystem, AI Brief generation, with related tests and docs. The wrapper `scheduler_container_failed` duplicate alert is intentionally not implemented here; it remains a follow-up item from the design spec.

## File Structure

- Modify `sab/ai_brief_providers.py`
  - Add request-local source catalog helpers.
  - Change OpenAI request schema from returned `sources[]` objects to returned `source_refs[]`.
  - Resolve model refs back to canonical source rows.
  - Isolate source-ref errors per recommendation/watch candidate.
- Modify `tests/test_ai_brief_providers.py`
  - Update existing OpenAI fake responses to use `source_refs`.
  - Add unit coverage for source IDs, valid ref resolution, bad recommendation ref drop, bad watch ref fallback, and rank re-normalization.
- Modify `tests/test_ai_brief.py`
  - Update integration fake OpenAI responses to `source_refs`.
  - Add a regression test for the 2026-06-17 failure shape.
- Modify `tests/test_scheduled_ai_brief_runner.py`
  - Add/adjust coverage that a quality `WARN` after partial isolation still returns a pipeline result, while `FAIL` still blocks.
- Modify `docs/STRATEGY.md`
  - Document the source-ref model boundary contract.
- Modify `docs/ARCHITECTURE.md`
  - Document source provider → source catalog → model refs → canonical restore.
- Modify `docs/operations.md`
  - Document `model_source_ref_*` diagnostics and partial publish behavior.

## Task 1: Switch OpenAI Boundary To Source Refs

**Files:**
- Modify: `tests/test_ai_brief_providers.py`
- Modify: `sab/ai_brief_providers.py`

- [x] **Step 1: Write failing provider payload/schema test**

Add this test near `test_openai_payload_separates_recommendable_and_watch_candidates` in `tests/test_ai_brief_providers.py`:

```python
def test_openai_payload_adds_source_ids_and_schema_uses_source_refs() -> None:
    session = _CapturingSession(
        {
            "recommendations": [],
            "vetoed_candidates": [],
            "watch_candidates": [
                {
                    "ticker": "MSFT.NAS",
                    "action": "WATCH",
                    "reason": "trigger pending",
                    "retrigger_conditions": ["price back above trigger"],
                    "source_refs": ["MSFT.NAS:1"],
                }
            ],
            "source_issues": [],
        }
    )
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=session,
    )

    provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[_candidate("MSFT.NAS", role="watch_only")],
    )

    request = session.requests[0]["json"]
    assert isinstance(request, dict)
    user_payload = json.loads(str(request["input"][1]["content"]))
    recommendation_source = user_payload["recommendable_candidates"][0]["sources"][0]
    watch_source = user_payload["watch_candidates"][0]["sources"][0]
    assert recommendation_source["source_id"] == "AAPL.NAS:1"
    assert watch_source["source_id"] == "MSFT.NAS:1"

    schema = request["text"]["format"]["schema"]
    recommendation_props = schema["properties"]["recommendations"]["items"]["properties"]
    watch_props = schema["properties"]["watch_candidates"]["items"]["properties"]
    assert "source_refs" in recommendation_props
    assert "source_refs" in watch_props
    assert "sources" not in recommendation_props
    assert "sources" not in watch_props
```

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py::test_openai_payload_adds_source_ids_and_schema_uses_source_refs -q
```

Expected: FAIL because model input lacks `source_id` and the schema still exposes `sources`.

- [x] **Step 3: Add source catalog and model-facing candidates**

In `sab/ai_brief_providers.py`, add these helpers after `_as_provider_mapping_rows`:

```python
def _source_id_for(ticker: str, index: int) -> str:
    return f"{ticker}:{index}"


class _SourceReferenceCatalog:
    def __init__(self, candidates: list[dict[str, object]]) -> None:
        self._sources_by_ticker: dict[str, dict[str, dict[str, object]]] = {}
        for candidate in candidates:
            ticker = str(candidate.get("ticker") or "").strip()
            if not ticker:
                continue
            rows_by_id: dict[str, dict[str, object]] = {}
            for index, source in enumerate(_candidate_sources(candidate), start=1):
                source_id = _source_id_for(ticker, index)
                rows_by_id[source_id] = source
            self._sources_by_ticker[ticker] = rows_by_id

    def model_candidates(
        self, candidates: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        model_rows: list[dict[str, object]] = []
        for candidate in candidates:
            ticker = str(candidate.get("ticker") or "").strip()
            sources = [
                {"source_id": source_id, **source}
                for source_id, source in self._sources_by_ticker.get(
                    ticker, {}
                ).items()
            ]
            model_rows.append({**candidate, "sources": sources})
        return model_rows

    def has_sources_for(self, ticker: str) -> bool:
        return bool(self._sources_by_ticker.get(ticker))

    def sources_for_refs(
        self,
        *,
        ticker: str,
        source_refs: list[str],
    ) -> tuple[list[dict[str, object]], list[str]]:
        rows_by_id = self._sources_by_ticker.get(ticker, {})
        resolved: list[dict[str, object]] = []
        invalid_refs: list[str] = []
        for source_ref in source_refs:
            source = rows_by_id.get(source_ref)
            if source is None:
                invalid_refs.append(source_ref)
                continue
            resolved.append(dict(source))
        return resolved, invalid_refs
```

In `OpenAiBriefProvider.build_recommendations`, create catalogs before the request:

```python
        recommendable_source_catalog = _SourceReferenceCatalog(recommendable_candidates)
        watch_source_catalog = _SourceReferenceCatalog(watch_candidates)
        request_payload = _build_openai_request_payload(
            model_name=self.model_name,
            recommendable_candidates=recommendable_source_catalog.model_candidates(
                recommendable_candidates
            ),
            watch_candidates=watch_source_catalog.model_candidates(watch_candidates),
        )
```

Pass the catalogs into `_normalize_openai_provider_result`:

```python
            recommendable_source_catalog=recommendable_source_catalog,
            watch_source_catalog=watch_source_catalog,
```

Update `_normalize_openai_provider_result` signature:

```python
def _normalize_openai_provider_result(
    parsed: Mapping[str, Any],
    *,
    recommendable_candidates: list[dict[str, object]],
    watch_candidates: list[dict[str, object]],
    recommendable_source_rows_by_ticker: Mapping[str, Mapping[str, dict[str, object]]],
    watch_source_rows_by_ticker: Mapping[str, Mapping[str, dict[str, object]]],
    recommendable_source_catalog: _SourceReferenceCatalog,
    watch_source_catalog: _SourceReferenceCatalog,
) -> AiBriefProviderResult:
```

- [x] **Step 4: Change OpenAI schema from `sources` to `source_refs`**

In `_build_openai_request_payload`, extend the system prompt sentence:

```python
                    "Only cite source_refs supplied in each candidate's "
                    "sources[].source_id list; do not return source title, url, "
                    "or published_at fields. "
```

In `_openai_result_schema`, replace recommendation `sources` with `source_refs`. The recommendation `required` list must become:

```python
                    "required": [
                        "ticker",
                        "rank",
                        "confidence",
                        "rationale",
                        "checklist",
                        "source_refs",
                    ],
```

The recommendation `properties` source field must become:

```python
                        "source_refs": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {"type": "string"},
                        },
```

Replace watch `sources` with `source_refs`. The watch `required` list must become:

```python
                    "required": [
                        "ticker",
                        "action",
                        "reason",
                        "retrigger_conditions",
                        "source_refs",
                    ],
```

The watch `properties` source field must become:

```python
                        "source_refs": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {"type": "string"},
                        },
```

- [x] **Step 5: Run provider payload/schema test**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py::test_openai_payload_adds_source_ids_and_schema_uses_source_refs -q
```

Expected: PASS.

- [x] **Step 6: Commit Task 1**

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py
git commit -m "feat(ai-brief): source ref 모델 계약 추가" -m "OpenAI 입력 후보의 source에 request-local source_id를 붙이고 structured output schema가 source 객체 대신 source_refs를 받도록 전환합니다."
```

## Task 2: Resolve Recommendation Source Refs And Drop Bad Recommendations

**Files:**
- Modify: `tests/test_ai_brief_providers.py`
- Modify: `sab/ai_brief_providers.py`

- [x] **Step 1: Write failing tests for valid refs and bad recommendation refs**

Add these tests before the `_Response` helper in `tests/test_ai_brief_providers.py`:

```python
def test_openai_resolves_recommendation_source_refs_to_canonical_sources() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [
                    {
                        "ticker": "AAPL.NAS",
                        "rank": 1,
                        "confidence": "LOW",
                        "rationale": ["entry setup remains valid"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["AAPL.NAS:1"],
                    }
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[],
    )

    sources = result.recommendations[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "AAPL.NAS source"
    assert sources[0]["url"] == "https://news.example/AAPL.NAS"
    assert sources[0]["published_at"]


def test_openai_drops_recommendation_with_invalid_source_ref_and_reranks() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [
                    {
                        "ticker": "AAPL.NAS",
                        "rank": 1,
                        "confidence": "LOW",
                        "rationale": ["bad source ref"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["AAPL.NAS:404"],
                    },
                    {
                        "ticker": "MSFT.NAS",
                        "rank": 2,
                        "confidence": "LOW",
                        "rationale": ["valid source ref"],
                        "checklist": ["manually confirm price and risk before order"],
                        "source_refs": ["MSFT.NAS:1"],
                    },
                ],
                "vetoed_candidates": [],
                "watch_candidates": [],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[
            _candidate("AAPL.NAS", role="recommendable"),
            _candidate("MSFT.NAS", role="recommendable"),
        ],
        watch_candidates=[],
    )

    assert [row["ticker"] for row in result.recommendations] == ["MSFT.NAS"]
    assert result.recommendations[0]["rank"] == 1
    sources = result.recommendations[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "MSFT.NAS source"
    assert sources[0]["url"] == "https://news.example/MSFT.NAS"
    assert result.source_issues == [
        {
            "ticker": "AAPL.NAS",
            "code": "model_source_ref_invalid",
            "severity": "WARN",
            "message": "model returned source_refs not present in candidate.sources",
        }
    ]
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_resolves_recommendation_source_refs_to_canonical_sources \
  tests/test_ai_brief_providers.py::test_openai_drops_recommendation_with_invalid_source_ref_and_reranks \
  -q
```

Expected: FAIL because `_normalize_openai_provider_result` still reads `sources`.

- [x] **Step 3: Add source-ref parsing and issue helpers**

In `sab/ai_brief_providers.py`, add these helpers after `_provider_source_issue_tickers`:

```python
def _provider_source_refs(value: object, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise AiBriefProviderContractError(f"OpenAI output {field_name} must be a list")
    source_refs: list[str] = []
    seen_source_refs: set[str] = set()
    for idx, raw_ref in enumerate(value):
        if not isinstance(raw_ref, str):
            raise AiBriefProviderContractError(
                f"OpenAI output {field_name}[{idx}] must be a string"
            )
        source_ref = raw_ref.strip()
        if not source_ref:
            raise AiBriefProviderContractError(
                f"OpenAI output {field_name}[{idx}] must be a non-empty string"
            )
        if source_ref in seen_source_refs:
            raise AiBriefProviderContractError(
                f"OpenAI output {field_name} must not contain duplicate source_refs"
            )
        seen_source_refs.add(source_ref)
        source_refs.append(source_ref)
    if len(source_refs) > _MAX_SOURCES_PER_TICKER:
        raise AiBriefProviderContractError(
            "OpenAI output source_refs must contain at most "
            f"{_MAX_SOURCES_PER_TICKER} refs"
        )
    return source_refs


def _model_source_issue(
    *,
    ticker: str,
    code: str,
    message: str,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "code": code,
        "severity": "WARN",
        "message": message,
    }
```

Add raw rank validation before source-ref filtering:

```python
def _validate_raw_recommendation_ranks(
    rows: list[dict[str, object]],
) -> None:
    ranks = [row.get("rank") for row in rows]
    expected = list(range(1, len(rows) + 1))
    if ranks != expected:
        raise AiBriefProviderContractError(
            "OpenAI output recommendations[].rank must be contiguous from 1 to N "
            "in recommendation order"
        )
```

- [x] **Step 4: Resolve recommendation refs in normalization**

In `_normalize_openai_provider_result`, parse `source_issues` before the recommendations loop:

```python
    source_issues = _as_provider_mapping_rows(
        parsed.get("source_issues"), field_name="source_issues"
    )
    source_issue_tickers = _provider_source_issue_tickers(source_issues)
    raw_recommendations = _as_provider_mapping_rows(
        parsed.get("recommendations"), field_name="recommendations"
    )
    _validate_raw_recommendation_ranks(raw_recommendations)
```

Replace the current recommendations loop with:

```python
    recommendations: list[dict[str, object]] = []
    for raw_recommendation in raw_recommendations:
        ticker = str(raw_recommendation.get("ticker") or "").strip()
        if ticker not in candidate_by_ticker:
            raise AiBriefProviderContractError(
                f"OpenAI output included ineligible ticker {ticker!r}"
            )
        source_refs = _provider_source_refs(
            raw_recommendation.get("source_refs"),
            field_name="recommendations[].source_refs",
        )
        sources, invalid_refs = recommendable_source_catalog.sources_for_refs(
            ticker=ticker,
            source_refs=source_refs,
        )
        candidate_has_sources = recommendable_source_catalog.has_sources_for(ticker)
        if invalid_refs or (candidate_has_sources and not sources):
            source_issues.append(
                _model_source_issue(
                    ticker=ticker,
                    code="model_source_ref_invalid"
                    if invalid_refs
                    else "model_source_ref_missing",
                    message=(
                        "model returned source_refs not present in candidate.sources"
                        if invalid_refs
                        else "model omitted source_refs for a sourced candidate"
                    ),
                )
            )
            continue
        if not sources and ticker not in source_issue_tickers:
            source_issues.append(
                _model_source_issue(
                    ticker=ticker,
                    code="model_unbacked_recommendation_dropped",
                    message="recommendation was dropped because it was not source-backed",
                )
            )
            continue
        candidate = candidate_by_ticker[ticker]
        recommendations.append(
            {
                "ticker": ticker,
                "name": candidate.get("name"),
                "rank": raw_recommendation.get("rank"),
                "action": "ENTER",
                "confidence": str(
                    raw_recommendation.get("confidence") or "LOW"
                ).upper(),
                "rationale": string_list(raw_recommendation.get("rationale")),
                "checklist": string_list(raw_recommendation.get("checklist")),
                "sources": sources,
                "as_of": _offset_now_iso(),
            }
        )
```

After the loop and before returning `AiBriefProviderResult`, re-rank kept recommendations:

```python
    for rank, recommendation in enumerate(recommendations, start=1):
        recommendation["rank"] = rank
```

Remove the duplicate `source_issues = _as_provider_mapping_rows(...)` assignment that currently appears after the recommendations loop so the augmented list is returned.

- [x] **Step 5: Run targeted provider tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_resolves_recommendation_source_refs_to_canonical_sources \
  tests/test_ai_brief_providers.py::test_openai_drops_recommendation_with_invalid_source_ref_and_reranks \
  -q
```

Expected: PASS.

- [x] **Step 6: Commit Task 2**

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py
git commit -m "fix(ai-brief): 추천 source ref 오류를 후보 단위로 격리" -m "OpenAI 추천 결과의 source_refs를 canonical source로 복원하고 잘못된 ref를 반환한 추천만 제외하도록 provider 정규화 경계를 좁힙니다."
```

## Task 3: Resolve Watch Source Refs With Deterministic Fallback

**Files:**
- Modify: `tests/test_ai_brief_providers.py`
- Modify: `sab/ai_brief_providers.py`

- [x] **Step 1: Write failing watch source-ref fallback tests**

Replace `test_openai_rejects_watch_candidate_unprovided_source_url` in `tests/test_ai_brief_providers.py` with:

```python
def test_openai_replaces_watch_candidate_with_invalid_source_ref_with_fallback() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "WATCH",
                        "reason": "model watch reason",
                        "retrigger_conditions": ["model condition"],
                        "source_refs": ["MSFT.NAS:404"],
                    }
                ],
                "source_issues": [],
            }
        ),
    )

    result = provider.build_recommendations(
        recommendable_candidates=[_candidate("AAPL.NAS", role="recommendable")],
        watch_candidates=[
            _candidate(
                "MSFT.NAS",
                role="watch_only",
                ai_role_reason="entry trigger requires re-confirmation",
            )
        ],
    )

    assert result.watch_candidates[0]["ticker"] == "MSFT.NAS"
    assert result.watch_candidates[0]["action"] == "WATCH"
    assert result.watch_candidates[0]["reason"] == (
        "entry trigger requires re-confirmation"
    )
    assert result.watch_candidates[0]["retrigger_conditions"] == [
        "price must satisfy the original entry trigger again",
        "manual review must confirm source and market context",
    ]
    sources = result.watch_candidates[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "MSFT.NAS source"
    assert sources[0]["url"] == "https://news.example/MSFT.NAS"
    assert result.source_issues == [
        {
            "ticker": "MSFT.NAS",
            "code": "model_watch_source_ref_invalid",
            "severity": "WARN",
            "message": "watch row source_refs were invalid and fallback was used",
        }
    ]
```

Add this valid watch ref test next to it:

```python
def test_openai_resolves_watch_source_refs_to_canonical_sources() -> None:
    provider = OpenAiBriefProvider(
        model_name="gpt-test",
        api_key="test-key",
        timeout_seconds=1.0,
        session=_CapturingSession(
            {
                "recommendations": [],
                "vetoed_candidates": [],
                "watch_candidates": [
                    {
                        "ticker": "MSFT.NAS",
                        "action": "WATCH",
                        "reason": "trigger pending",
                        "retrigger_conditions": ["price back above trigger"],
                        "source_refs": ["MSFT.NAS:1"],
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

    sources = result.watch_candidates[0]["sources"]
    assert isinstance(sources, list)
    assert sources[0]["title"] == "MSFT.NAS source"
    assert sources[0]["url"] == "https://news.example/MSFT.NAS"
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py::test_openai_replaces_watch_candidate_with_invalid_source_ref_with_fallback \
  tests/test_ai_brief_providers.py::test_openai_resolves_watch_source_refs_to_canonical_sources \
  -q
```

Expected: FAIL because watch normalization still expects returned `sources`.

- [x] **Step 3: Add provider-local watch fallback helper**

In `sab/ai_brief_providers.py`, add after `_model_source_issue`:

```python
def _provider_fallback_watch_candidate(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    ticker = str(candidate.get("ticker") or "").strip()
    reason = str(
        candidate.get("ai_role_reason") or "entry trigger is pending re-confirmation"
    ).strip()
    row: dict[str, object] = {
        "ticker": ticker,
        "action": "WATCH",
        "reason": reason,
        "retrigger_conditions": [
            "price must satisfy the original entry trigger again",
            "manual review must confirm source and market context",
        ],
        "sources": _candidate_sources(candidate),
    }
    name = str(candidate.get("name") or "").strip()
    if name:
        row["name"] = name
    return row
```

- [x] **Step 4: Resolve watch refs in normalization**

In `_normalize_openai_provider_result`, replace the watch normalization loop with:

```python
    normalized_watch_candidates: list[dict[str, object]] = []
    for raw_watch in _as_provider_mapping_rows(
        parsed.get("watch_candidates"), field_name="watch_candidates"
    ):
        ticker = str(raw_watch.get("ticker") or "").strip()
        if ticker not in watch_candidate_by_ticker:
            raise AiBriefProviderContractError(
                f"OpenAI output included ineligible watch ticker {ticker!r}"
            )
        source_refs = _provider_source_refs(
            raw_watch.get("source_refs"),
            field_name="watch_candidates.source_refs",
        )
        sources, invalid_refs = watch_source_catalog.sources_for_refs(
            ticker=ticker,
            source_refs=source_refs,
        )
        watch_has_sources = watch_source_catalog.has_sources_for(ticker)
        if invalid_refs or (watch_has_sources and not sources):
            source_issues.append(
                _model_source_issue(
                    ticker=ticker,
                    code="model_watch_source_ref_invalid",
                    message="watch row source_refs were invalid and fallback was used",
                )
            )
            normalized_watch_candidates.append(
                _provider_fallback_watch_candidate(watch_candidate_by_ticker[ticker])
            )
            continue
        normalized_watch_candidates.append(
            {
                "ticker": ticker,
                "action": str(raw_watch.get("action") or "").strip().upper(),
                "reason": str(raw_watch.get("reason") or "").strip(),
                "retrigger_conditions": string_list(
                    raw_watch.get("retrigger_conditions")
                ),
                "sources": sources,
            }
        )
```

- [x] **Step 5: Run full provider test file and update remaining fake responses**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py -q
```

Expected first run: FAIL in older tests whose fake OpenAI output still uses `sources`.

For each failing fake OpenAI response in `tests/test_ai_brief_providers.py`, update returned rows:

```python
"sources": [_source("AAPL.NAS")]
```

to:

```python
"source_refs": ["AAPL.NAS:1"]
```

and:

```python
"sources": []
```

to:

```python
"source_refs": []
```

Keep expected final `result.recommendations[].sources` and `result.watch_candidates[].sources` assertions as `sources[]`; final provider results must still expose canonical source objects.

Run again:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_ai_brief_providers.py -q
```

Expected: PASS.

- [x] **Step 6: Commit Task 3**

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py
git commit -m "fix(ai-brief): watch source ref 오류를 fallback 처리" -m "OpenAI watch 후보의 source_refs가 깨진 경우 provider 전체 실패 대신 deterministic watch 후보를 복원하고 source issue로 진단합니다."
```

## Task 4: Add AI Brief Integration And Scheduled Quality Regression Coverage

**Files:**
- Modify: `tests/test_ai_brief.py`
- Modify: `tests/test_scheduled_ai_brief_runner.py`

- [x] **Step 1: Update OpenAI integration fake outputs to `source_refs`**

In `tests/test_ai_brief.py`, update fake `_OpenAiSession` output payloads so model responses use `source_refs` instead of returned source objects. Apply these exact patterns:

```python
"sources": [],
```

becomes:

```python
"source_refs": [],
```

and:

```python
"sources": [
    {
        "title": "Apple supply chain update",
        "url": "https://example.test/aapl",
        "published_at": _fresh_published_at(),
    }
],
```

becomes:

```python
"source_refs": ["AAPL.NAS:1"],
```

For tests that intentionally assert provider-wide failures unrelated to source refs, keep the same expected `system_issues` behavior after replacing the source field.

- [x] **Step 2: Write 2026-06-17 partial watch regression test**

Add this test after `test_run_ai_brief_openai_provider_writes_structured_recommendation` in `tests/test_ai_brief.py`:

```python
def test_run_ai_brief_openai_invalid_watch_source_ref_uses_partial_publish_artifact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
    source_report = _write_source_report(
        tmp_path,
        sources=[
            {
                "ticker": "AAPL.NAS",
                "title": "Apple supply chain update",
                "url": "https://example.test/aapl",
                "published_at": _fresh_published_at(),
            },
            {
                "ticker": "MSFT.NAS",
                "title": "Microsoft trigger context",
                "url": "https://example.test/msft",
                "published_at": _fresh_published_at(),
            },
        ],
    )
    report_dir = tmp_path / "reports"
    session = _OpenAiSession(
        {
            "recommendations": [
                {
                    "ticker": "AAPL.NAS",
                    "rank": 1,
                    "confidence": "LOW",
                    "rationale": ["source-backed context supports manual review"],
                    "checklist": ["manually confirm price and risk before order"],
                    "source_refs": ["AAPL.NAS:1"],
                }
            ],
            "vetoed_candidates": [],
            "watch_candidates": [
                {
                    "ticker": "MSFT.NAS",
                    "action": "WATCH",
                    "reason": "model returned a watch row with a bad source ref",
                    "retrigger_conditions": ["price back above trigger"],
                    "source_refs": ["MSFT.NAS:404"],
                }
            ],
            "source_issues": [],
        }
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "sab.ai_brief.load_config",
        lambda: SimpleNamespace(report_dir=report_dir.as_posix()),
    )
    monkeypatch.setattr("sab.ai_brief_providers.requests.Session", lambda: session)

    exit_code = run_ai_brief(
        entry_report_path=entry_report.as_posix(),
        buy_report_path=None,
        market="US",
        model_provider="openai",
        model_name="gpt-test",
        model_timeout_seconds=7.5,
        source_provider="local-json",
        source_report_path=source_report.as_posix(),
    )

    assert exit_code == 0
    payload = json.loads(next(report_dir.glob("*.ai-brief.json")).read_text())
    assert payload["recommendations"][0]["ticker"] == "AAPL.NAS"
    assert payload["recommendations"][0]["sources"][0]["url"] == (
        "https://example.test/aapl"
    )
    assert payload["watch_candidates"][0]["ticker"] == "MSFT.NAS"
    assert payload["watch_candidates"][0]["sources"][0]["url"] == (
        "https://example.test/msft"
    )
    assert payload["source_issues"][0]["code"] == "model_watch_source_ref_invalid"
    assert payload["system_issues"] == []
    assert payload["summary"]["source_issue_count"] == 1
    assert payload["brief_state"] == "NEEDS_REVIEW_WEAK_NEWS"
    assert payload["brief_reason"] == "weak_news_coverage"
```

- [x] **Step 3: Run integration regression to verify it fails, then passes**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief.py::test_run_ai_brief_openai_invalid_watch_source_ref_uses_partial_publish_artifact \
  -q
```

Expected before provider implementation is complete: FAIL. After Tasks 1-3 are complete and fake outputs are updated: PASS.

- [x] **Step 4: Add scheduled pipeline WARN-pass regression**

Add this test after the existing quality-gate failure test in `tests/test_scheduled_ai_brief_runner.py`:

```python
def test_default_pipeline_returns_result_when_ai_brief_quality_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_scan(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.buy.json")
        return 0

    def fake_run_entry(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.entry.json")
        return 0

    def fake_run_ai_brief(**kwargs: object) -> int:
        callback = kwargs.get("report_path_callback")
        if callable(callback):
            callback("reports/current.ai-brief.json")
        return 0

    def fake_evaluate_ai_brief_recommendation_report(
        **kwargs: object,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            status="WARN",
            issues=[
                SimpleNamespace(
                    code="ai_brief_source_issue_reported",
                    message="watch source ref fallback was used",
                )
            ],
        )

    monkeypatch.setattr("sab.scheduler.runner.run_scan", fake_run_scan)
    monkeypatch.setattr("sab.scheduler.runner.run_entry", fake_run_entry)
    monkeypatch.setattr("sab.scheduler.runner.run_ai_brief", fake_run_ai_brief)
    monkeypatch.setattr(
        "sab.scheduler.runner.evaluate_ai_brief_recommendation_report",
        fake_evaluate_ai_brief_recommendation_report,
    )
    monkeypatch.setattr(
        "sab.scheduler.runner.SupabaseHoldingsExportConfig.from_env",
        lambda: object(),
    )
    monkeypatch.setattr(
        "sab.scheduler.runner.export_active_holdings_snapshot",
        lambda **_kwargs: 1,
    )
    monkeypatch.setattr(
        "sab.scheduler.runner._default_guard_snapshot",
        lambda _market, _now: _guard(session_state="PRE_OPEN"),
    )

    result = DefaultScheduledPipeline().run(
        market="US",
        session_date="2026-05-28",
        report_date="2026-05-28",
        source_provider=None,
        model_provider="fake",
        dry_run=False,
    )

    assert result.ai_brief_report_path == "reports/current.ai-brief.json"
```

- [x] **Step 5: Run integration and scheduled tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief.py::test_run_ai_brief_openai_provider_writes_structured_recommendation \
  tests/test_ai_brief.py::test_run_ai_brief_openai_invalid_watch_source_ref_uses_partial_publish_artifact \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_raises_when_ai_brief_quality_gate_fails \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_returns_result_when_ai_brief_quality_warns \
  -q
```

Expected: PASS.

- [x] **Step 6: Commit Task 4**

```bash
git add tests/test_ai_brief.py tests/test_scheduled_ai_brief_runner.py
git commit -m "test(ai-brief): source ref partial publish 회귀 보강" -m "OpenAI watch source ref 오류가 system issue 없이 source issue로 격리되고 quality WARN은 scheduled pipeline 결과를 허용하는지 검증합니다."
```

## Task 5: Update Documentation And Run Quality Gates

**Files:**
- Modify: `docs/STRATEGY.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/operations.md`

- [x] **Step 1: Update strategy contract**

In `docs/STRATEGY.md`, near the AI Brief state/source contract section around `brief_state`, add this text:

```markdown
- AI Brief 모델 provider는 source 객체(`title`/`url`/`published_at`)를 신뢰 경계 밖에서 재작성하지 않습니다. Source provider가 만든 canonical source row는 실행 중 request-local `source_id`를 받고, 모델은 `source_refs`만 선택합니다. 최종 artifact에는 로컬 코드가 `source_refs`를 canonical `sources[]` 객체로 복원한 결과만 저장합니다.
- 모델이 특정 후보에 대해 잘못된 `source_refs`를 반환하면 해당 추천은 제외하거나 watch 후보는 deterministic fallback으로 복원하고, `source_issues[]`에 `model_source_ref_*` 진단을 남깁니다. 추천 품질 게이트는 복원된 최종 artifact를 기준으로 판단합니다.
```

- [x] **Step 2: Update architecture flow**

In `docs/ARCHITECTURE.md`, update the scheduled/manual AI Brief flow section around the source provider and model provider steps with this text:

```markdown
Source provider 단계는 ticker별 canonical source row를 만든 뒤 모델 요청 직전에 request-local source catalog를 구성합니다. Catalog는 각 후보의 source row에 `source_id`를 붙이고, OpenAI provider는 source 객체가 아니라 `source_refs[]`를 structured output으로 받습니다. Provider normalization은 refs를 catalog의 canonical source row로 복원하고, candidate-local source ref 오류는 `source_issues[]`로 격리한 뒤 최종 `recommendations[].sources[]`/`watch_candidates[].sources[]` artifact 형태를 유지합니다.
```

- [x] **Step 3: Update operations runbook**

In `docs/operations.md`, extend the `scheduled ai-brief quality gate failed` paragraph with this text:

```markdown
`model_source_ref_invalid`, `model_source_ref_missing`, `model_unbacked_recommendation_dropped`, `model_watch_source_ref_invalid`은 모델이 canonical source catalog의 ref를 제대로 선택하지 못했다는 뜻입니다. 이 진단이 `WARN`이고 최종 추천이 source-backed이면 scheduled run은 partial publish로 정상 업로드될 수 있습니다. 같은 진단 뒤 추천이 모두 제거되거나 source-backed ratio가 부족하면 기존처럼 quality `FAIL`로 처리됩니다.
```

- [x] **Step 4: Run docs grep check**

Run:

```bash
rg -n "source_refs|model_source_ref|model_watch_source_ref|source catalog" \
  docs/STRATEGY.md docs/ARCHITECTURE.md docs/operations.md
```

Expected: each of the three docs has at least one relevant match.

- [x] **Step 5: Run targeted tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py \
  tests/test_ai_brief.py::test_run_ai_brief_openai_provider_writes_structured_recommendation \
  tests/test_ai_brief.py::test_run_ai_brief_openai_invalid_watch_source_ref_uses_partial_publish_artifact \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_raises_when_ai_brief_quality_gate_fails \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_returns_result_when_ai_brief_quality_warns \
  -q
```

Expected: PASS.

- [x] **Step 6: Run Python quality gate**

Run:

```bash
just quality
```

Expected: PASS. If `just` fails because pinned tools are not on `PATH`, rerun:

```bash
mise exec -- just quality
```

Expected: PASS.

- [x] **Step 7: Commit Task 5**

```bash
git add docs/STRATEGY.md docs/ARCHITECTURE.md docs/operations.md
git commit -m "docs(ai-brief): source ref partial publish 운영 계약 기록" -m "AI Brief 모델 경계가 source_refs를 사용하고 후보 단위 source ref 오류는 partial publish 가능한 source issue로 격리된다는 전략, 구조, 운영 문서를 갱신합니다."
```

## Task 6: Final Review And Focused Diff Check

**Files:**
- Review: `sab/ai_brief_providers.py`
- Review: `tests/test_ai_brief_providers.py`
- Review: `tests/test_ai_brief.py`
- Review: `tests/test_scheduled_ai_brief_runner.py`
- Review: `docs/STRATEGY.md`
- Review: `docs/ARCHITECTURE.md`
- Review: `docs/operations.md`

- [x] **Step 1: Check final diff scope**

Run:

```bash
git status --short
git diff --stat HEAD~5..HEAD
```

Expected: only the files listed in this plan changed after the plan commit.

- [x] **Step 2: Search for stale returned source object schema in OpenAI outputs**

Run:

```bash
rg -n '"sources"\s*:' tests/test_ai_brief_providers.py tests/test_ai_brief.py sab/ai_brief_providers.py
```

Expected:

- Matches in final artifact assertions or model input candidate construction are allowed.
- No match should remain inside fake OpenAI response payloads that represent model output.
- `_openai_result_schema()` should expose `source_refs`, not output `sources`.

- [x] **Step 3: Search for new diagnostics**

Run:

```bash
rg -n "model_source_ref_invalid|model_source_ref_missing|model_unbacked_recommendation_dropped|model_watch_source_ref_invalid" sab tests docs
```

Expected: matches in provider implementation, provider/workflow tests, and docs.

- [x] **Step 4: Run final targeted verification**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest \
  tests/test_ai_brief_providers.py \
  tests/test_ai_brief.py::test_run_ai_brief_openai_invalid_watch_source_ref_uses_partial_publish_artifact \
  tests/test_scheduled_ai_brief_runner.py::test_default_pipeline_returns_result_when_ai_brief_quality_warns \
  -q
```

Expected: PASS.

- [x] **Step 5: Record final status**

Do not commit if any verification command fails. If all checks pass, report:

```text
Implemented source-ref OpenAI boundary, candidate-level source-ref isolation, partial publish regression coverage, and docs. just quality passed.
```
