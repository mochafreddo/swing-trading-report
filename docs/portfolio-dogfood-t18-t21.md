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

T21: `LOCAL_PROBE_IMPLEMENTED · ONE_SHOT_ORDER_AGGREGATE_OBSERVED`

실사용 체결내역 대상은 토스증권이다. KIS 시세 사용은 KIS 증권계좌 사용을 뜻하지 않는다.
기존 KIS recorded package는 과거 회귀검사로 보존하며 토스 지원이나 실제 계좌 검증의 증거로
사용하지 않는다. KIS one-shot 승인은 실행되지 않았고 토스 호출에 적용되지 않는다.
아래 14개 scenario 결과는 기존 KIS 합성 검증 기록이다.

- Data mode: `RECORDED_REDACTED · PROVIDER_FREE`이며 `provider_history_state=NOT_EVALUATED`다.
- 기대 결과: provider endpoint, method, credential boundary, request/page/byte/time budget, 저장 metadata,
  금지 metadata와 주문 금지를 exact contract로 고정하고 success와 모든 실패 분기를 재생한다.
- 실제 결과: 14개 scenario에서 success 1개와 incomplete pagination, duplicate fill, cursor loop,
  timeout, 401, 403, 429, 5xx, malformed payload, request/page/byte/time budget 실패 13개를
  재생했다. provider call과 order operation은 0이다.
- 저장 가능 metadata: scenario/result code, request/page/byte/time count, capability state와
  redacted fill identity hash만 허용한다. account ID/number, token, 수량, 가격, 손익, raw payload는
  contract와 recursive validator에서 금지한다.
- 과거 회귀검사 재현: `UV_CACHE_DIR=.uv-cache uv run python scripts/run_portfolio_outcome_capability_t21.py --recorded-replay`.
- Regression test: exact read endpoint/method, frozen budgets, privacy rejection, permanent order-operation
  prohibition, recorded result code를 `tests/test_portfolio_outcome_capability_t21.py`가 고정한다.
- 남은 `NOT_EVALUATED`: 토스 체결내역 접근 수단, 인증 권한, history retention, real pagination cursor, partial fill,
  correction/cancel, fill identity와 outage behavior.

### 토스 기준 수정 계획

저장소 `web/src/lib/toss/client.ts`는 `/oauth2/token`과 `/api/v1/holdings`를 호출하는
보유목록 adapter만 구현한다. 이는 코드에 기재된 경로일 뿐 현재 provider의 공식 지원이나
사용자 계정 접근 자격을 검증한 결과가 아니다. 체결내역 endpoint, pagination, fill identity
mapping은 구현되어 있지 않다. 보유 수량이나 평균매입가 변화로 체결·정정·취소를 추정하지 않는다.
기존 holdings sync는 별도 저장 경로를 가지므로 zero-write probe로 실행하지 않는다.

