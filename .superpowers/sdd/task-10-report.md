# Task 10 report — Reports Decision Board API/UI

## 결과와 전파 경로

인증된 기존 `/reports` 여정에 Decision Board V0 전용 `ENTRY|HOLDING` lane을 추가했다.

```text
T7 report_index identity + deterministic storage key
  -> strict list query/run-kind cache identity
  -> T1 envelope structure + payload-hash + key identity validation
  -> authenticated API / SSR prefetch
  -> URL and browser-navigation state
  -> dedicated list/detail states

T9 private local RunJournal
  -> optional bounded server-only reader
  -> authenticated no-store endpoint / SSR prefetch
  -> distinct missed/stale warning panel
```

기존 report type, key normalization, detail/list caching과 렌더링은 그대로 유지했다. Decision Board에만 exact lane/key/envelope 규칙을 적용하며, broker/order mutation, notification, provider network, launchd activation, GitHub Actions 변경은 추가하지 않았다.

## API와 데이터 경계

- `/api/reports`는 `type=decision-board`일 때 exact `runKind=ENTRY|HOLDING`을 필수로 받고, 다른 type의 `runKind`는 거부한다. lane은 Supabase index query와 server/client list cache identity에 포함된다.
- list item은 T7 parser가 검증한 public `runKind`와 deterministic `runId`만 노출한다.
- `/api/reports/detail`은 T7 deterministic key를 파싱하고 Decision Board row가 index에 존재해야만 object를 읽는다. T1 Web schema, recomputed payload hash, key의 `run_kind/run_id/idempotency_key`와 envelope의 exact equality를 모두 검증한다.
- Decision Board key는 URL에서도 surrounding whitespace를 허용하지 않는다. legacy key의 기존 trim 동작은 유지한다.
- malformed/forged/wrong-identity/stale-hash/private-key content는 raw fallback 없이 sanitized typed 422 `invalid_decision_board_report`로 끝난다. invalid object는 React와 detail cache에 도달하지 않는다.
- detail cache identity는 bucket/key와 deterministic idempotency content identity를 포함한다.

## 선택적 local journal 경계

- `DECISION_BOARD_JOURNAL_DIR`가 없으면 path나 오류를 노출하지 않고 `UNAVAILABLE/NOT_CONFIGURED`를 반환한다.
- configured path는 absolute normalized non-root directory여야 하고, 전체 component와 final directory의 symlink/type/private mode를 확인한다.
- record는 safe canonical T9 basename, `O_NOFOLLOW`, regular/single-link/private mode, 64 KiB byte bound, inode/size stability, canonical JSON + final newline, Web RunJournal schema/chronology, filename identity를 모두 통과해야 한다.
- scan/output limit은 각각 hard cap 1000/100이고, 결과는 `MISSED_EXPECTED|STALE_INCOMPLETE`만 newest-first deterministic order로 반환한다.
- malformed, unsafe, symlinked, changed record 또는 invalid bound는 path/raw bytes 없이 `UNAVAILABLE/UNSAFE_OR_INVALID`로 fail closed한다.
- endpoint는 기존 admin/local/same-origin guard와 no-store response를 사용한다. 클라이언트도 response shape와 T9 record schema를 다시 확인하며 invalid payload를 warning data로 렌더링하지 않는다.

## UI 계약

- report type selector에 `Decision Board`를 추가하고 lane selector를 필수로 표시한다. lane은 URL, SSR, client fetch, cache, refresh, browser back/forward reconciliation에 유지된다.
- SSR과 client navigation은 filter lane과 다른 Decision Board key를 선택하지 않고 URL을 안전한 state로 정리한다.
- list row는 report type, lane badge, public run ID를 표시한다.
- PUBLISHED detail은 run identity/time/status, ticker/exchange, item status/action, reason code, public evidence claim/entailment를 표시한다. HOLDING `SELL`은 별도 시각 스타일을 유지한다.
- BLOCKED는 shared issue code만 표시하고 directional table을 만들지 않는다. empty published universe는 정상 empty state다.
- raw toggle은 server에서 이미 hash/key/privacy validation을 통과한 public envelope에만 적용된다.
- local journal panel은 report status와 별도임을 설명하고 missed/stale 관측만 표시한다. order/notification/action button은 없다.

