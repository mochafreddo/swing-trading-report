# Task 7 report — run-kind report index and atomic Decision Board persistence

## 결과와 전파 경로

Decision Board V0 envelope의 `idempotency_key`가 Python contract, JSON Schema, Web Zod mirror에 같은 strict `sha256:` + 64 lowercase hex 규칙으로 추가됐다. 전파 경로는 다음과 같다.

`validated envelope -> deterministic UTC/run-kind/run-id/full-digest key -> atomic local canonical bytes -> Supabase Storage exact-byte create/confirm -> service-role-only report_index identity row -> Web server-only strict parser/query/cache`

runner/CLI/scheduler, RunJournal, detail renderer, notification, Toss/order 호출은 이 task에 추가하지 않았다. Legacy report type과 duplicate-suffix naming/upload는 유지했다.

## Identity와 canonical separation

- key grammar: `YYYY/MM/YYYY-MM-DD.decision-board.{entry|holding}.<safe-run-id>.<full-64-lower-hex>.json`
- basename은 local filename과 Storage object key에서 동일하다.
- `created_at`은 offset 필수이고 key partition/date는 UTC로 계산한다.
- run ID는 1-128자 ASCII letter/digit/underscore/hyphen만 허용한다.
- idempotency digest는 축약하지 않는다.
- account/trigger/ticker/quantity/price/P&L/notes/tags/secret는 key와 index row에 넣지 않는다.
- envelope `idempotency_key`는 `decision_payload` 밖의 metadata다. 같은 payload가 다른 run envelope에 있어도 canonical payload bytes/hash는 변하지 않는다.

## Local concurrency/crash proof

writer는 caller graph를 strict canonical JSON bytes로 한 번 snapshot한 뒤 alias-free built-in graph를 validate하고, 같은 snapshot bytes와 graph에서 key/filename/payload를 만든다. caller mutation, dict/list subclass, cycle, non-finite number는 key/bytes 사이에 끼어들 수 없다. real directory를 `O_NOFOLLOW`로 열고 target별 persistent advisory `flock`, same-directory private temp, file `fsync`, hard-link `O_EXCL` equivalent create, directory `fsync`를 사용한다. lock `fstat`/`flock` 실패는 열린 FD를 닫고, 획득 직후 pathname과 locked inode가 달라진 multiple-inode race는 fail closed한다. open inode와 final directory entry도 다시 비교하므로 symlink/non-regular target과 replacement race를 거부한다.

검증은 deterministic caller-mutation interleaving, strict graph rejection, `fstat`/`flock` FD cleanup, persistent lock pathname replacement, thread/process 동일 bytes convergence, 다른 bytes one-winner+typed-conflict, 다른 run uniqueness, serializer/write/directory-fsync failure cleanup, symlink/directory/replacement race를 포함한다. Review-fix local+Supabase focused 묶음은 45 passed다.

## Storage/index rollback matrix

| Storage 상태 | Index 결과 | 동작 |
| --- | --- | --- |
| 새 object 생성 | authoritative row 확인 | 성공 |
| 새 object 생성 | insert/readback 실패 뒤 matching row 재확인 | 경쟁 writer가 repair한 것으로 수렴, object 보존 후 성공 |
| 새 object 생성 | 재확인 결과 absent/mismatch/error | object 보존, `cleanup_failed=true`, `rollback_skipped=true`인 explicit partial failure |
| 기존 object, exact equal bytes | missing/equal index row | full identity ignore-duplicate insert 뒤 authoritative readback으로 repair/confirm |
| 기존 object, exact equal bytes | index 실패 | 기존 object를 삭제하지 않고 index error |
| 기존 object, different bytes | 해당 없음 | typed idempotency conflict, index request 없음 |
| 기존 index identity, different metadata | authoritative mismatch | overwrite하지 않고 typed idempotency conflict |

Storage와 report index를 묶는 원자 transaction/conditional delete가 없으므로 `GET absent -> competing index insert -> object DELETE` race를 단순 재확인만으로 막을 수 없다. 따라서 Decision Board index failure 뒤에는 object delete를 시도하지 않는다. deterministic fake interleaving에서 absent 응답 직후 경쟁 index insert를 만들고 delete가 0회인지 확인했다. matching/absent/mismatch/HTTP error/request error/invalid JSON matrix와 legacy Supabase storage를 합친 regression은 103 passed다. 모든 unit test는 recorded fake HTTP만 사용했고 network call을 하지 않았다.

## Migration/RLS/grant evidence

