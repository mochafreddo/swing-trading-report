# Portfolio Mandate T17 dogfood evidence

상태: Accepted (implemented and usable, recurring local-only evidence)

이 문서는 T13–T16의 local vertical journey에서 기대 결과와 실제 결과를 함께 기록한다.
모든 fixture와 actor ID는 합성이며 외부 계정·주문·credential을 포함하지 않는다.

## T13

T13: `IMPLEMENTED_AND_USABLE`

- Build/commit: `800bccd` (`feat(mandate): LONG_TERM 합성 정책을 Today에 연결한다`)
- Data mode: `SYNTHETIC · LOCAL_ONLY`
- 기대 결과: representative, stale, conflicting, predicate fulfilled/not fulfilled와
  `UNCLASSIFIED · NO ADVICE`를 deterministic truth table로 compile하고 `/today`에서
  375/768/1280px 모두 읽을 수 있어야 한다.
- 실제 결과: 8개 합성 case가 Python과 Web에서 동일하게 replay됐다. 최초 375px
  dogfood에서는 LONG_TERM grid가 두 열로 남아 카드가 압축되는 반응형 결함을 찾았다.
- 재현 단계: Docker `/today`를 375px viewport로 열고 `LONG_TERM · SYNTHETIC` lane의
  computed grid column 수를 확인한다. 수정 전에는 2, 수정 후에는 1이다.
- Sanitized evidence: `web/fixtures/portfolio-long-term.t13.synthetic.json`,
  Python 4 tests, Web targeted 14 tests, Docker 375/768/1280 horizontal overflow 0.
- Regression test: `web/src/components/__tests__/long-term-synthetic-lane.test.tsx`의
  `collapses the LONG_TERM grid to one column at the mobile breakpoint`.
- Fix commit: `800bccd`에 mobile media rule과 regression을 함께 포함했다.
- 남은 NOT_EVALUATED: 실제 holding intent, 실제 filing freshness/provider capability,
  production mandate activation과 LONG_TERM 방향성 promotion.

## T14

T14: `IMPLEMENTED_AND_USABLE`

- Build/commit: `a010c9f` (`feat(web): Mandate Evidence Outcome dogfood를 추가한다`)
- Data mode: `SYNTHETIC FIXTURE · LOCAL_ONLY · PUBLIC_PROJECTION_ONLY`
- 기대 결과: correction, empty, loading, stale, blocked, ambiguous, invalid-contract를
  URL-backed native link로 이동하고 refresh 뒤 선택을 유지하며 375/768/1280px에서
  overflow와 private field가 없어야 한다.
- 실제 결과: 최초 구현 검토에서 loading/stale/ambiguous/invalid-contract browser 상태가
  누락됐고 invalid selection이 sentinel string에 의존하는 결함을 찾았다. 명시적 selection
  variant와 상태별 fixture/UI/E2E를 추가한 뒤 Playwright fixture-only journey 3개와
  component/route targeted test 23개가 통과했다. unexpected external request는 0개였다.
- 재현 단계: Docker에서
  `/today?dogfood=corrected-lineage#mandate-evidence-outcome`을 연 뒤 Empty link에 focus하고
  Enter, reload, Loading/Stale/Blocked/Ambiguous/invalid-contract 선택 순으로 실행한다.
- Sanitized evidence: `web/fixtures/portfolio-dogfood.t14.synthetic.json`과
  `web/e2e/decision-board-reports.spec.ts`의
  `fixture-only /today Mandate Evidence Outcome journey`.
- Regression test: public/private field exclusion, bounded query, explicit selection variant,
  모든 필수 상태, native link와 selection retention을 component/route/E2E tests가 고정한다.
- Fix commit: `01d0830`이 누락 상태와 sentinel 기반 selection을 수정했다.
- 남은 NOT_EVALUATED: 실제 private holding, provider history, DB projection writer와
  production UI promotion.

## T15

T15: `IMPLEMENTED_AND_USABLE`

- Build/commit: `54fc984` (`feat(outcome): provider-free history adapter를 추가한다`)
- Data mode: `RECORDED` 또는 bounded `REDACTED_IMPORT`; provider state는 항상
  `NOT_EVALUATED`.
