# AI Brief Telegram Rich Text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Execution status:** This file is preserved as the implementation recipe for this branch. After execution, the checklist below is not maintained as live task status; use the branch commits and verification output as the completion record.

**Goal:** Render AI Brief Telegram report notifications as decision-first Telegram HTML while preserving existing scan/sell, Slack, skipped, and failure alert behavior.

**Architecture:** Keep the existing `sab.report.notification_text` builder boundary and `sendMessage` transport. Add small HTML formatting helpers inside `notification_text.py`, convert only `build_ai_brief_telegram_report_text(...)` to Telegram HTML, and pass `parse_mode=HTML` only from AI Brief report delivery paths.

**Tech Stack:** Python 3.14, pytest, GitHub Actions YAML, Telegram Bot API `sendMessage` with `parse_mode=HTML`.

---

## Problem Brief

**Context:** AI Brief Telegram text is built in `sab/report/notification_text.py`. GitHub workflow delivery happens in `.github/workflows/ai-brief.yml`, and local scheduled delivery happens through `DefaultScheduledNotifier` in `sab/scheduler/runner.py`.

**Problem:** The current AI Brief Telegram body is plain key-value text, so the main decision signal is mixed with diagnostics and harder to scan on mobile.

**Goal:** Improve only the AI Brief Telegram report body with Telegram HTML rich text, decision-first ordering, and safe escaping.

**Non-Goals:** Do not modify scan/sell Telegram, Slack summaries, skipped notifications, host-failure alerts, report JSON schema, recommendation logic, or quality-gate behavior.

**Constraints:** Keep `sendMessage`, keep previews disabled, keep current message splitting behavior, escape all report-derived text, and avoid emoji.

## Impact Note

This changes AI Brief Telegram rendering and the AI Brief report send payload. The main break risk is malformed Telegram HTML, so the implementation must add escaping tests and parse-mode delivery tests. Strategy documentation does not change because trading logic does not change.

## File Structure

- Modify `sab/report/notification_text.py`
  - Add HTML escape/tag/link helpers.
  - Convert `build_ai_brief_telegram_report_text(...)` from plain text to Telegram HTML.
  - Leave scan/sell Telegram and Slack builders unchanged.
- Modify `sab/scheduler/runner.py`
  - Let `DefaultScheduledNotifier._post_telegram_message(...)` accept an optional `parse_mode`.
  - Pass `parse_mode="HTML"` from `send_schedule(...)`.
  - Leave `send_late_alert(...)` plain text.
- Modify `.github/workflows/ai-brief.yml`
  - Send each split `ai-brief.telegram.txt` part with `parse_mode=HTML` only from the `Send Telegram notification` step.
  - Leave `Send skipped Telegram notification` unchanged.
- Modify `tests/test_notification_text.py`
  - Update AI Brief Telegram expectations for HTML.
  - Add escaping and unsafe-link coverage.
  - Keep scan/sell tests plain text.
- Modify `tests/test_ai_brief_workflow.py`
  - Assert AI Brief report send step includes `parse_mode=HTML`.
  - Assert skipped send step does not include `parse_mode=HTML`.
- Modify `tests/test_scheduled_ai_brief_runner.py`
  - Assert AI Brief scheduled Telegram POST includes `parse_mode=HTML`.
  - Assert late alert POST does not include `parse_mode`.
- Modify `docs/ARCHITECTURE.md`
  - Clarify AI Brief Telegram is HTML rich text, while Slack and scan/sell remain unchanged.

## Task 1: AI Brief Telegram HTML Builder

**Files:**
- Modify: `tests/test_notification_text.py`
- Modify: `sab/report/notification_text.py`

- [ ] **Step 1: Add failing tests for AI Brief Telegram HTML formatting and escaping**

Append these tests near the existing AI Brief Telegram tests in `tests/test_notification_text.py`:

