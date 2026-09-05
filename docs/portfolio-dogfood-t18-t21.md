# Portfolio Mandate T18–T21 local evidence

상태: Accepted (local packages implemented and usable; production promotion remains blocked)

이 문서는 T18–T21의 provider-free local vertical journey에서 기대 결과, 실제 결과,
재현 단계, 회귀 검사를 함께 기록한다. private 원문·실제 종목·account·credential·수량·가격·손익은
문서, fixture, 로그, screenshot에 기록하지 않는다.

## T18

T18: `IMPLEMENTED_AND_USABLE`

- Data mode: `PRIVATE_ZERO_WRITE · BROWSER_MEMORY_ONLY`.
- 기대 결과: 기존 private v1 파일 1개를 `/today`에서 명시적으로 선택하면 8개 holding의
  role, thesis, composite invalidation, concentration, frozen addition, evidence reference를
  표시한다. 파일은 업로드·저장·변환하지 않고 clear, refresh, navigation 뒤 브라우저 메모리에서
  사라져야 한다.
- 실제 결과: strict duplicate-key parser와 v1 Zod schema를 기존 A2 local preview 경계에
  추가했다. 정확히 8개 holding, `5 CORE / 3 SATELLITE`, `APPROVED · ACTIVE · LONG_TERM`,
  composite rule, concentration range, valuation queue identity와 자동 주문 금지를 검증한다.
  실제 private 값은 committed fixture나 test assertion에 복사하지 않았다.
- 최초 dogfood 결함: 합성 fixture가 `condition_match`를 항상 명시하고 주문 금지 토큰을 세 값으로
  고정해, 원본 v1 JSON Schema가 허용하는 `condition_match` 생략(`ALL` 기본값)과 일반화된 고유
  `prohibited_operations` 목록을 실제 브라우저 parser가 거부했다. 생략형 합성 fixture와 반대의
  invalid 조합·중복 금지 목록 회귀검사를 추가하고, UI에는 생략 기본값을 `ALL`로 표시하도록
  수정했다.
- Sanitized evidence: 합성 8종목 fixture는 독립 Python invariant test와 Web Zod parser/E2E를
  함께 통과했다. 실제 private input도 값별 private JSON Schema와 Web Zod parser를 통과했다.
  fixture credential과 메모리 전용 login throttle을 쓰는 격리 Docker에서 실제 파일을 열어
  375/768/1280px 모두 8개 card, `5 CORE / 3 SATELLITE`, private badge 8개, evidence link 14개,
  board action 0을 확인했다. preview 내부 button/form/order action, horizontal overflow, 외부
  request, `localStorage`, `sessionStorage`, IndexedDB, console/browser error는 모두 0이었다.
- Regression test: 같은 파일 재선택, clear, 늦게 끝난 이전 read 무시, invalid JSON 원자적 제거,
  1 MiB 초과 거부, `fetch`/Web Storage/IndexedDB 미사용을 고정한다.
- Actual browser journey: file input focus와 `Tab → Enter` Clear, 같은 파일 재선택, refresh,
  `/reports → /today` navigation을 실행했다. Clear 뒤 file/derived state가 제거됐고 refresh와
  navigation 뒤 자동 복원은 0이었다. private 값 보호를 위해 screenshot은 만들지 않았다.

## T19

T19: `APPROVED_REPLAY_ONLY_NO_PRODUCTION_ADVICE`

- Data mode: `PUBLIC_PRIMARY_SOURCE · FROZEN_REPLAY · PROVIDER_FREE`.
- 기대 결과: SEC 원문 12건과 fake clock 주기 4개를 exact CIK/accession URL, publication timestamp,
  reporting period, supporting span hash, parser version으로 고정하고 모든 case를 한 번씩 replay한다.
