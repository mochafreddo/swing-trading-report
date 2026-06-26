# AI Brief Korean Telegram Implementation Plan

**Status:** Completed on 2026-06-26.

> **Historical note:** This plan has been implemented on `feat/ai-brief-korean-telegram`. The checkbox steps below are retained as execution history, not active worker instructions.

**Goal:** Make new AI Brief Telegram messages Korean-first by guiding OpenAI display text to Korean and localizing the remaining Telegram diagnostic labels.

**Architecture:** Keep the current AI Brief artifact schema and Telegram delivery path. Add language instructions at the OpenAI provider boundary, translate only local fixed strings in provider/formatter code, and keep source titles and machine-readable identifiers unchanged.

**Tech Stack:** Python 3.14, pytest, `sab.ai_brief_providers`, `sab.report.notification_text`, Markdown docs.

---

## File Structure

- Modify `sab/ai_brief_providers.py`
  - Responsibility: AI Brief model provider request construction, fake provider fallback text, investment-readiness caveats, and provider fallback watch rows.
  - Boundary: Model/schema identifiers remain English and machine-readable; only user-facing explanation strings become Korean.
- Modify `tests/test_ai_brief_providers.py`
  - Responsibility: Provider prompt/request contract and fake-provider/local fixed display text coverage.
- Modify `sab/report/notification_text.py`
  - Responsibility: Telegram-only AI Brief notification formatting and HTML-safe diagnostics.
  - Boundary: No report schema changes and no machine translation of model/source free text.
- Modify `tests/test_notification_text.py`
  - Responsibility: Telegram diagnostic language, HTML escaping, and source-title preservation coverage.
- Modify `docs/api.md`
  - Responsibility: Public contract note for AI Brief notification language behavior.

## Task 1: Provider Korean Display Guidance

**Files:**
- Modify: `tests/test_ai_brief_providers.py`
- Modify: `sab/ai_brief_providers.py`

- [ ] **Step 1: Add failing provider-language tests**

In `tests/test_ai_brief_providers.py`, add this test near the existing OpenAI prompt/schema tests:

```python
def test_openai_prompt_requires_korean_display_fields() -> None:
    session = _CapturingSession(
        {
            "recommendations": [],
            "vetoed_candidates": [],
            "watch_candidates": [],
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
    request_input = request["input"]
    assert isinstance(request_input, list)
    system_message = request_input[0]
    assert isinstance(system_message, dict)
    system_content = str(system_message["content"])
    assert "Write user-facing display fields in Korean" in system_content
    assert "recommendations[].rationale" in system_content
    assert "recommendations[].checklist" in system_content
    assert "vetoed_candidates[].reason" in system_content
    assert "watch_candidates[].reason" in system_content
    assert "watch_candidates[].retrigger_conditions" in system_content
    assert "source_issues[].message" in system_content
    assert "Keep ticker symbols" in system_content
    assert "confidence/action enum values" in system_content
    assert "issue codes and severities" in system_content
    assert "source_refs" in system_content
    assert "article titles, URLs, and published dates unchanged" in system_content
```

Replace the assertion block in `test_fake_provider_rationale_uses_ai_role_reason_for_promoted_candidates` with:

```python
    rationale_items: list[str] = []
    for recommendation in result.recommendations:
        rationale = recommendation["rationale"]
        assert isinstance(rationale, list)
        rationale_items.extend(str(item) for item in rationale)
    rationale_text = "\n".join(rationale_items)
    assert "AI Brief 포함 사유: portfolio policy blocked automatic entry" in rationale_text
    assert "AI Brief 포함 사유: risk alignment requires manual review" in rationale_text
    assert "진입 갭 스냅샷: 1.00%" in rationale_text
    assert "수동 검토용 로컬 소스 맥락 있음" in rationale_text
    assert "AI brief inclusion" not in rationale_text
    assert "entry gap snapshot" not in rationale_text
    assert "local source context is available" not in rationale_text
    assert "entry report marked this candidate ENTER" not in rationale_text
```

Add a focused investment-readiness assertion inside `test_openai_normalized_output_preserves_candidate_investment_readiness` by replacing the two English caveat assertions with:

```python
    assert "투자 준비 상태에 추가 확인 필요: CONTEXT_REQUIRED" in rationale
    assert (
        "NAV/위험 예산, 청산 유동성, 포트폴리오 노출, 소스 맥락을 행동 전 확인"
        in checklist
    )
```