```python
def test_build_ai_brief_telegram_report_text_uses_html_rich_text() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "summary": {
            "preselected_count": 2,
            "recommendation_count": 1,
            "source_issue_count": 0,
            "system_issue_count": 0,
        },
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "name": "Apple",
                "confidence": "HIGH",
                "rationale": ["source-backed context supports manual review"],
                "sources": [{"title": "Apple supply chain update"}],
            }
        ],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789",
        storage_key="2026/05/2026-05-05.ai-brief.json",
    )

    assert text.startswith("<b>SAB AI Brief</b>")
    assert "시장 <code>US</code>" in text
    assert "모델 <code>openai/gpt-test</code>" in text
    assert "<b>판단</b>" in text
    assert "상태 <code>FINAL_JUDGMENT</code>" in text
    assert "사유 <code>source_backed_final</code>" in text
    assert "뉴스 근거 확인된 추천 후보 1건" in text
    assert "<b>추천 후보 1건</b> (표시 <code>1</code>건)" in text
    assert "1. <b>AAPL.NAS Apple</b> · <code>HIGH</code>" in text
    assert "근거 <code>1</code>개 · Apple supply chain update" in text
    assert "<b>진단</b>" in text
    assert "source <code>0</code> · system <code>0</code>" in text
    assert "보관 <code>2026/05/2026-05-05.ai-brief.json</code>" in text
    assert (
        '<a href="https://github.com/example/repo/actions/runs/789">실행 보기</a>'
        in text
    )


def test_build_ai_brief_telegram_report_text_escapes_html_values() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "openai",
        "model_name": "gpt<&test>",
        "summary": {
            "preselected_count": 1,
            "recommendation_count": 1,
            "source_issue_count": 1,
            "system_issue_count": 0,
        },
        "recommendations": [
            {
                "ticker": "AAPL.NAS",
                "name": 'AT&T <Alpha "A">',
                "confidence": "HIGH",
                "rationale": ['2 < 3 & "quoted"'],
                "sources": [{"title": "News <b>bold</b> & supply"}],
            }
        ],
        "source_issues": [
            {
                "ticker": "AAPL.NAS",
                "code": "source_coverage_below_threshold",
                "message": 'bad <tag> & "quoted"',
            }
        ],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="https://github.com/example/repo/actions/runs/789?x=1&y=2",
    )

    assert "모델 <code>openai/gpt&lt;&amp;test&gt;</code>" in text
    assert "<b>AAPL.NAS AT&amp;T &lt;Alpha &quot;A&quot;&gt;</b>" in text
    assert "2 &lt; 3 &amp; &quot;quoted&quot;" in text
    assert "News &lt;b&gt;bold&lt;/b&gt; &amp; supply" in text
    assert "bad &lt;tag&gt; &amp; &quot;quoted&quot;" in text
    assert (
        '<a href="https://github.com/example/repo/actions/runs/789?x=1&amp;y=2">'
        "실행 보기</a>"
    ) in text


def test_build_ai_brief_telegram_report_text_keeps_unsafe_run_url_plain() -> None:
    report = {
        "generated_at": "2026-05-05T08:40:00+09:00",
        "market": "US",
        "model_provider": "fake",
        "model_name": "fake-ai-brief-v1",
        "summary": {"recommendation_count": 0},
        "recommendations": [],
        "source_issues": [],
        "system_issues": [],
    }

    text = build_ai_brief_telegram_report_text(
        report=report,
        run_url="javascript:alert(1)",
    )

    assert '<a href="javascript:alert(1)">' not in text
    assert "실행 javascript:alert(1)" in text
```

- [ ] **Step 2: Run the new formatting tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_uses_html_rich_text \
  tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_escapes_html_values \
  tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_keeps_unsafe_run_url_plain
```

Expected: FAIL because the current builder starts with `[SAB][ai-brief][schedule]`, does not emit HTML tags, and does not render a labeled link.

- [ ] **Step 3: Add HTML helper imports and functions**

In `sab/report/notification_text.py`, add these imports near the top:

```python
import html
from urllib.parse import urlparse
```

Add these helpers after `_safe_single_line(...)`:

```python
def _html_escape(value: Any, *, default: str = "") -> str:
    return html.escape(_safe_str(value, default=default), quote=True)


def _html_bold(value: Any, *, default: str = "") -> str:
    return f"<b>{_html_escape(value, default=default)}</b>"


def _html_code(value: Any, *, default: str = "") -> str:
    return f"<code>{_html_escape(value, default=default)}</code>"


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _html_link(url: Any, label: str) -> str:
    text = _safe_str(url)
    if not text:
        return ""
    if not _is_http_url(text):
        return _html_escape(text)
    return f'<a href="{_html_escape(text)}">{_html_escape(label)}</a>'