- 실제 결과: 12건에는 actual invalidation, counterexample, stale, conflicting, insufficient,
  unchanged thesis가 포함된다. 결과는 `REVIEW_REQUIRED`, `THESIS_UNCHANGED`, `BLOCK_STALE`,
  `BLOCK_CONFLICT`, `BLOCK_INSUFFICIENT`, `PREDICATE_CANDIDATE`만 허용한다. 충족 case도 SELL이
  아니라 review이며 AI authority는 candidate만 생성한다.
- 최초 dogfood 결함: `scripts/` 직접 실행 시 repository root가 import path에 없어 `sab` import가
  실패했다. 기존 저장소 실행기 패턴과 같이 root를 명시해 동일 명령이 통과하도록 수정했다.
- 완료 감사 결함: duplicate cadence ID guard의 집합 변수를 같은 루프의 case-ID 배열이 덮어썼다.
  두 이름을 분리하고 future `generated_at`과 duplicate cadence identity negative test로 고정했다.
- Sanitized review summary: case 12, cadence 4, review-required 3, thesis-unchanged 3,
  stale block 2, conflict block 2, insufficient block 1, predicate candidate 1.
- User approval: 2026-09-05에 사용자가 12건의 case, source/span 및 expected action set에 대한
  의미 검토 완료와 서명 기록을 명시적으로 승인했다. 승인 문구와 기록 시각
  `2026-09-05T03:46:19Z`를 manifest의 `approval_signature`에 보존했다.
  `USER_ATTESTATION_SHA256`은 서명 해시 슬롯만 비운 전체 manifest와 승인 기록을 묶는
  변경 감지 해시이며 개인키 전자서명이나 독립적인 사용자 신원 인증 수단이 아니다.
  `production_advice_authorized=false`이며 기존 12건의 내용과 action label은 변경하지 않았다.
- Public source audit: 8개 고유 SEC filing URL의 issuer/accession identity와 12개 supporting span의
  현재 원문 근거를 대조했다. 표 행은 parser의 ` | ` cell separator로 정규화했다. Source/span
  일치를 확인했고, 이후 action 의미 승인은 위 사용자 승인 기록으로 남겼다.
- 재현: `UV_CACHE_DIR=.uv-cache uv run python scripts/replay_portfolio_long_term_t19.py`.
- Regression test: exact source identity, span hash, action precedence, AI 비권한, cadence coverage,
  미승인 null 서명, 승인 상태/해시 일치, 승인 후 내용 변경 거부와 운영 조언 금지를
  `tests/test_portfolio_long_term_replay_t19.py`가 고정한다.
- 남은 `NOT_EVALUATED`: production advice 연결.

`published_at`은 SEC filing date가 day precision인 case에서 UTC 자정으로 정규화된 고정값이다.
SEC accepted timestamp라고 주장하지 않는다. 현재 승인은 historical replay 검토에 한정되며
이 manifest를 운영 판단에 연결하는 권한을 부여하지 않는다.

## T20

T20: `IMPLEMENTED_AND_USABLE`

- Data mode: `DISPOSABLE_LOOPBACK · POSTGRESQL_17_11 · DEFAULT_OFF`.
- 기대 결과: 한 명령이 새 빈 DB를 만들고 기존 A1 migration만 재사용하여 migration/RLS/grant/
  concurrency/late-failure rollback 계약을 실행한 뒤 backup→restore checksum과 RTO/RPO를 확인하고
  클러스터와 임시 디렉터리를 정리한다.
- 실제 결과: schema version `portfolio-mandate.a1`, journal RPO 0, restore RTO 0.072초,
  cluster stopped와 temporary directory removed가 모두 true였다. 기존·live DB write는 0이다.
- 최초 dogfood 결함: 샌드박스 루프백 bind가 `EPERM`으로 막혔다. 동일한 폐기형 명령을 승인된
  샌드박스 외 실행으로 재현했다.
