# API

상태: Accepted (API/인터페이스 가이드)

이 문서는 현재 코드 기준의 CLI 서브커맨드와 로컬 웹 API route 계약을 정리합니다. 웹 API는 로컬 관리자 콘솔 내부 API이며, 공개 외부 API로 안정성/호환성을 보장하지 않습니다.

## 문서 상태

### 현재 제공

- `sab` CLI subcommand, 주요 option, 산출물 계약을 제공합니다.
- Next.js `web/src/app/api/**/route.ts` 기준 웹 API route, 인증 경계, 요청/응답 형태를 제공합니다.

### 실험

- OpenAPI/Swagger 문서는 아직 없습니다.
- 웹 API contract 자동 생성은 구현되어 있지 않습니다.

### 백로그

- `web/src/lib/schemas.ts`에서 API 요청 schema 표를 자동 생성하는 문서화 스크립트.
- standalone `entry` workflow dispatch API.

### 폐기 후보

- 인증 없이 Storage object를 직접 list/download하는 초기 웹 API 가정은 현재 계약이 아닙니다.

## Authentication Boundary

| Surface | Auth | Notes |
| --- | --- | --- |
| CLI `sab` | local environment credentials | `.env`/GitHub Secrets/Docker env에서 KIS, Supabase, provider secret을 읽습니다. |
| Web pages | admin session cookie | `/login`에서 `SAB_BASIC_AUTH_USER/PASS`로 로그인합니다. |
| Web APIs | admin session + same-origin/local request guard | `/api/auth/login`과 `/api/auth/logout`를 제외한 API route는 `enforceAdminApiGuard`를 사용합니다. |
| GitHub workflow dispatch | server-side `GITHUB_PAT` | `RUN_DISPATCH_ENABLED=1`일 때만 `/api/run`이 dispatch합니다. |

`/login` page는 liveness 확인용으로 비인증 접근이 가능하지만, 보호 API의 정상 여부를 의미하지 않습니다.

