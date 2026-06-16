# AI Brief Telegram Rich Text Design

상태: Accepted
Status: Approved design, pending written-spec review
Date: 2026-06-16
Scope: AI Brief Telegram report message only

## Context

`sab/report/notification_text.py` renders Telegram and Slack notification text from
generated report artifacts. AI Brief Telegram output is currently plain text with
key-value lines, and delivery paths send it through Telegram `sendMessage` without
`parse_mode`.

The relevant AI Brief delivery paths are:

- `.github/workflows/ai-brief.yml`, which writes `ai-brief.telegram.txt` and sends it
  through Telegram for manual or scheduled runs when notifications are enabled.
- `sab/scheduler/runner.py`, where `DefaultScheduledNotifier.send_schedule()` builds
  and sends the scheduled AI Brief body.

Telegram Bot API `sendMessage` supports rich text formatting through
`parse_mode=HTML`, including bold text, inline code, and labeled links. This is enough
for the desired UI/UX improvement without changing the transport API.

## Problem

AI Brief Telegram messages are hard to scan because the highest-value decision signal
is visually mixed with metadata and diagnostics. The current shape makes the reader
work too hard to answer the first operational question:

```text
Do I have a source-backed candidate to review today?
```

The project needs a richer but still conservative Telegram format that surfaces the
decision first, keeps diagnostics available, and does not increase notification
delivery risk.

## Goals

- Improve only the AI Brief Telegram report body.
- Use Telegram HTML rich text through the existing `sendMessage` API.
- Make the message decision-first: judgment, count, and top candidates appear before
  diagnostics.
- Keep the format restrained: bold labels, inline code, labeled links, and line breaks.
- Escape all report-derived text before embedding it in HTML.
- Update every path that sends the AI Brief report body so it passes `parse_mode=HTML`.
- Preserve Slack summaries, report JSON contracts, recommendation logic, and
  scan/sell Telegram behavior.

## Non-Goals

- Do not change scan or sell Telegram messages.
- Do not change AI Brief skipped, late-alert, or host-failure operational alerts.
- Do not change Slack formatting.
- Do not change source collection, recommendation, risk, or quality-gate logic.
- Do not introduce Telegram `sendRichMessage` or a new Telegram transport abstraction.
- Do not implement a fully HTML-aware Telegram message splitter in this pass.

## Constraints

- Keep Telegram `sendMessage`.
- Keep `disable_web_page_preview=true`.
- Keep the 4096-character Telegram message limit and existing chunking behavior.
- Avoid emoji and heavy visual decoration.
- Keep all report-derived values escaped before insertion into HTML.
- Render links only when the URL is non-empty and starts with `http://` or `https://`.
- Keep item limits compact: AI Brief recommendations stay capped at the existing
  display maximum of 3.

## Approved Approach

Use `sendMessage` with `parse_mode=HTML` and a small safe-formatting layer inside
`sab/report/notification_text.py`.

Alternatives considered:

- Partial path update: faster, but risks workflow/scheduler output drift.
- Telegram `sendRichMessage`: more expressive, but larger API and compatibility risk
  for an operational notification.

The approved approach is the smallest safe change: it keeps the current builder and
delivery model while improving the presentation.

## Message Structure

The AI Brief Telegram body should be ordered for decision-making:

1. Title: bold `SAB AI Brief`.
2. Decision summary: market, generated time, `brief_state`, and the main decision
   sentence.
3. Recommendations: count and up to 3 candidates.
4. Watch/veto sections: present only when data exists.
5. Diagnostics: source/system issue counts, source chain/provider summary, and first
   source/system issues.
6. Footer: storage key and run link.

Example shape:

```html
<b>SAB AI Brief</b>
시장 <code>US</code> · 생성 <code>2026-05-05T08:40:00+09:00</code>

<b>판단</b>
<code>FINAL_JUDGMENT</code> 뉴스 근거 확인된 추천 후보 2건

<b>추천 후보 2건</b>
1. <b>AAPL.NAS Apple</b> · <code>HIGH</code>
   source-backed context supports manual review
   근거 <code>1</code>개 · Apple supply chain update

<b>진단</b>
source <code>0</code> · system <code>0</code>

<a href="https://github.com/example/repo/actions/runs/789">실행 보기</a>
```

