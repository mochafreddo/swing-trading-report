# Portfolio Mandate T16 persistence rehearsal

상태: Implemented and usable (disposable local-only)

T16은 기존 A1 persistence 계약을 실제 provider나 운영 writer에 연결하지 않고 반복
실행할 수 있는 동작 prototype이다. `PortfolioMandatePersistenceT16`은 database
connection을 소유하지 않으며, 호출자가 별도로 검증한 executor만 주입받는다. 생성
직후에는 default-off이고 `writer_enabled=true`와
`target_kind=DISPOSABLE_LOOPBACK`을 동시에 지정해야 SQL을 실행한다.

## 기존 계약 재사용

새 migration은 추가하지 않았다. 전용 loopback PostgreSQL 17.11의 빈 database에 기존
`supabase/migrations/20260828230000_create_portfolio_mandate_a1.sql`만
`--single-transaction`으로 적용한다. 하네스는 적용 전에 server address, port,
database prefix, data directory, session user, exact server version과 blank state를
검증한다. 끝부분에 의도적 오류를 붙인 migration 복제본이 schema와 NOLOGIN role을
모두 rollback하는 것도 실제 적용 전에 확인한다.

## Rehearsal journey

1. 합성 issuer, instrument, broker snapshot/allocation, active mandate, draft mandate,
   journal과 decision projection을 seed한다.
2. existing `activate_mandate_version_a1` RPC를 authenticated synthetic actor로 호출한다.
3. 같은 full payload를 재호출해 `ALREADY_ACTIVATED`를 확인한다.
4. `service_role` SELECT로 기존 decision이 `SUPERSEDED`, `eligible=false`인지 project한다.
5. 새 transaction 안에서 journal update가 `APPEND_ONLY_EVENT`로 거부되는지 확인하고,
   `supersedes_event_id`를 가진 합성 correction event를 append한다.
6. correction과 유일한 source slice로 projection을 다시 만들고 expected semantic row가
   하나인지 확인한다.
7. transaction을 rollback한 뒤 원래 projection이 byte-for-value 수준의 typed 결과로
   유지되고 correction event가 남지 않았는지 확인한다.

Rebuild는 source mandate version에 slice가 정확히 하나일 때만 row를 만든다. 매칭이
0개 또는 여러 개면 추정하지 않고 fail closed한다. Rehearsal transaction 밖에서는
기존 activation 결과만 유지된다.

## 권한과 비활성 경계

RLS와 SQL grant는 서로 다른 계약으로 검사한다. 모든 A1 table은 RLS가 enable/force된
상태여야 하며 `service_role`은 SELECT와 허용된 non-user RPC만 가진다. User activation은
`authenticated` role, `auth.uid()`와 저장된 owner를 함께 확인한다. 이 prototype은
runtime command, report route, scheduler, notification, order, provider 또는 deploy
경로에서 import하거나 생성하지 않는다.

기존·live DB migration apply, backfill, writer activation, 실제 mandate activation과
production promotion은 모두 `REQUIRES_SEPARATE_APPROVAL`이다. 실제 Supabase나 broker에
연결하지 않았으며 provider 결과는 `NOT_EVALUATED`다.

## 검증

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q \
  tests/test_portfolio_mandate_persistence_t16.py \
  tests/test_portfolio_mandate_migration.py
```

Disposable PostgreSQL 계약은 opt-in environment와 새 전용 cluster에서 다음 test
selection으로 실행한다.

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q \
  tests/test_portfolio_mandate_postgres_contracts.py \
  -k 'a1_migration_applies_with_least_privilege_roles or \
  activation_commits_version_slice_journal_and_projection_together or \
  t16_writer_projects_and_rebuilds_with_rollback or \
  predicate_authority_requires_structured_evidence_and_is_append_only'
```