## CLI Interface

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab <command> [options]
```

| Command | Purpose | Key Options | Output |
| --- | --- | --- | --- |
| `scan` | watchlist/screener universe를 평가해 buy report 생성 | `--limit`, `--watchlist`, `--provider kis|pykrx`, `--screener-limit`, `--universe watchlist|screener|both`, `--markets KR,US` | `reports/YYYY-MM-DD(-n).buy.json` |
| `sell` | active holdings 평가 후 sell report 생성 | `--provider kis|pykrx`, `--holdings <path>` | `reports/YYYY-MM-DD(-n).sell.json` |
| `entry` | buy report 후보의 다음 세션 진입 조건 평가 | `--buy-report`, `--provider kis|pykrx`, `--mode PRE_OPEN|INTRADAY|AFTER_CLOSE`, `--market KR|US`, `--upload` | `reports/YYYY-MM-DD(-n).entry.json` |
| `ai-brief` | entry report의 recommendable/watch 후보를 AI brief로 요약 | `--entry-report`, `--market`, `--buy-report`, `--model-provider fake|openai`, `--model-name`, `--source-provider`, `--source-report`, `--source-api-url`, `--upload`, `--report-date` | `reports/YYYY-MM-DD(-n).ai-brief.json` |
| `ai-brief-scheduled` | runtime_state guard와 marker를 사용하는 scheduled runner | `--market`, `--schedule-role`, `--runner-role`, `--scheduled-tick`, `--attempt-id`, `--run-url`, `--source-provider`, `--model-provider`, `--dry-run`, `--guard-only` | `ai-brief` 또는 `ai-brief-skip` report, runtime_state marker |

## Report Artifacts

| Report Type | Local Pattern | Supabase Storage Pattern | Index Source |
| --- | --- | --- | --- |
| `buy` | `reports/YYYY-MM-DD(-n).buy.json` | `YYYY/MM/YYYY-MM-DD(-n).buy.json` | `report_index` |
| `sell` | `reports/YYYY-MM-DD(-n).sell.json` | `YYYY/MM/YYYY-MM-DD(-n).sell.json` | `report_index` |
| `entry` | `reports/YYYY-MM-DD(-n).entry.json` | `YYYY/MM/YYYY-MM-DD(-n).entry.json` | `report_index` |
| `ai-brief` | `reports/YYYY-MM-DD(-n).ai-brief.json` | `YYYY/MM/YYYY-MM-DD(-n).ai-brief.json` | `report_index` |
| `ai-brief-skip` | `reports/YYYY-MM-DD(-n).ai-brief-skip.json` | `YYYY/MM/YYYY-MM-DD(-n).ai-brief-skip.json` | `report_index` |

### AI Brief Artifact Notes

- `ai-brief.summary` includes `entry_count`, `recommendable_count`, `watch_count`, `preselected_count`, `recommendation_count`, `excluded_count`, `vetoed_count`, `cap_excluded_count`, `source_issue_count`, and `system_issue_count`.
- `eligible_tickers[]` is the preselected recommendable model-input ticker list after the 5-candidate cap. `watch_tickers[]` is tracked separately and never contributes to recommendation rank.
- `recommendations[]` is capped at 3 rows. Its `rank` values must match the displayed array order as contiguous `1..N`, and recommendation text must avoid automated order/execution language.
- `watch_candidates[]` records watch-only candidates with `action=WATCH`, manual reason, retrigger conditions, and optional source rows. It is displayed separately from `recommendations[]`.
- `vetoed_candidates[]` records preselected recommendable candidates that the model did not recommend. It is displayed separately from `recommendations[]` in notifications and the web report detail view.
- `source_provider_summary` records the configured source chain, provider-level `status|covered|total`, and final recommendable/watch coverage. A chain of `none` has no provider rows and zero final coverage.
- OpenAI model output uses request-local `source_refs` internally, but final artifacts keep canonical `sources[]` objects. `model_source_ref_invalid`, `model_source_ref_missing`, `model_unbacked_recommendation_dropped`, and `model_watch_source_ref_invalid` may appear in `source_issues[]` when local normalization isolates a candidate-level source-ref problem.
- `brief_state` is one of `NO_SIGNAL`, `NEEDS_REVIEW_WATCH_ONLY`, `FINAL_JUDGMENT`, or `NEEDS_REVIEW_WEAK_NEWS`. `NO_SIGNAL` means no recommendable or watch candidates; `NEEDS_REVIEW_WATCH_ONLY` means only trigger-pending watch candidates remain.
- `scripts/eval_ai_brief_recommendations.py` is the offline recommendation quality gate. The manual GitHub AI Brief workflow and scheduled runner treat `FAIL` as a stop before normal notification/success handling.

### Notification Text Contracts

- AI Brief Telegram report notifications use Telegram HTML rich text. The body is decision-first and uses only `<b>`, `<code>`, and `<a>` tags.
- Report-derived values are HTML-escaped, normalized to single-line text where needed, and length-bounded before rendering. Unsafe, malformed, too-long, or whitespace/control-character HTTP(S) `run_url` values are not emitted as Telegram links.
- GitHub Actions and the scheduled notifier split the AI Brief Telegram report body with `split_telegram_message_text()` and send each part through `sendMessage` with `parse_mode=HTML` and web previews disabled.
- AI Brief skipped notifications, scan/sell Telegram notifications, host late alerts, and Slack summaries remain plain text. Slack keeps the key-value summary format.

## Web API Routes

| Method | Path | Purpose | Request Contract | Response/Status |
| --- | --- | --- | --- | --- |
| `POST` | `/api/auth/login` | 관리자 로그인 | JSON `{ "username": string, "password": string }` | `200 { "ok": true }`, sets HttpOnly session cookie |
| `POST` | `/api/auth/logout` | 관리자 로그아웃 | no body required | `200 { "ok": true }`, clears session cookie |
| `GET` | `/api/reports` | report_index 목록 조회 | query `type=all|buy|sell|entry|ai-brief|ai-brief-skip`, `q`, `limit=1..200`, `refresh=true|false` | `ReportsListResponse` |
| `GET` | `/api/reports/detail` | Storage JSON 상세 조회 | query `key=<storage-key>`, `refresh=true|false` | report JSON |
| `POST` | `/api/run` | `scan.yml`/`sell.yml` workflow_dispatch | scan: `{ "workflow":"scan", "provider":"kis|pykrx", "universe":"KR|US|both" }`; sell: `{ "workflow":"sell", "provider":"kis|pykrx" }` | `202 WorkflowDispatchResult` |
| `GET` | `/api/holdings` | holdings 목록 | query `limit=1..200`, optional `cursor` | `{ items, nextCursor, hasMore }` |
| `POST` | `/api/holdings` | holding 생성 | `HoldingMutationInput` with required `ticker` | `201 HoldingRecord` |
| `PATCH` | `/api/holdings/[ticker]` | holding 수정 | at least one mutable holding field | `200 HoldingRecord` |
| `DELETE` | `/api/holdings/[ticker]` | holding 삭제 | no body required | `200 { "deleted": true, "ticker": string }` |
| `POST` | `/api/holdings/[ticker]/add-buy` | 추가매수 원자 갱신 | header `Idempotency-Key: <uuid>`, JSON `{ "buy_quantity": number, "buy_price": number, "buy_date"?: "YYYY-MM-DD" }` | `200 HoldingRecord`; mismatch `409` |
| `PATCH`/`DELETE` | `/api/holdings/[...ticker]` | class ticker alias route | same as `[ticker]` | same as `[ticker]` |
| `POST` | `/api/holdings/add-buy/[...ticker]` | class ticker add-buy alias route | same as `[ticker]/add-buy` | same as `[ticker]/add-buy` |
| `GET` | `/api/holdings/yaml` | holdings YAML export | no body required | YAML snapshot payload |
| `POST` | `/api/holdings/yaml` | holdings YAML import dry-run/apply | JSON `{ "document": string, "apply": boolean }` | `{ mode, summary }` |
| `POST` | `/api/holdings/toss-sync` | Toss Securities holdings dry-run/apply | dry-run: `{ "mode": "dry-run" }`; apply: `{ "mode": "apply", "diffHash": "sha256:...", "confirmationText": "APPLY TOSS HOLDINGS" }` | `{ mode, diffHash, applyBlocked, summary, changes, blockedRows, targetRows }`; apply may return `409` for blocked/stale diffs |
| `GET` | `/api/tickers/search` | ticker directory 검색 | query `q=1..120 chars`, `limit=1..50` | ticker search payload |
| `GET` | `/api/tickers/recent-candidates` | 최근 buy 후보 | query `limitReports=1..50`, `limitCandidates=1..100` | recent candidate payload with `pattern: string \| null` per candidate |

### Holdings Contract Notes

- `HoldingRecord`/current snapshots include nullable `entry_pattern: string | null`.
- `HoldingMutationInput` accepts optional `entry_pattern?: string | null`. A non-null `entry_pattern` create/patch payload must include `quantity > 0` in the same payload. Explicit `entry_pattern: null` clears without requiring quantity. If a mutation owns `quantity: 0`, persistence normalizes `entry_pattern` to `null`.
- YAML import/replace-all inputs are the only path where an omitted active `entry_pattern` key can mean preserve-existing. YAML export always owns the key, including `entry_pattern: null`.
- Add Buy remains quantity-only. `/api/holdings/[ticker]/add-buy` does not accept marker fields such as `entry_pattern`; the RPC preserves existing active markers and clears stale markers when reactivating `quantity=0` rows.
- `/api/tickers/search` remains ticker/name-only. `/api/tickers/recent-candidates` reads the latest buy report candidates and returns `{ ticker, name, pattern }`, where invalid or missing buy-report patterns are normalized to `null`.
- `/api/holdings/toss-sync` fetches Toss holdings with server-side credentials, normalizes safe rows into the holdings snapshot contract, preserves app-owned metadata for matched rows, and returns a grouped reconciliation with a deterministic `diffHash`. Blocked rows such as unknown enum values, invalid decimals, or unresolved US exchange suffixes set `applyBlocked=true`. Apply refetches Toss and Supabase, recomputes the diff/hash, requires `confirmationText: "APPLY TOSS HOLDINGS"`, rejects blocked or stale diffs with `409`, and only then calls the Supabase replace-all RPC. The browser displays these rows in the Holdings Toss Sync panel and does not receive Toss access tokens or full account identifiers.

## Ticker Contract

| Market | Format | Example | Notes |
| --- | --- | --- | --- |
| KR | six digits | `005930` | KRX code. |
| US | symbol + exchange suffix | `AAPL.NAS`, `BRK.B.NYS` | Supported suffixes: `.NAS`, `.NYS`, `.AMS`. |

`.US` suffix is intentionally rejected because it is ambiguous.

## Request Examples

```bash
curl -sS -X POST http://127.0.0.1:55300/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"replace-with-password"}'
```

```bash
curl -sS 'http://127.0.0.1:55300/api/reports?type=buy&limit=30'
```

```bash
curl -sS -X POST http://127.0.0.1:55300/api/run \
  -H 'Content-Type: application/json' \
  -d '{"workflow":"scan","provider":"kis","universe":"both"}'
```

The examples above require a valid authenticated session cookie in normal browser/API use. They are shape examples, not a complete authentication walkthrough.

## Error Handling

| Condition | Typical Status | Notes |
| --- | ---: | --- |
| Missing/invalid admin session | `401` or redirect from page middleware | Protected API route guard. |
| Same-origin/local guard failure | `403` | Local-console hardening. |
| Schema validation failure | `400` | Zod schema errors are returned as request errors. |
| GitHub dispatch disabled | `503`/feature disabled response | Depends on `/api/run` branch. |
| Supabase upstream error | matching upstream status or `500` | Route logs include request metadata, not secrets. |
| Add-buy idempotency payload mismatch | `409` | Same idempotency key with different payload. |

## Source Of Truth

- CLI options: `sab/__main__.py`
- Web request schemas: `web/src/lib/schemas.ts`
- Web route implementations: `web/src/app/api/**/route.ts`
- Shared response types: `web/src/lib/types.ts`
- Supabase schema/RPC: `supabase/migrations/`

## Verification

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab --help
pnpm --dir web run test:coverage
```

NOT_RUN: 이 문서 작성 중 CLI와 web test 전체를 실행하지 않았다면 최종 보고서에 별도로 기록합니다.