```

Add this decision helper near `_format_source_provider_statuses(...)`:

```python
def _ai_brief_decision_text(
    *,
    state: str,
    reason: str,
    recommendation_count: int,
) -> str:
    if state == BRIEF_STATE_NO_SIGNAL:
        return "오늘은 볼 종목 없음. 쉬어도 됨"
    if state == BRIEF_STATE_NEEDS_REVIEW_WATCH_ONLY:
        return "watch 후보만 있음. 재트리거 조건 확인 필요"
    if state == BRIEF_STATE_FINAL_JUDGMENT:
        return f"뉴스 근거 확인된 추천 후보 {recommendation_count}건"
    if reason == BRIEF_REASON_MODEL_OR_SYSTEM_ISSUE:
        return "AI 판단 보류: 모델/시스템 이슈 확인 필요"
    if reason == BRIEF_REASON_WEAK_NEWS_COVERAGE:
        return "뉴스 근거 약함, 기술 신호만 있음"
    return "AI 판단 보류: 추천을 확정하지 않음"
```

- [ ] **Step 4: Convert `build_ai_brief_telegram_report_text(...)` to HTML**

Replace the body of `build_ai_brief_telegram_report_text(...)` in `sab/report/notification_text.py` with this implementation:

```python
def build_ai_brief_telegram_report_text(
    *,
    report: dict[str, Any],
    run_url: str,
    storage_key: str | None = None,
    max_items: int = 5,
) -> str:
    counts = _ai_brief_counts(report)
    total = len(counts.recommendations)
    shown = min(total, max(max_items, 0), 3)
    model_provider = _safe_str(report.get("model_provider"), default="fake")
    model_name = _safe_str(report.get("model_name"), default="-")
    brief_state = read_ai_brief_state(report)
    decision = _ai_brief_decision_text(
        state=brief_state.state,
        reason=brief_state.reason,
        recommendation_count=total,
    )

    lines = [
        _html_bold("SAB AI Brief"),
        (
            f"시장 {_html_code(report.get('market'), default='-')} · "
            f"모델 {_html_code(f'{model_provider}/{model_name}')}"
        ),
        f"생성 {_html_code(_generated_at(report))}",
        "",
        _html_bold("판단"),
        f"상태 {_html_code(brief_state.state)} · 사유 {_html_code(brief_state.reason)}",
        _html_escape(decision),
        (
            f"추천 {_html_code(total)}건 · 표시 {_html_code(shown)}건 · "
            f"source {_html_code(counts.source_issue_count)} · "
            f"system {_html_code(counts.system_issue_count)}"
        ),
    ]

    if counts.watch_present:
        ticker_preview, extra = _ticker_preview(counts.watch_tickers)
        suffix = f", 외 {extra}건" if extra > 0 else ""
        detail = (
            f": {_html_escape(ticker_preview)}{_html_escape(suffix)}"
            if ticker_preview
            else ""
        )
        lines.append(f"watch 후보 {_html_code(counts.watch_count)}건{detail}")

    if (
        brief_state.state == BRIEF_STATE_NEEDS_REVIEW_WEAK_NEWS
        and counts.preselected_count > 0
        and total > 0
    ):
        ticker_preview, extra = _ticker_preview(report.get("eligible_tickers"))
        if ticker_preview:
            suffix = f", 외 {extra}건" if extra > 0 else ""
            lines.append(
                f"대상: {_html_escape(ticker_preview)}{_html_escape(suffix)}"
            )

    lines.append("")
    if total == 0:
        lines.extend([_html_bold("추천 후보"), "추천 후보 없음"])
        if counts.recommendable_count > 0:
            candidate_count_text = f"{counts.recommendable_count}건"
            if counts.preselected_count != counts.recommendable_count:
                candidate_count_text = (
                    f"{candidate_count_text}(모델 입력 {counts.preselected_count}건)"
                )
            lines.append(
                "추천 생성 실패/보류: recommendable 후보 "
                f"{_html_escape(candidate_count_text)}이 있었지만 추천 결과가 비었습니다."
            )
            ticker_preview, extra = _ticker_preview(report.get("eligible_tickers"))
            if ticker_preview:
                suffix = f", 외 {extra}건" if extra > 0 else ""
                lines.append(
                    f"대상: {_html_escape(ticker_preview)}{_html_escape(suffix)}"
                )
    else:
        lines.append(
            f"{_html_bold(f'추천 후보 {total}건')} (표시 {_html_code(shown)}건)"
        )
        for idx, row in enumerate(counts.recommendations[:shown], start=1):
            ticker = _safe_str(row.get("ticker"), default="-")
            name = _safe_str(row.get("name"))
            ticker_name = f"{ticker} {name}".strip()
            confidence = _safe_str(row.get("confidence"), default="-").upper()
            rationale = _first_list_text(row.get("rationale"))
            source_count = len(_recommendation_sources(row))
            lines.append(f"{idx}. {_html_bold(ticker_name)} · {_html_code(confidence)}")
            lines.append(f"   {_html_escape(rationale)}")
            source_title = _first_source_title(row)
            if source_title:
                lines.append(
                    f"   근거 {_html_code(source_count)}개 · {_html_escape(source_title)}"
                )
            else:
                lines.append(f"   근거 {_html_code(source_count)}개")
        extra = total - shown
        if extra > 0:
            lines.append(f"외 {_html_code(extra)}건")

    vetoed_total = len(counts.vetoed_candidates)
    vetoed_shown = min(vetoed_total, max(max_items, 0), 3)
    if vetoed_total > 0:
        lines.extend(["", _html_bold(f"AI 판단 제외 {vetoed_total}건")])
        for row in counts.vetoed_candidates[:vetoed_shown]:
            ticker = _safe_str(row.get("ticker"), default="-")
            action = _safe_str(row.get("action"), default="-").upper()
            reason = _safe_single_line(row.get("reason"), default="-")
            lines.append(
                f"- {_html_code(ticker)} · {_html_code(action)} · {_html_escape(reason)}"
            )
        extra = vetoed_total - vetoed_shown
        if extra > 0:
            lines.append(f"제외 외 {_html_code(extra)}건")

    lines.extend(
        [
            "",
            _html_bold("진단"),
            (
                f"source {_html_code(counts.source_issue_count)} · "
                f"system {_html_code(counts.system_issue_count)}"
            ),
        ]
    )
    source_chain_summary = _format_source_chain_summary(report)
    if source_chain_summary:
        lines.append(_html_code(source_chain_summary))
    source_provider_statuses = _format_source_provider_statuses(report)
    if source_provider_statuses:
        lines.append(_html_code(source_provider_statuses))

    for issue in counts.source_issues[:3]:
        lines.append(_html_escape(_format_issue("source issue", issue)))
    for issue in counts.system_issues[:3]:
        lines.append(_html_escape(_format_issue("system issue", issue)))

    key = _safe_str(storage_key)
    if key:
        lines.append(f"보관 {_html_code(key)}")
    run_link = _html_link(run_url, "실행 보기")
    if run_link:
        if _is_http_url(_safe_str(run_url)):
            lines.append(run_link)
        else:
            lines.append(f"실행 {run_link}")
    return "\n".join(lines)