## Formatting Rules

- Use `<b>` for the title, section names, and ticker/name labels.
- Use `<code>` for short identifiers such as market, model, state, confidence,
  counts, and storage keys.
- Escape all dynamic text with an HTML escape helper before wrapping it in tags.
- Build tags through helpers instead of interpolating raw report strings directly
  into HTML.
- Render `run_url` as `<a href="...">실행 보기</a>` only for safe HTTP(S) URLs.
- Render non-HTTP(S) or empty URLs as escaped plain text or omit the link if empty.
- Keep source title, issue message, and rationale truncation behavior conservative.
- Keep watch and veto sections conditional so empty placeholders do not add noise.

## Data Flow

`build_ai_brief_telegram_report_text(...)` remains the single AI Brief Telegram body
builder. It will return Telegram HTML instead of plain text.

The caller flow stays the same:

```text
AI Brief JSON artifact
  -> build_ai_brief_telegram_report_text(...)
  -> split_telegram_message_text(...)
  -> Telegram sendMessage(parse_mode=HTML)
```

Slack builders continue to return plain key-value text. Scan/sell Telegram builders
continue to return their current plain text bodies.

## Delivery Path Changes

Update only the paths that send the AI Brief report body:

- `DefaultScheduledNotifier._post_telegram_message()` should send
  `parse_mode=HTML` for AI Brief schedule messages.
- `.github/workflows/ai-brief.yml` should pass `-d parse_mode=HTML` when sending
  `ai-brief.telegram.txt`.

Skipped schedule notifications in `.github/workflows/ai-brief.yml`, host wrapper
failure alerts, scan notifications, and sell notifications stay unchanged.

If a shared private posting helper makes `parse_mode` hard to scope, it should accept
an optional parse mode argument and default to the current plain-text behavior.

## Error Handling

- If Telegram rejects malformed HTML, keep existing failure behavior. Scheduled
  delivery remains required where it is already required.
- Do not catch and suppress HTML parse failures inside the builder.
- Prevent malformed HTML by escaping report-derived text and testing hostile strings
  containing `<`, `>`, `&`, and quotes.
- Because the existing splitter is line-based and not HTML-aware, keep AI Brief output
  compact. General HTML-aware chunking is intentionally out of scope.

## Testing

Update `tests/test_notification_text.py`:

- Assert AI Brief Telegram includes `<b>`, `<code>`, and safe `<a href=...>` output.
- Assert report-derived ticker names, rationale, source titles, and issue messages
  are escaped.
- Preserve key state coverage for `NO_SIGNAL`, `NEEDS_REVIEW_WATCH_ONLY`,
  `FINAL_JUDGMENT`, `NEEDS_REVIEW_WEAK_NEWS`, and model/system issue cases.
- Confirm scan/sell Telegram builders are not converted as part of this change.

Update workflow/scheduler tests as needed:

- Assert `.github/workflows/ai-brief.yml` sends AI Brief Telegram with
  `parse_mode=HTML`.
- Assert skipped Telegram notification remains plain text unless a future spec changes
  it.
- Assert scheduled notifier POST payload includes `parse_mode=HTML` for AI Brief
  schedule delivery.

Recommended targeted verification:

```text
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_notification_text.py tests/test_ai_brief_workflow.py
```

If scheduled runner delivery tests are changed, also run the relevant
`tests/test_scheduled_ai_brief_runner.py` subset.

## Documentation

Update `docs/ARCHITECTURE.md` to clarify that:

- AI Brief Telegram report notifications use Telegram HTML rich text.
- Slack summaries remain key-value text.
- Scan/sell Telegram messages are outside this scoped change.

No `docs/STRATEGY.md` update is needed because the strategy and recommendation logic
do not change.

## Acceptance Criteria

- AI Brief Telegram report output is decision-first and uses Telegram HTML rich text.
- All report-derived text in the HTML body is escaped.
- AI Brief Telegram delivery paths pass `parse_mode=HTML`.
- Slack, scan/sell Telegram, and operational skipped/failure alerts are unchanged.
- Targeted tests pass.