2026-09-05 공개 문서 확인: [공식 가이드](https://developers.tossinvest.com/llms.txt)가 안내하는
[OpenAPI 명세](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json) version `1.2.14`,
응답 SHA-256 `a7b32ba754401d13fa649ba91eebd212420eb1afab28e9c2c0d6ea8d43055fed`를 인증 없이 확인했다.
`GET /api/v1/orders`와 `GET /api/v1/orders/{orderId}`는 문서상 주문 이력 조회 경로다.
`CLOSED`는 limit/cursor 페이지 처리와 KST 주문 생성일 기준 from/to를 지원하지만 `OPEN`은
limit/cursor를 무시한다. 응답의 `OrderExecution`은 누적 체결량·평균가·최종 체결 시각이며,
확인한 `Order`/`OrderExecution` schema에는 개별 fill ID나 이전/다음 정정 주문 연결 필드가 없다.
`GET /api/v1/trades`는 Market Data로 분류되어 개인 계좌 체결 이력으로 사용하지 않는다.
OAuth 명세의 scopes는 빈 객체이므로 read-only token 권한을 확인했다고 주장하지 않는다.
실사용 계정 접근 자격, 수동 주문 포함 범위와 보존 기간도 아직 검증하지 않았다.

개별 체결·정정 lineage 증거 부족은 T15 정밀 분석 연결만 제한한다. API로 주문별 체결 결과를
조회·검증하는 단계의 차단 사유가 아니다. 주문 ID를 fill ID로 복제하거나 누적량 차이로
synthetic fill을 만들지 않고도 주문별 결과를 검증할 수 있다. 문서상 GET 후보와 실제 허용된
요청은 분리하며 기본 실행의 live allowlist는 계속 비어 있다.

추가 확인: [공식 AsyncAPI 명세](https://openapi.tossinvest.com/openapi-docs/latest/asyncapi.json)
version `1.2.2`, SHA-256 `130251057fd9535a3e276099f9166b445f8c51f505f30540758e4b209231282e`의
`personal:order`는 국내·미국 주식의 주문 스냅샷을 전달한다. `execution.filledAt`은 없고
개별 체결 식별자·정정 연결 필드도 확인되지 않았다. 문서의 무손실 보장은 연결 세션 내부에
한정되며 끊긴 구간은 재전송하지 않는다. REST 재조회로 주문 상태를 맞추더라도 개별 fill
lineage가 복원되는 것은 아니다. 웹소켓 연결이나 수집 daemon을 해결책으로 추가하지 않는다.

이전 파일 import 제안은 실사용 흐름과 맞지 않아 철회했다. 거래내역 파일이나 열 이름은
필수 입력이 아니며 API가 기본 경로다. 추가 공개 문서 확인은 credential 사용, 인증·계좌 API
요청 또는 웹소켓 연결을 포함하지 않았다.

1. 토스 전용 승인 후 종료 주문 목록의 접근·응답 형식·페이지 완결성을 one-shot 검증한다. 조회 성공과 계정의 전체 수동 주문 포함 보장은 구분한다.
2. 주문별 누적 체결 결과는 그대로 검증하고, 부분체결·취소·정정은 관측된 주문 상태로만 요약한다. 개별 fill이나 정정 연결은 생성하지 않는다.
3. T15 공통 계약은 유지하되 probe 응답을 억지로 매핑하지 않는다. 향후 정밀 분석은 개별 fill lineage 증거가 확보된 뒤 연결한다. 과거 보존 기간이나 앱 수동 주문 포함 범위는 단일 제한 조회만으로 확정하지 않는다.

### 토스 one-shot 실행 계약

- 입력: process 환경의 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT`와 명시적 from/to 날짜. `ACCOUNT`는 계좌번호가 아닌 기존 `accountSeq`여야 한다. 파일 자동 로드·계좌 목록 탐색·계좌 자동 선택은 하지 않는다. 값은 채팅·명령 인자에 넣지 않는다.
- 요청: 고정 호스트 `openapi.tossinvest.com`의 `POST /oauth2/token` 1회와 `GET /api/v1/orders`만 사용한다. `status=CLOSED`, `limit=20`, `from`/`to`는 KST 주문 생성일 기준 양 끝 포함, 최대 30일이다. 커서는 직전 응답에서만 이어받아 URL 인코딩한다.
- 상한: 최대 5 requests(토큰 포함), 4 history pages, 총 1,048,576 bytes의 소비한 응답 본문, 시작 후 30초. 응답 본문을 상한보다 더 읽지 않으며 Unix main-thread alarm으로 DNS·TLS·read 대기를 포함한 시간을 제한한다. 이 바이트 한도는 HTTP 헤더나 OS 네트워크 버퍼의 wire-byte 제한이 아니다.
- 범위 제외: 주문 상세, OPEN 조회, accounts/holdings 조회, 웹소켓, 시세 호출, 주문 생성·정정·취소, 재시도, 리디렉션, proxy, token cache, DB, scheduler, notification. 토큰 재발급도 재시도하지 않는다.
- 저장: raw payload와 계좌·토큰·주문 ID·종목·수량·가격·손익은 출력/저장하지 않는다. 요청·페이지·응답 본문 byte·경과 시간, 고정 result code와 capability state만 stdout으로 출력한다. CLI는 core dump를 금지하고 사용 credential을 자식 프로세스용 환경에서 제거한다. 비밀값의 Python 메모리 완전 소거를 보장하는 것은 아니다.
- 성공: 완전한 페이지 체인과 유효한 주문별 결과는 `COMPLETE_ORDER_AGGREGATE`다. 빈 결과는 `COMPLETE_NO_ORDERS`로 구분한다. 둘 다 개별 fill lineage·보존 기간·수동 주문 포함 범위·read-only OAuth scope의 검증 완료를 뜻하지 않는다.
- 중단: 401/403/429/5xx, redirect, timeout, malformed/중복 JSON, 알 수 없는 주문 상태, 중복 주문, cursor loop, 상한 도달 시 종료한다. 4페이지 뒤 continuation이 남으면 `INCOMPLETE_PAGE_BUDGET`이지 성공이 아니다. 실패 시 private exception text를 출력하지 않는다.

실행은 별도 승인 후에만 `scripts/run_portfolio_outcome_capability_t21.py --toss-probe-approved --from-date YYYY-MM-DD --to-date YYYY-MM-DD`로 가능하다. 승인 플래그는 사용자 승인의 대체물이 아니며 이전 KIS 승인을 적용해서는 안 된다. 아래 토스 실제 실행 1회는 별도 승인을 받아 수행했으며 승인 재사용은 허용하지 않는다.

기본 CLI는 `UV_CACHE_DIR=.uv-cache uv run python scripts/run_portfolio_outcome_capability_t21.py`다.
토스 대상, `NOT_EVALUATED`, probe 승인 범위와 별도 T15 제한을 stdout으로만 출력한다. credential을
읽거나 fixture/artifact를 열지 않으며 허용된 live request 목록은 비어 있다. 종료 코드 0은
readiness 출력 성공일 뿐 provider 검증 성공이 아니다. T18/T19/T20, 기존 KIS 시세 경로,
T15 계약, 스케줄과 운영 writer는 이 변경 범위에 포함하지 않는다.

수정 검증: T21/T15/Outcome targeted pytest 70개 통과, 변경 Python 파일 Ruff와 mypy 통과,
기본 CLI dogfood 및 `git diff --check` 통과. 새 토스 probe 테스트는 합성 응답과 fake HTTPS
connection으로만 실행했으며 개별 fill ID 없는 성공, 빈 결과, 페이지·byte 한도, timeout,
HTTP 실패, 민감값 비출력, 승인 없을 때 요청 0건을 검증했다. 기본 실행은 존재하지 않는
fixture 경로를 주어도 readiness만 출력하고 artifact를 만들지 않는다. 명시적 replay는 14개
과거 scenario를 재생하며 출력과 artifact 모두 `HISTORICAL_KIS_RECORDED_ONLY_NOT_TOSS`로
표시된다. 전체 `just quality`는 Ruff/format/mypy와 pytest 3,591 passed, 25 skipped로
통과했다. Web 코드는 변경하지 않아 `just ci-web`과 Docker 재빌드는 실행하지 않았다.
위 로컬 구현 검증 시점에는 공개 문서 검색/GET만 수행했고 실제 인증 교환, 계좌 조회,
주문 호출, credential 사용과 민감 데이터 저장은 모두 0건이었다. 이후 승인된 실제 검증은
다음 기록으로 구분한다.

### 승인된 토스 one-shot 실행 결과

기록 시각: `2026-09-05T04:38:03Z` (실행 완료 후 기록 시각이며 요청 시작 시각은 아니다).
사용자는 process-memory credential/accountSeq로 `2026-08-07`부터 `2026-09-05`까지 KST
종료 주문을 최대 5요청·4페이지·응답 본문 1 MiB·30초 안에서 1회 검증하도록 승인했다.
설정 파일을 실행하지 않고 승인된 세 입력만 메모리로 전달해 기존 probe 함수를 호출했다.
core dump를 금지했고 raw 응답·credential·accountSeq·종목·주문 ID·수량·가격·손익을
로그나 파일로 남기지 않았다. 이 기록은 실행기가 출력한 고정 결과 코드와 집계 metadata만 보존한다.

| 항목 | 실제 결과 |
|---|---|
| result_code | `COMPLETE_ORDER_AGGREGATE` |
| provider_history_state | `ORDER_AGGREGATE_OBSERVED` |
| request_count | 2 (토큰 POST 1회, CLOSED 주문 GET 1회) |
| page_count | 1 (후속 cursor 없음) |
| response_byte_count | 1,456 (토큰 응답 포함 소비한 본문) |
| elapsed_ms | 460 (probe 함수의 측정값) |
| partial_fill_state | `NOT_OBSERVED` |
| correction_cancel_state | `NOT_OBSERVED` |
| order_operations / 재시도 | 0 / 0 |

한도 내 조회·페이지 완결·주문별 누적 체결 결과의 형식 검증은 실제로 통과했다. 전체 계좌
이력을 감사한 것은 아니며 `individual_fill_lineage`, `manual_order_coverage`,
`retention_window`, `oauth_read_only_scope`는 계속 `NOT_EVALUATED`다. 부분체결·정정·취소가
이 조회에서 관측되지 않았다는 결과도 해당 기능의 미지원이나 계좌 전체의 부재를 뜻하지 않는다.
추가 조회·재실행·기간 확대·정기 수집·Outcome 연결·production 활성화는 수행하지 않았다.
기본 CLI는 실행 이력을 저장하거나 이 승인을 재사용하지 않고 여전히 승인 전 readiness를 출력한다.
이번 실행 후 변경은 이 sanitized 기록뿐이며 `git diff --check`로 확인했다. 코드 변경이 없어
전체 품질 검사를 재실행하지 않았고 실제 provider 검증을 반복하지 않았다.

## Exact promotion boundaries

다음은 이 checkpoint에 포함되지 않았고 각각 별도 명시 승인이 필요하다.

- T19 production advice 연결: historical replay 의미 검토와 서명 기록 승인은 완료됐다.
  운영 판단 연결과 활성화는 별도 승인 대상이다.
- T20 live rehearsal: 대상 DB identity, migration window, backup/restore owner, RTO/RPO acceptance와
  rollback authority를 특정한 별도 승인. 현재 실행기는 live target을 받을 수 없다.
- T21 live one-shot probe: 위 계약으로 승인된 1회 실행은 완료됐다. 추가 실행은 새 승인이 필요하다.
  KIS 승인은 이전하지 않는다. 주문 생성·정정·취소는 영구 금지하며 raw response와 민감값은 저장하지 않는다.
- production promotion: writer activation, scheduler/notification/owner 변경, provider 연결,
  기존·live DB write, 배포 또는 실제 advice 연결은 각각 별도 승인.

## External side effects

- 기존 local-only checkpoint의 provider call은 0건이었다. 이후 승인된 토스 one-shot의 provider call은 총 2건(토큰 POST 1회, 종료 주문 GET 1회)이다.
- 실제 주문, live/existing DB write, notification, schedule/heartbeat, owner 변경: 각각 0건.
- local disposable PostgreSQL write와 local Docker rebuild는 production side effect가 아니다.
- 실제 holding intent/horizon 추론과 Phase 6 PASS 주장: 0건.