```

- [ ] **Step 5: Run the targeted AI Brief Telegram tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_uses_html_rich_text \
  tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_escapes_html_values \
  tests/test_notification_text.py::test_build_ai_brief_telegram_report_text_keeps_unsafe_run_url_plain
```

Expected: PASS.

- [ ] **Step 6: Update existing AI Brief Telegram assertions for the new HTML shape**

In `tests/test_notification_text.py`, update only AI Brief Telegram assertions that expect old plain key-value fragments. Keep the semantic checks but assert the rich text shape. Use these replacements as the target style:

```python
assert "<b>SAB AI Brief</b>" in text
assert "시장 <code>US</code>" in text
assert "모델 <code>openai/gpt-test</code>" in text
assert "상태 <code>FINAL_JUDGMENT</code>" in text
assert "사유 <code>source_backed_final</code>" in text
assert "뉴스 근거 확인된 추천 후보 2건" in text
assert "<b>추천 후보 2건</b> (표시 <code>2</code>건)" in text
assert "source <code>0</code> · system <code>0</code>" in text
assert "1. <b>AAPL.NAS Apple</b> · <code>HIGH</code>" in text
assert "근거 <code>1</code>개 · Apple supply chain update" in text
```

For count and extra assertions, use these rich-text equivalents:

```python
assert "watch 후보 <code>2</code>건: AAPL.NAS, MSFT.NAS" in text
assert "<code>source_chain=finnhub,benzinga-news final recommendable=3/7 watch=1/2</code>" in text
assert "<code>source_providers=finnhub success 3/7; benzinga-news success 0/4</code>" in text
assert "외 <code>4</code>건" in text
assert "보관 <code>2026/05/2026-05-05.ai-brief.json</code>" in text
```

