# Portfolio Mandate A1 비활성 계약

상태: Accepted (disposable PostgreSQL verified, not deployed)

이 문서는 RN1 dossier를 구현 계약으로 채택한 A1의 범위를 기록한다. Migration
파일과 Python/Web contract validator를 작성하고 전용 loopback disposable
PostgreSQL 17에서 migration과 transaction/concurrency 계약을 검증했다. 기존 로컬
DB, production DB, 외부 Supabase에는 연결하거나 적용하지 않았으며 A1은 여전히
runtime과 deploy 경로에 연결하지 않은 비활성 설계면이다.

## Public seam

향후 persistence adapter는 하나의 `PortfolioMandateStore` module로 다음 command
seam만 노출한다.

- `rebase_position_slices(command) -> RebaseResult`
- `activate_mandate_version(command) -> ActivationResult`
- `seal_evidence_identity(command) -> EvidenceSealResult`
- `record_predicate_authority(command) -> PredicateAuthorityResult`

Caller는 row 쓰기 순서, quarantine 생성, journal append 또는 projection
invalidation을 따로 조립하지 않는다. 각 command는 성공 결과나 typed rejection
하나만 반환하며 PostgreSQL transaction 실패는 부분 write 없이 rollback한다.

## Additive schema

`supabase/migrations/20260828230000_create_portfolio_mandate_a1.sql`은 기존
table과 writer를 수정하지 않는 create-only 초안이다.

- Issuer, Instrument, ListingAlias는 UUID stable identity와 event-time validity를
  사용한다. Ticker는 표시·검색 alias이며 aggregate/evidence FK가 아니다.
- Mandate는 UUID owner actor를 저장하고 immutable version은 허용된
  classification/horizon/approval 조합과 aggregate별 one-active constraint를
  사용한다.
- BrokerPositionSnapshot, allocation, PositionSlice는 exact snapshot/allocation
  version을 참조한다. Slice quantity는 음수가 아니며 quarantine을 포함한 합계가
  broker quantity와 일치해야 한다. 모든 decimal은 유한값만 허용하고 `NaN`과
  양·음의 무한대를 거부한다. Rebase command의 fill/corporate-action 분기는
  caller 문자열이 아니라 exact snapshot, source, hash, verification state를 봉인한
  append-only rebase evidence를 참조한다.
- Journal, lineage, activation, rebase, predicate authority event는 append-only다.
  Correction은 기존 event 수정이 아니라 `supersedes_event_id`를 가진 새 event다.
- Mandate version lineage FK는 `(mandate_id, mandate_version_id)`를 함께 묶는다.
  Activation draft의 `supersedes_version_id`는 transaction 안에서 현재 expected
  version과 정확히 일치해야 한다.
- 모든 A1 table은 RLS를 enable/force하고 `public`, `anon`, `authenticated` 권한을
  회수한다. `service_role`의 ambient 권한도 모든 table에서 먼저 명시적으로
  회수한 뒤 SELECT와 non-user command RPC만 부여하며 직접 DML은 부여하지 않는다.
  User activation과 user predicate confirmation RPC는 `authenticated`만 실행하고
  `auth.uid()`를 저장 actor와 Mandate owner에 결속한다. Command는 fixed
  `search_path`의 security-definer boundary 안에서 실행한다.
- Research adapter용 NOLOGIN role은 fixed-field
  `submit_predicate_candidate_a1`만 실행할 수 있다. Aggregate command RPC와 table
  DML 권한은 없으며 candidate는 항상 `AI/RESEARCH_ADAPTER/REVIEW_ONLY`로 저장한다.

## PostgreSQL 검증