- [ ] **Step 2: Run provider tests and confirm failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_providers.py::test_openai_prompt_requires_korean_display_fields tests/test_ai_brief_providers.py::test_fake_provider_rationale_uses_ai_role_reason_for_promoted_candidates tests/test_ai_brief_providers.py::test_openai_normalized_output_preserves_candidate_investment_readiness
```

Expected: FAIL because the prompt and local fixed strings are still English.

- [ ] **Step 3: Add Korean provider guidance and local fixed text**

In `sab/ai_brief_providers.py`, replace `_INVESTMENT_READINESS_CHECKLIST_ITEM` with:

```python
_INVESTMENT_READINESS_CHECKLIST_ITEM = (
    "NAV/위험 예산, 청산 유동성, 포트폴리오 노출, 소스 맥락을 행동 전 확인"
)
```

In `FakeAiBriefProvider.build_recommendations`, replace the recommendation `checklist` list with:

```python
                "checklist": [
                    "진입 가격이 entry report 스냅샷과 크게 벌어지지 않았는지 확인",
                    "갭 가드, 포지션 크기, 현금 여력이 허용 범위인지 확인",
                    "차단 헤드라인이나 시장 전체 충격이 없는지 수동 확인",
                ],
```

In the same method, replace the fake watch row fallback fields with:

```python
                "reason": str(
                    candidate.get("ai_role_reason")
                    or "진입 트리거 재확인이 필요함"
                ),
                "retrigger_conditions": [
                    "가격이 원래 진입 트리거를 다시 충족해야 함",
                    "소스와 시장 맥락을 수동 확인해야 함",
                ],
```

In `_build_openai_request_payload`, append this sentence to the system message content after the existing source/title untrusted-data instructions and before the checklist sentence:

```python
                    "Write user-facing display fields in Korean: "
                    "recommendations[].rationale, recommendations[].checklist, "
                    "vetoed_candidates[].reason, watch_candidates[].reason, "
                    "watch_candidates[].retrigger_conditions, and "
                    "source_issues[].message. Keep ticker symbols, "
                    "confidence/action enum values, issue codes and severities, "
                    "source_refs, provider/source names, and article titles, URLs, "
                    "and published dates unchanged. "
```

In `_apply_investment_readiness_context`, replace the appended rationale text with:

```python
        f"투자 준비 상태에 추가 확인 필요: {status}",
```

In `_provider_fallback_watch_candidate`, replace the fallback reason and retrigger conditions with:

```python
    reason = str(
        candidate.get("ai_role_reason") or "진입 트리거 재확인이 필요함"
    ).strip()
    row: dict[str, object] = {
        "ticker": ticker,
        "action": "WATCH",
        "reason": reason,
        "retrigger_conditions": [
            "가격이 원래 진입 트리거를 다시 충족해야 함",
            "소스와 시장 맥락을 수동 확인해야 함",
        ],
        "sources": _candidate_sources(candidate),
    }
```

Replace `_build_fake_rationale` with:

```python
def _build_fake_rationale(candidate: Mapping[str, object]) -> list[str]:
    ai_role_reason = str(candidate.get("ai_role_reason") or "").strip()
    rationale = [
        f"AI Brief 포함 사유: {ai_role_reason}"
        if ai_role_reason
        else "AI Brief 수동 검토 대상 후보"
    ]
    entry_reasons = candidate.get("entry_reasons")
    if isinstance(entry_reasons, list) and entry_reasons:
        rationale.append(str(entry_reasons[0]))
    buy_reason_labels = candidate.get("buy_reason_labels")
    if isinstance(buy_reason_labels, list) and buy_reason_labels:
        rationale.append(f"매수 신호 맥락: {buy_reason_labels[0]}")
    gap_pct = candidate.get("gap_pct")
    if isinstance(gap_pct, int | float):
        rationale.append(f"진입 갭 스냅샷: {gap_pct * 100:.2f}%")
    if _candidate_sources(candidate):
        rationale.append("수동 검토용 로컬 소스 맥락 있음")
    return rationale
```

- [ ] **Step 4: Run provider tests and confirm pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_ai_brief_providers.py::test_openai_prompt_requires_korean_display_fields tests/test_ai_brief_providers.py::test_fake_provider_rationale_uses_ai_role_reason_for_promoted_candidates tests/test_ai_brief_providers.py::test_openai_normalized_output_preserves_candidate_investment_readiness
```

Expected: PASS.

- [ ] **Step 5: Commit provider changes**

Run:

```bash
git add sab/ai_brief_providers.py tests/test_ai_brief_providers.py
git commit -m "feat(ai-brief): 모델 표시 문구를 한국어로 유도"
```

## Task 2: Telegram Diagnostic Localization

**Files:**
- Modify: `tests/test_notification_text.py`
- Modify: `sab/report/notification_text.py`

- [ ] **Step 1: Update failing Telegram diagnostic tests**