- 기대 결과: 두 page cursor chain이 완전할 때만 O1 lineage로 flatten하고 linked,
  unlinked, ambiguous, partial fill, correction을 replay하며 cross-page duplicate fill과
  private import 위반을 거부해야 한다.
- 실제 결과: 최초 구현 검토에서 redacted mapping이 bounded bytes parser를 우회할 수 있는
  privacy 경계 결함을 찾았다. recorded mapping과 redacted bytes entrypoint를 분리한 뒤
  T15 6 tests와 기존 O1 28 tests가 통과했다. CLI replay는 page 2개, lineage 1개,
  `pagination_state=COMPLETE`, `provider_history_state=NOT_EVALUATED`를 반환했다.
- 재현 단계: recorded fixture를 `adapt_outcome_history_t15`에 전달하고 결과 lineage를
  기존 `propose_outcome_matches`와 append-only correction projector에 전달한다.
- Sanitized evidence: `portfolio-outcome-history-t15.recorded.json`과
  `portfolio-outcome-history-t15.redacted-import.json`; raw account와 credential 없음.
- Regression test: `tests/test_portfolio_outcome_history_t15.py`의 complete cursor,
  discontinuity, duplicate fill, bounded import, mapping bypass 거부, correction replay 6 cases.
- Fix commit: `01d0830`이 redacted import의 bounded parser 우회를 차단했다.
- 남은 NOT_EVALUATED: 실제 provider read-only scope, history retention, pagination cursor,
  provider fill identity와 outage behavior.

## T16

T16: `IMPLEMENTED_AND_USABLE`

- Build/commit: `aba5637` (`feat(mandate): 일회용 영속성 리허설을 추가한다`)
- Data mode: `SYNTHETIC · DISPOSABLE_LOOPBACK · DEFAULT_OFF`
- 기대 결과: 빈 PostgreSQL 17.11에 기존 A1 migration만 적용하고 seed→activation
  write→typed project→append-only correction→rebuild→rollback을 수행해야 한다. RLS와
  grant, idempotency도 각각 검증해야 한다.
- 실제 결과: 최초 실제 rebuild에서 PostgreSQL 17의 `min(uuid)` 미지원 오류를 찾았다.
  UUID를 정렬한 `array_agg` 첫 원소로 교체했다. 후속 검토에서는 caller가 선언한 target과
  실제 operation connection이 달라질 수 있는 결함을 찾아 각 executor call의 동일
  session에 identity guard를 넣었다. targeted 70 tests와 A1 PostgreSQL 전체 23 tests가
  새 cluster에서 통과했고 종료 후 cluster를 중지하고 삭제했다.
- 재현 단계: exact loopback/data-dir/server-version/blank-state opt-in을 만족하는 새
  cluster에서 `tests/test_portfolio_mandate_postgres_contracts.py` 전체를 실행한다.
- Sanitized evidence: 합성 UUID와 hash만 사용한 pytest 결과 `23 passed`; migration
  late-failure rollback sentinel과 correction rollback 후 잔존 row 0.
- Regression test: `test_t16_writer_projects_and_rebuilds_with_rollback`,
  `test_t16_writer_is_default_off_and_does_not_call_executor`,
  `test_t16_rechecks_disposable_identity_in_every_operation_session`.
- Fix commit: `aba5637`에 PostgreSQL 17-compatible UUID aggregation과 regression을
  포함했고, `01d0830`이 typed result와 operation-session identity 경계를 보강했다.
- 남은 NOT_EVALUATED: 기존·live DB migration apply, backfill, writer activation,
  production projection rebuild와 운영 load/concurrency.

## Promotion boundary

- 외부 호출: 0건
- 주문: 0건
- Toss/provider write, notification, schedule/heartbeat 변경, live DB write: 모두 0건
- 실제 holding intent 또는 horizon 추론: 0건
- Phase 6 PASS 주장: 없음

기존·live DB 적용, actual provider 연결, writer activation과 production promotion은
`REQUIRES_SEPARATE_APPROVAL`이다. 이 checkpoint는 T13–T17의 local usable completion과
분리한다.