- 두 번째 dogfood 결함: PostgreSQL 17 `pg_dump`의 매 실행 restriction nonce와 설명 주석이 같은
  DDL의 checksum을 달리 만들었다. DDL과 `COMMENT ON`은 보존하면서 비의미 dump framing만
  정규화했다.
- 재현: `UV_CACHE_DIR=.uv-cache uv run python scripts/portfolio_mandate_t20_rehearsal.py`.
- Local evidence: `tmp/portfolio-mandate-t20-evidence.local.json`은 gitignored이며 target identity,
  app revision, migration hash, schema/journal/projection checksum, RTO/RPO와 cleanup 결과만 담는다.
- Regression test: source/restore operation identity와 PostgreSQL 17.11, inherited PG route 제거,
  rehearsal role 선점 충돌, dump normalization, 단일 기존 A1 migration 재사용, evidence fail-closed 필드를
  `tests/test_portfolio_mandate_promotion_t20.py`가 고정한다.
- 남은 `NOT_EVALUATED`: 기존·live DB migration, backfill, production rollback, 실제 운영 부하.

## T21

T21: `IMPLEMENTED_AND_USABLE_WITH_RECORDED_REDACTED_FIXTURES`

- Data mode: `RECORDED_REDACTED · PROVIDER_FREE`이며 `provider_history_state=NOT_EVALUATED`다.
- 기대 결과: provider endpoint, method, credential boundary, request/page/byte/time budget, 저장 metadata,
  금지 metadata와 주문 금지를 exact contract로 고정하고 success와 모든 실패 분기를 재생한다.
- 실제 결과: 14개 scenario에서 success 1개와 incomplete pagination, duplicate fill, cursor loop,
  timeout, 401, 403, 429, 5xx, malformed payload, request/page/byte/time budget 실패 13개를
  재생했다. provider call과 order operation은 0이다.
- 저장 가능 metadata: scenario/result code, request/page/byte/time count, capability state와
  redacted fill identity hash만 허용한다. account ID/number, token, 수량, 가격, 손익, raw payload는
  contract와 recursive validator에서 금지한다.
- 재현: `UV_CACHE_DIR=.uv-cache uv run python scripts/run_portfolio_outcome_capability_t21.py`.
- Regression test: exact read endpoint/method, frozen budgets, privacy rejection, permanent order-operation
  prohibition, recorded result code를 `tests/test_portfolio_outcome_capability_t21.py`가 고정한다.
- 남은 `NOT_EVALUATED`: KIS OAuth scope, history retention, real pagination cursor, partial fill,
  correction/cancel, fill identity와 outage behavior.

## Exact promotion boundaries

다음은 이 checkpoint에 포함되지 않았고 각각 별도 명시 승인이 필요하다.

- T19 production advice 연결: historical replay 의미 검토와 서명 기록 승인은 완료됐다.
  운영 판단 연결과 활성화는 별도 승인 대상이다.
- T20 live rehearsal: 대상 DB identity, migration window, backup/restore owner, RTO/RPO acceptance와
  rollback authority를 특정한 별도 승인. 현재 실행기는 live target을 받을 수 없다.
- T21 live one-shot probe: KIS app key/secret과 account routing을 process memory에서만 사용해
  `POST /oauth2/tokenP` 1회와 국내·해외 체결내역 `GET`만 총 8 request, 4 page, 1 MiB, 30초 내에서
  수행하는 승인. 주문 생성·정정·취소 endpoint는 영구 금지하며 raw response와 민감값은 저장하지 않는다.
- production promotion: writer activation, scheduler/notification/owner 변경, provider 연결,
  기존·live DB write, 배포 또는 실제 advice 연결은 각각 별도 승인.

## External side effects

- 실제 주문, provider call, live/existing DB write, notification, schedule/heartbeat, owner 변경: 각각 0건.
- local disposable PostgreSQL write와 local Docker rebuild는 production side effect가 아니다.
- 실제 holding intent/horizon 추론과 Phase 6 PASS 주장: 0건.