`tests/test_portfolio_mandate_postgres_contracts.py`는 명시적 opt-in과 exact
`127.0.0.1` host, explicit port, `portfolio_mandate_a1_test_` database prefix,
expected data directory를 모두 요구한다. DSN query/fragment와 상속된 `PG*`
connection override를 거부하고, destructive fixture setup 전에 실제 server
address/port/database/data directory/session user/server version `170011`, 전용
임시 data-directory 형태, 빈 database, candidate role 사전 부재를 read-only로
대조한다. 기존 candidate role은 삭제하지 않고 실패한다. Password는 생성 시점부터
mode `0600`인 임시
`PGPASSFILE`에만 기록하고 psql argv와 canonical DSN에서는 제거한다. Migration
file은 `--single-transaction`으로 적용하며 끝부분이 실패하는
복제본으로 schema와 candidate role이 함께 rollback되는지 먼저 확인한다. 새로 만든
전용 PostgreSQL 17.11 cluster에서 다음 계약을 검증했다.

- migration 전체 parser/DDL 적용, 모든 A1 table의 실제 RLS `ENABLE/FORCE` flag,
  blank database의 schema/table/function grant, candidate role의 신규 생성 전용
  fail-closed 경계와 안전 attributes/상위 role membership 부재
- ambiguous sell quarantine, mid-transaction constraint failure의 전체 rollback,
  concurrent rebase one-target commit
- activation의 version/slice/journal/projection atomic commit, concurrent one-winner,
  full-payload idempotency, `authenticated`/`auth.uid()` actor 및 Mandate owner
  재검증과 service-role 실행 거부
- 두 session barrier를 통과한 concurrent rebase/activation과 동일 source의
  instrument-scope evidence seal one-winner
- approved metric/operator/threshold/unit/period와 observed value를 실제 비교하는
  structured predicate fulfillment, false predicate와 free-text fail-closed,
  authenticated user confirmation actor binding, append-only trigger
- JSON/Python/Web decimal contract와 같은 유한 quantity/metric 6자리 및
  corporate-action ratio 8자리 소수 정밀도 제한과 특수 numeric 거부
- candidate role의 `REVIEW_ONLY` submit-only 권한과 authority/table 접근 거부

Blank database에서 필요한 `public` schema `USAGE`는 `service_role`,
`authenticated`, candidate role에 각 RPC 범위만큼 부여한다. 임시 cluster 밖의
DB에는 migration을 적용하지 않았다.

## Authority와 privacy

- Mandate activation은 caller label이 아니라 authenticated JWT role과 `auth.uid()`로
  확인한 user actor만 수행한다.
- Slice rebase는 deterministic actor만 수행한다.
- Deterministic parser의 구조화된 source span/parser/schema가 모두 존재하고,
  observed metric/unit/period가 승인 definition과 일치하며 observed decimal value가
  승인 operator/threshold를 실제로 만족하거나 authenticated user가 전체 audit
  field로 확인한 경우에만 predicate가 `SELL_ELIGIBLE`이 된다.
- AI는 `PREDICATE_CANDIDATE`만 제출하며 효과는 `REVIEW_ONLY`다. Source
  validator는 provenance만 확정한다. Free-text rationale는 authority event를
  만들지 않으며, deterministic parser가 비정형 surface를 fulfillment로 제출하면
  typed review-required rejection으로 종료한다.
- Predicate authority event는 user가 승인한 exact mandate version의 typed predicate
  definition(metric/operator/threshold/unit/period)을 FK로 참조한다. 방향성
  eligibility에는 exact predicate schema version도 일치해야 한다. Source는 mandate
  instrument와 일치하는 evidence seal로 결속하며 correction은 동일 mandate
  version/predicate의 이전 `PREDICATE_FULFILLED` event만 supersede한다.
- Full fixture validator는 persistence invariant 검사용이며 Web report/public research
  projection이 아니다. `portfolioMandatePublicEvidenceA1Schema`가 별도 public
  projection 경계다. Account ID/hash, quantity, cost, P/L, notes, tags는 이 public
  evidence surface에 포함하지 않는다. Broker persistence position에만 keyed hash
  reference를 둔다.

## 비활성 범위

A1은 LONG_TERM runtime, writer, board, alert, Outcome, provider 호출, 주문, Toss
write, notification, automation, deploy, cutover를 활성화하지 않는다. 기존 US
SWING Decision Board와 hard SELL precedence, advice-only/no-order 경계, 기존
production writer ownership을 그대로 유지한다.