- [ ] **Step 7: Run all notification text tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_notification_text.py
```

Expected: PASS. Scan and sell Telegram tests should still pass with plain text expectations.

- [ ] **Step 8: Commit the builder change**

Run:

```bash
git add sab/report/notification_text.py tests/test_notification_text.py
git commit -m "feat(ai-brief): 텔레그램 리치 텍스트 본문 렌더링" -m "AI Brief 텔레그램 리포트 본문을 decision-first HTML 형식으로 렌더링하고 리포트 값 escape 회귀 테스트를 추가한다."
```

Expected: commit succeeds.

## Task 2: GitHub Workflow Parse Mode

**Files:**
- Modify: `.github/workflows/ai-brief.yml`
- Modify: `tests/test_ai_brief_workflow.py`

- [ ] **Step 1: Add failing workflow assertions**

In `tests/test_ai_brief_workflow.py`, update `test_ai_brief_workflow_uploads_artifacts_and_delivery_is_opt_in()` by adding these lines after the existing Telegram env assertions:

```python
    telegram_script = str(telegram_step.get("run") or "")
    skipped_telegram_step = _find_step_by_name(
        steps,
        "Send skipped Telegram notification",
    )
    skipped_telegram_script = str(skipped_telegram_step.get("run") or "")

    assert "split_telegram_message_text" in telegram_script
    assert 'Path("ai-brief.telegram.txt").read_text' in telegram_script
    assert '"parse_mode": "HTML"' in telegram_script
    assert "for message_text in split_telegram_message_text(" in telegram_script
    assert '"text": message_text' in telegram_script
    assert "text@ai-brief.telegram.txt" not in telegram_script
    assert "parse_mode" not in skipped_telegram_script
    assert "text@ai-brief.skipped.telegram.txt" in skipped_telegram_script
```

- [ ] **Step 2: Run the workflow test and verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_ai_brief_workflow.py::test_ai_brief_workflow_uploads_artifacts_and_delivery_is_opt_in
```

Expected: FAIL because the AI Brief Telegram send step does not yet split long
rich-text messages and send each part with `parse_mode=HTML`.

- [ ] **Step 3: Add HTML chunked delivery to AI Brief report delivery**

In `.github/workflows/ai-brief.yml`, update only the `Send Telegram notification`
step that sends `ai-brief.telegram.txt`:

```yaml
          python - <<'PY'
          import os
          import urllib.parse
          import urllib.request
          from pathlib import Path

          from sab.report.notification_text import split_telegram_message_text

          bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
          chat_id = os.environ["TELEGRAM_CHAT_ID"]
          url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
          telegram_text = Path("ai-brief.telegram.txt").read_text(encoding="utf-8")

          for message_text in split_telegram_message_text(telegram_text):
              payload = urllib.parse.urlencode(
                  {
                      "chat_id": chat_id,
                      "text": message_text,
                      "parse_mode": "HTML",
                      "disable_web_page_preview": "true",
                  }
              ).encode("utf-8")
              req = urllib.request.Request(url, data=payload, method="POST")
              with urllib.request.urlopen(req, timeout=10) as resp:
                  if resp.status >= 300:
                      raise RuntimeError(f"Telegram returned HTTP {resp.status}")
          PY
```

Do not modify the earlier `Send skipped Telegram notification` curl command.