In `tests/test_notification_text.py`, update the assertion in `test_build_ai_brief_telegram_report_text_explains_weak_news_coverage` from:

```python
    assert (
        "source issue: MSFT.NAS openai_no_external_sources - "
        "No supplied source context."
    ) in text
```

to:

```python
    assert (
        "소스 이슈: MSFT.NAS openai_no_external_sources - "
        "No supplied source context."
    ) in text
```

In `test_build_ai_brief_telegram_report_text_handles_zero_recommendations`, update the system issue assertion from:

```python
    assert "system issue: model_provider_timeout - OpenAI request timed out." in text
```

to:

```python
    assert "시스템 이슈: model_provider_timeout - OpenAI request timed out." in text
```

In `test_build_ai_brief_telegram_report_text_explains_model_failure_with_candidates`, update the system issue assertion from:

```python
    assert (
        "system issue: model_provider_failed - OpenAI request failed with HTTP 429: "
        "quota exceeded"
    ) in text
```

to:

```python
    assert (
        "시스템 이슈: model_provider_failed - OpenAI request failed with HTTP 429: "
        "quota exceeded"
    ) in text
```

In `test_build_ai_brief_telegram_report_text_includes_watch_and_source_chain`, replace the source-chain/provider assertions with:

```python
    assert (
        "소스 체인 finnhub, benzinga-news · 추천 커버리지 3/7 · "
        "watch 커버리지 1/2"
    ) in text
    assert (
        "소스 제공자: finnhub 성공 3/7; benzinga-news 성공 0/4"
    ) in text
    assert "source_chain=" not in text
    assert "source_providers=" not in text
```

Add this focused source-title preservation test near the AI Brief Telegram tests:

```python
def test_build_ai_brief_telegram_report_text_preserves_source_title_language() -> None:
    report = _minimal_ai_brief_report(
        summary={"preselected_count": 1, "recommendation_count": 1},
        recommendations=[
            {
                "ticker": "AAPL.NAS",
                "confidence": "HIGH",
                "rationale": ["한국어 추천 사유"],
                "sources": [
                    {
                        "title": "Apple supply chain update",
                        "url": "https://example.test/aapl",
                        "published_at": "2026-05-05T07:00:00+09:00",
                    }
                ],
            }
        ],
    )

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
    )

    assert "한국어 추천 사유" in text
    assert "근거 <code>1</code>개 · Apple supply chain update" in text
    assert "애플 공급망 업데이트" not in text
```

- [ ] **Step 2: Run Telegram tests and confirm failure**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_explains_weak_news_coverage tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_handles_zero_recommendations tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_explains_model_failure_with_candidates tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_includes_watch_and_source_chain tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_preserves_source_title_language
```

Expected: FAIL because diagnostics still use English labels and raw source summary names.

- [ ] **Step 3: Localize formatter helpers and AI Brief diagnostics**

In `sab/report/notification_text.py`, add this helper after `_format_coverage`:

```python
def _format_provider_status_label(status: Any) -> str:
    normalized = _safe_str(status).lower()
    labels = {
        "success": "성공",
        "partial": "부분",
        "failed": "실패",
        "error": "오류",
        "skipped": "건너뜀",
    }
    return labels.get(normalized, _safe_str(status, default="-"))
```

Replace `_format_source_chain_summary` with:

```python
def _format_source_chain_summary(report: dict[str, Any]) -> str:
    source_provider_summary = _as_dict(report.get("source_provider_summary"))
    chain = [_safe_str(item) for item in _as_list(source_provider_summary.get("chain"))]
    chain = [provider for provider in chain if provider]
    if not chain:
        return ""

    chain_text = ", ".join(chain)
    final = _as_dict(source_provider_summary.get("final"))
    if not final:
        return f"소스 체인 {chain_text}"
    recommendable = _format_coverage(
        final.get("recommendable_covered"),
        final.get("recommendable_total"),
    )
    watch = _format_coverage(final.get("watch_covered"), final.get("watch_total"))
    return (
        f"소스 체인 {chain_text} · 추천 커버리지 {recommendable} · "
        f"watch 커버리지 {watch}"
    )
```

Replace `_format_source_provider_statuses` with:

```python
def _format_source_provider_statuses(report: dict[str, Any]) -> str:
    source_provider_summary = _as_dict(report.get("source_provider_summary"))
    parts: list[str] = []
    for raw_provider in _as_list(source_provider_summary.get("providers")):
        provider = _as_dict(raw_provider)
        name = _safe_str(provider.get("provider"))
        if not name:
            continue
        status = _format_provider_status_label(provider.get("status"))
        coverage = _format_coverage(provider.get("covered"), provider.get("total"))
        parts.append(f"{name} {status} {coverage}")
    if not parts:
        return ""
    return f"소스 제공자: {'; '.join(parts)}"