## TDD 증거

각 slice는 production 변경 전에 RED를 확인했다.

1. exact query/list/URL/SSR slice: 4개 test file에서 6 failures를 확인한 뒤 GREEN.
2. strict detail slice: stale hash, forged identity, private metadata가 기존 200으로 통과하는 3 failures를 확인한 뒤 sanitized 422로 GREEN.
3. journal reader/route slice: module/route import failure를 각각 확인한 뒤 reader 4, endpoint 포함 6 tests GREEN.
4. UI state slice: selector/detail/list/panel/URL의 7 failures 또는 missing module을 확인한 뒤 component 묶음 GREEN.
5. fixture-only journey: mocked navigation이 URL replace 뒤 state를 재주입하지 않는 harness 문제를 분리해 고쳤고, ENTRY 선택/detail BUY -> HOLDING 전환/detail SELL -> stale warning -> no order/notification control을 shared fixtures와 fake fetch만으로 통과했다.
6. late boundary regressions: lane과 key 불일치가 client에서 선택되는 1 failure, whitespace-normalized Decision Board URL key가 404로 진행되는 1 failure, alternate-case provider exception metadata가 200으로 통과하는 1 failure, malformed journal client payload가 무검증되는 failure를 각각 RED로 확인한 뒤 fail-closed GREEN으로 고정했다.

최종 focused Web 묶음은 `17 files / 162 tests`가 통과했다.

## 검증

- fixture/component journey: shared Decision Board fixtures와 local fake fetch만 사용, live server/network 없음.
- `UV_CACHE_DIR=.uv-cache mise exec -- uv run python scripts/check_next_app_routes.py`: 통과.
- `mise exec -- pnpm --dir web run lint`: 통과.
- `mise exec -- pnpm --dir web run format:check`: 통과.
- `mise exec -- pnpm --dir web run typecheck`: 통과.
- `mise exec -- just ci-web`: lint/format/typecheck, `95 files / 684 tests`, coverage gate, Next production build 통과.
- `UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q tests/test_decision_board_contracts.py`: `42 passed`.
- `mise exec -- just quality`: Ruff, Python format, mypy, pytest `3001 passed / 8 skipped` 통과. dependency deprecation warning 1297건은 기존 경고다.
- `git diff --check`: 통과.

## Self-review

- privacy: account/quantity/price/P&L/notes/tags/secret/provider exception/traceback 계열 field key를 recursive 거부하고 invalid response/log에 payload를 넣지 않는다. journal path/raw error도 응답하지 않는다.
- exact type/identity: lane은 uppercase exact enum이며 key, index, envelope run kind/run ID/idempotency를 결속한다.
- cache: list lane과 detail content identity가 cache key에 포함되고 invalid detail은 cache되지 않는다.
- URL/SSR/navigation: SSR과 initial hydration, browser reconciliation 모두 lane-mismatched key를 거부한다.
- invalid payload: detail은 typed 422, journal은 safe unavailable로 fail closed하며 raw fallback이 없다.
- legacy: legacy query/key/detail/cache/component tests와 전체 Web/Python gates를 통과했다.
- authority: read-only report/journal consumer만 추가했으며 order, notification, scheduler, workflow, remote data mutation을 호출하지 않았다.

## Rollout, rollback, 남은 불확실성

rollout 순서는 T7 migration/index와 producer가 준비된 뒤 Web consumer를 배포하고, journal panel은 서버가 읽을 수 있는 reviewed private absolute T9 journal directory를 명시적으로 설정할 때만 opt-in한다. 환경 변수를 설정하지 않으면 panel은 비활성 unavailable 상태다. 이번 변경은 Docker mount, production env, launchd template 설치/활성화를 수행하지 않았다.

rollback은 Web API/components를 되돌리고 `DECISION_BOARD_JOURNAL_DIR`를 제거하면 된다. Supabase report object/index와 local journal은 read-only 소비 대상이므로 삭제하거나 변형하지 않는다.

live Supabase round-trip, container journal mount, 실제 브라우저/server smoke는 수행하지 않았다. 요구된 offline fixture-only component journey와 fake API boundary, Next production build로 검증했으며, host/container별 optional journal path wiring은 별도 운영 승인 사항으로 남는다.