- [ ] **Step 4: Run the workflow test**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_ai_brief_workflow.py::test_ai_brief_workflow_uploads_artifacts_and_delivery_is_opt_in
```

Expected: PASS.

- [ ] **Step 5: Commit the workflow change**

Run:

```bash
git add .github/workflows/ai-brief.yml tests/test_ai_brief_workflow.py
git commit -m "fix(ai-brief): 텔레그램 HTML 장문 전송 보강" -m "AI Brief 리포트 텔레그램 전송에 HTML parse mode와 메시지 분할 전송을 적용하고 skipped 알림은 plain text로 유지한다."
```

Expected: commit succeeds.

## Task 3: Scheduled Notifier Parse Mode

**Files:**
- Modify: `sab/scheduler/runner.py`
- Modify: `tests/test_scheduled_ai_brief_runner.py`

- [ ] **Step 1: Add failing scheduled notifier payload assertions**

Replace `test_default_notifier_treats_slack_failure_as_best_effort` in `tests/test_scheduled_ai_brief_runner.py` with this version:

```python
def test_default_notifier_treats_slack_failure_as_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Response:
        status_code = 200

    def fake_post(url: str, **kwargs: object) -> _Response:
        calls.append((url, kwargs))
        if "hooks.slack.com" in url:
            raise RuntimeError("slack down")
        return _Response()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/test")
    monkeypatch.setattr("sab.scheduler.runner.requests.post", fake_post)

    DefaultScheduledNotifier().send_schedule(
        report=_FakeStorage().payload,
        storage_key="2026/05/2026-05-28.ai-brief.json",
    )

    telegram_call = next(
        (kwargs for url, kwargs in calls if "api.telegram.org" in url),
        None,
    )
    assert telegram_call is not None
    telegram_data = telegram_call.get("data")
    assert isinstance(telegram_data, dict)
    assert telegram_data["parse_mode"] == "HTML"
    assert telegram_data["disable_web_page_preview"] == "true"
    assert any("hooks.slack.com" in url for url, _kwargs in calls)
```

Add this new test below it:

```python
def test_default_scheduled_notifier_late_alert_stays_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Response:
        status_code = 200

    def fake_post(url: str, **kwargs: object) -> _Response:
        calls.append((url, kwargs))
        return _Response()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr("sab.scheduler.runner.requests.post", fake_post)

    DefaultScheduledNotifier().send_late_alert(
        reason="docker_failed",
        context={"detail": "plain <text> & safe"},
    )

    telegram_call = next(
        (kwargs for url, kwargs in calls if "api.telegram.org" in url),
        None,
    )
    assert telegram_call is not None
    telegram_data = telegram_call.get("data")
    assert isinstance(telegram_data, dict)
    assert "parse_mode" not in telegram_data
    assert "plain <text> & safe" in str(telegram_data["text"])
```

- [ ] **Step 2: Run the scheduled notifier tests and verify they fail**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_scheduled_ai_brief_runner.py::test_default_notifier_treats_slack_failure_as_best_effort \
  tests/test_scheduled_ai_brief_runner.py::test_default_scheduled_notifier_late_alert_stays_plain_text
```

Expected: FAIL because scheduled AI Brief Telegram data does not yet include `parse_mode`.

- [ ] **Step 3: Add optional parse mode to `DefaultScheduledNotifier`**

In `sab/scheduler/runner.py`, change `_post_telegram_message` to accept an optional parse mode:

```python
    def _post_telegram_message(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        bot_token = str(os.environ["TELEGRAM_BOT_TOKEN"])
        chat_id = str(os.environ["TELEGRAM_CHAT_ID"])
        data = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data=data,
            timeout=10,
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Telegram send failed: HTTP {response.status_code}")
```

In `send_schedule(...)`, change the chunk send loop to:

```python
        for part in split_telegram_message_text(text):
            self._post_telegram_message(part, parse_mode="HTML")
```

Do not change `send_late_alert(...)`; it should continue calling:

```python
        self._post_telegram_message(text)
```

- [ ] **Step 4: Run the scheduled notifier tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_scheduled_ai_brief_runner.py::test_default_notifier_treats_slack_failure_as_best_effort \
  tests/test_scheduled_ai_brief_runner.py::test_default_scheduled_notifier_late_alert_stays_plain_text