Migration은 additive nullable `run_kind`, `run_id`, `idempotency_key`, `decision_created_at`과 Decision Board field-set check, 두 nullable-safe unique index, partial latest lookup index를 추가한다. identity index는 PostgREST의 full-column `on_conflict`가 predicate 없이 infer할 수 있어야 하므로 partial index로 만들지 않았다. legacy row는 네 필드가 null이어야 하며 PostgreSQL unique NULL semantics 때문에 기존 PK/legacy index/row와 충돌하지 않는다. Static RED 3 failures에서 GREEN 3 passed로 전환한 뒤 partial-index inference 회귀 RED 1건을 추가해 최종 4 passed로 고정했다.

Disposable `public.ecr.aws/supabase/postgres:17.6.1.156`에서 production-equivalent legacy row를 먼저 만든 뒤 migration을 적용했다.

- legacy row count: 1, migration 뒤 보존
- latest ENTRY same timestamp tie: `run-b`
- latest HOLDING: `hold-z`
- `relrowsecurity=true`, `relforcerowsecurity=true`
- anon/authenticated SELECT privilege: false; anon direct SELECT: permission denied
- service-role CRUD grant와 3개 Decision Board index 확인
- legacy identity non-null, missing Decision identity, duplicate idempotency insert 모두 거부
- exact `ON CONFLICT (bucket_id, report_type, run_kind, idempotency_key) DO NOTHING`이 실행되고 같은 identity 두 번째 row를 무시해 row count 1 유지
- `supabase db lint --schema public --level warning --fail-on error`: no schema errors
- `supabase db advisors --type all --level warn --fail-on error`: no issues

Disposable container는 검사 뒤 stop/auto-remove했다. linked/production Supabase는 변경하지 않았다.

## Web contract proof

`ReportType`은 `decision-board`를 포함한다. Server-only `ReportIndexRow` parser는 nullable identity field를 legacy row에 null로 정규화하고 Decision Board row에서는 key/date/run-kind/run-id/full-idempotency/offset timestamp/privacy-neutral fields를 함께 검증한다. malformed row는 skip하며 legacy shape로 강등하지 않는다.

`runKind`는 `type=decision-board`에서만 허용하고 ENTRY/HOLDING을 query filter와 cache identity에 포함한다. Decision Board order는 `decision_created_at.desc,run_id.desc,report_key.desc,bucket_id.desc`이고 dedicated latest lookup은 explicit type/run-kind filter를 사용한다. Decision Board detail key는 Python identity처럼 surrounding whitespace를 거부하고, legacy detail key의 기존 trim 동작은 유지한다. Review-fix key/detail focused tests는 16 passed이며 lint, format, typecheck도 통과했다.

## 전체 검증

- T1/T6 + T3/T4/T5 focused regressions: 431 passed.
- docs state contract: 21 passed.
- `UV_CACHE_DIR=.uv-cache mise exec -- just quality`: Ruff, 295-file format check, mypy 282 sources, pytest 2862 passed / 8 skipped / 1297 dependency warnings.
- `UV_CACHE_DIR=.uv-cache mise exec -- just ci-web`: install/lint/format/typecheck, 91 files / 649 tests, coverage gate, Next 16 production build all passed.
- `git diff --check`: passed.

## Rollout/rollback

순서는 `migration -> Python producer/upload adapter -> Web server consumer`다. Web이 새 column을 select하므로 migration 전에 Web을 배포하지 않는다. 현재 producer runner와 UI control은 없으므로 이 task 자체가 자동 실행을 시작하지 않는다.

Rollback은 producer를 먼저 멈춘 뒤 Web/Python application을 되돌린다. Additive migration은 legacy와 공존하므로 기본적으로 유지한다. 적용된 column/index 또는 persisted Decision Board rows/object 삭제는 데이터 파괴이므로 자동 rollback하지 않고 forward-fix를 우선한다.

## 남은 불확실성

- linked production project target, rollout window, 승인자는 저장소에서 확인할 수 없다.
- 원격 Storage/PostgREST 실환경 round-trip은 수행하지 않았고 exact HTTP behavior는 fake-session과 disposable Postgres catalog/query로 분리 검증했다.
- runner/CLI/scheduler, RunJournal, UI detail/control, notification은 후속 task 소유다.
- Web report parser의 optional-field interface를 discriminated union으로 바꾸는 maintainability minor는 공개 동작이나 이번 보안 경계를 바꾸지 않아 후속 리팩터링으로 남겼다.
- Toss/order endpoint와 live account data는 접근하지 않았다.