```

In `build_ai_brief_telegram_report_text`, replace the diagnostic count block:

```python
            (
                f"source {_html_code(counts.source_issue_count)} · "
                f"system {_html_code(counts.system_issue_count)}"
            ),
```

with:

```python
            (
                f"소스 이슈 {_html_code(counts.source_issue_count)} · "
                f"시스템 이슈 {_html_code(counts.system_issue_count)}"
            ),
```

In the same function, replace the source summary rendering:

```python
    if source_chain_summary:
        lines.append(_html_code_single_line(source_chain_summary, max_chars=360))
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(_html_code_single_line(source_provider_statuses, max_chars=360))
```

with:

```python
    if source_chain_summary:
        lines.append(_html_single_line(source_chain_summary, max_chars=360))
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(_html_single_line(source_provider_statuses, max_chars=360))
```

Replace the issue loop prefixes:

```python
            _html_single_line(_format_issue("source issue", issue), max_chars=360)
```

with:

```python
            _html_single_line(_format_issue("소스 이슈", issue), max_chars=360)
```

and:

```python
            _html_single_line(_format_issue("system issue", issue), max_chars=360)
```

with:

```python
            _html_single_line(_format_issue("시스템 이슈", issue), max_chars=360)
```

- [ ] **Step 4: Run Telegram tests and confirm pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_explains_weak_news_coverage tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_handles_zero_recommendations tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_explains_model_failure_with_candidates tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_includes_watch_and_source_chain tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_preserves_source_title_language
```

Expected: PASS.

- [ ] **Step 5: Run full notification text tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_notification_text.py
```

Expected: PASS.

- [ ] **Step 6: Commit Telegram formatter changes**

Run:

```bash
git add sab/report/notification_text.py tests/test_notification_text.py
git commit -m "feat(ai-brief): 텔레그램 진단 문구를 한국어화"
```

## Task 3: Documentation And Final Verification

**Files:**
- Modify: `docs/api.md`

- [ ] **Step 1: Update notification contract docs**

In `docs/api.md`, under `### Notification Text Contracts`, replace this bullet:

```markdown
- AI Brief Telegram report notifications use Telegram HTML rich text. The body is decision-first and uses only `<b>`, `<code>`, and `<a>` tags.
```

with:

```markdown
- AI Brief Telegram report notifications use Telegram HTML rich text. The body is decision-first, Korean-first for operator-facing explanation text, and uses only `<b>`, `<code>`, and `<a>` tags. Source article titles, tickers, enum values, issue codes, URLs, and storage keys remain original/untranslated.
```

- [ ] **Step 2: Run targeted provider and notification suites**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_notification_text.py tests/test_ai_brief_providers.py
```

Expected: PASS.

- [ ] **Step 3: Run repository quality gate**

Run:

```bash
just quality
```

Expected: PASS. If this fails because `pnpm` is unavailable, rerun:

```bash
mise exec -- just quality
```

Expected: PASS.

- [ ] **Step 4: Review final diff for scope**

Run:

```bash
git diff --stat
git diff -- sab/ai_brief_providers.py sab/report/notification_text.py tests/test_ai_brief_providers.py tests/test_notification_text.py docs/api.md
```

Expected:

- Provider prompt and local fixed strings are Korean-first.
- Telegram diagnostics use Korean labels.
- Source article titles remain unmodified.
- No scan/sell Telegram, Slack, schema, ranking, source collection, or quality-gate behavior changed.

- [ ] **Step 5: Commit docs and any final test-only adjustments**

Run:

```bash
git add docs/api.md
git commit -m "docs(ai-brief): 한국어 알림 계약 문서화"
```

If Step 2 or Step 3 required small test-only expectation fixes in files already changed by Tasks 1 or 2, include only those files in this final commit:

```bash
git add docs/api.md tests/test_ai_brief_providers.py tests/test_notification_text.py
git commit -m "docs(ai-brief): 한국어 알림 계약 문서화"
```

## Plan Self-Review

- Spec coverage: The plan covers OpenAI Korean display guidance, fake-provider/local fixed Korean text, Telegram Korean diagnostic labels, source/provider summary localization, source-title preservation, unchanged report contracts, unchanged scan/sell/Slack/skipped paths, and targeted verification.
- Scope check: The plan is one cohesive subsystem, AI Brief operator-facing notification language. It does not introduce machine translation, locale settings, transport changes, ranking changes, source changes, or strategy changes.
- Type consistency: New helper names are `_format_provider_status_label`, `_format_source_chain_summary`, and `_format_source_provider_statuses`; tests assert rendered strings rather than changing public APIs.