```

Expected: PASS.

- [ ] **Step 5: Commit the scheduled notifier change**

Run:

```bash
git add sab/scheduler/runner.py tests/test_scheduled_ai_brief_runner.py
git commit -m "fix(scheduler): AI Brief 텔레그램 HTML 전송 설정" -m "스케줄 AI Brief 알림에는 parse_mode=HTML을 전달하고 late alert 알림은 기존 plain text 전송으로 유지한다."
```

Expected: commit succeeds.

## Task 4: Architecture Documentation And Final Verification

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Update notification architecture documentation**

In `docs/ARCHITECTURE.md`, replace the paragraph bullet that starts with
`` `notification_text`는 생성된 artifact를 Telegram 본문/Slack key-value 요약 텍스트로 렌더링할 수 있습니다.`` with this text:

```markdown
9. `notification_text`는 생성된 artifact를 Telegram 본문/Slack key-value 요약 텍스트로 렌더링할 수 있습니다. AI Brief Telegram 리포트 본문은 Telegram HTML rich text(`parse_mode=HTML`)로 decision-first 형식을 사용하며, `NO_SIGNAL`이면 휴식 문구, `NEEDS_REVIEW_WATCH_ONLY`이면 watch-only 재트리거 확인 문구, `FINAL_JUDGMENT`이면 source-backed 후보, `NEEDS_REVIEW_WEAK_NEWS`이면 downgraded copy와 issue 요약을 보여줍니다. `watch_candidates[]`, `source_provider_summary`, `vetoed_candidates[]`가 있으면 추천과 별도로 표시합니다. Slack 요약은 watch/source chain/veto count를 key-value로 포함하고, scan/sell Telegram 메시지는 기존 plain text 형식을 유지합니다.
```

- [ ] **Step 2: Run focused verification**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q \
  tests/test_notification_text.py \
  tests/test_ai_brief_workflow.py::test_ai_brief_workflow_uploads_artifacts_and_delivery_is_opt_in \
  tests/test_scheduled_ai_brief_runner.py::test_default_notifier_treats_slack_failure_as_best_effort \
  tests/test_scheduled_ai_brief_runner.py::test_default_scheduled_notifier_late_alert_stays_plain_text
```

Expected: PASS.

- [ ] **Step 3: Run lint/type checks for touched Python files**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check sab/report/notification_text.py sab/scheduler/runner.py tests/test_notification_text.py tests/test_ai_brief_workflow.py tests/test_scheduled_ai_brief_runner.py
```

Expected: PASS.

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml
```

Expected: PASS.

- [ ] **Step 4: Review the final diff**

Run:

```bash
git diff --stat
git diff -- sab/report/notification_text.py sab/scheduler/runner.py .github/workflows/ai-brief.yml docs/ARCHITECTURE.md
```

Expected:

- `build_ai_brief_telegram_report_text(...)` is the only Telegram builder converted to HTML.
- `.github/workflows/ai-brief.yml` sends split `ai-brief.telegram.txt` parts with `parse_mode=HTML` only from the report send step.
- `DefaultScheduledNotifier.send_schedule(...)` passes `parse_mode="HTML"`.
- `DefaultScheduledNotifier.send_late_alert(...)` does not pass a parse mode.
- Slack builders, scan Telegram builder, and sell Telegram builder are unchanged.

- [ ] **Step 5: Commit documentation and verification updates**

Run:

```bash
git add docs/ARCHITECTURE.md
git commit -m "docs(architecture): AI Brief 텔레그램 HTML 알림 기록" -m "AI Brief 텔레그램 리포트만 HTML rich text를 사용하고 Slack 및 scan/sell 알림은 기존 형식을 유지한다는 알림 계약을 문서화한다."
```

Expected: commit succeeds.

- [ ] **Step 6: Final status check**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.

## Self-Review Notes

- Spec coverage: builder formatting, escaping, run link handling, GitHub parse mode, scheduled parse mode, skipped/failure alert exclusions, Slack exclusion, docs, and tests are covered by Tasks 1-4.
- Scope: one implementation plan is sufficient because the spec covers one subsystem: AI Brief Telegram report notification rendering and delivery.
- Type consistency: the plan keeps existing public builder names and adds small private HTML/link helpers inside `notification_text.py`.
- Out-of-scope behavior: a generic parser-aware Telegram HTML splitter remains out of scope; generated AI Brief lines are bounded so the existing splitter does not cut generated tags.
