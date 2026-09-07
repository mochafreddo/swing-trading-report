# Portfolio Mandate 계획 대조 및 재개 조건

상태: `LOCAL_ONLY` 구현·검증 완료, 운영 전환 미완료. 기준일: 2026-09-07.

2026-08-06 design 및 engineering test plan을 코드, 작업 트리, T17/T18–T21 기록과 현재 승인 증거에 대조했다. T1–T21을 다시 구현하지 않았다. 기존 주문 화면 WIP를 검토하고 아래 결함 수정과 A1 검토 projection을 추가했다. 과거 실사용 기록은 이번 합성 검증과 구분한다. 각 파일의 최종 변경은 Git 이력으로 확인한다.

## 현재 완료 범위와 사용

| 흐름 | 이번에 확인하거나 수정한 결과 | 사용 및 직접 근거 |
| --- | --- | --- |
| 주문 결과 미리보기 | 완결된 페이지 체인만 원자적으로 표시한다. 날짜·시나리오 변경, Clear·refresh는 이전 결과를 제거한다. 누적 결과를 개별 fill로 바꾸지 않는다. | `/today`의 **토스 주문 이력 · 합성 미리보기**. `web/src/lib/toss/order-history.ts`, component/공통 decimal fixture/Python 교차 검사, fixture-only E2E |
| 일회성 별도 화면 | exact Host/Origin/session, 고정 POST, 호출 전 latch 소비, no-store, Clear/pagehide/15분 만료를 검증했다. 비공개 브라우저와 임시 서버는 운영 Next route와 별개다. | `scripts/run_toss_order_view_once.py --synthetic` 및 `web/e2e/toss-order-view.spec.ts`. 실제 실행 두 건은 T21 과거 승인 기록이며 재사용하지 않는다. |
| 주문 금액 경계 | 잘못된 non-null `orderAmount`가 수량 검사를 우회하는 결함과 Python 유니코드 숫자 허용을 수정했다. | `sab/portfolio_mandate/toss_order_probe.py`, 공유 14개 decimal 사례 |
| private 승인 표시 | 승인 문서의 `APPROVED · ACTIVE · LONG_TERM`을 보존하면서 운영 조언 미연결을 별도로 표시한다. 이전의 `PRIVATE DRAFT` 표기를 수정했다. | `unclassified-queue-preview.tsx`와 component/E2E. 실제 private v1은 읽기 전용 schema 검증, 현재 화면 재검증은 합성 값만 사용 |
| T13 정책 | DRAFT·다른 horizon, 미래 filing, 단위·기간·authority 불일치, 라벨과 실제 decimal 비교 불일치는 방향성 결과를 차단한다. | Python/Web compiler와 공유 7개 negative fixture. Decimal/BigInt로 LT/LTE/GT/GTE/EQ를 비교하며 AI/CANDIDATE는 REVIEW만 허용 |
| A1 검토 연결 | exact mandate version → active allocation/slice → visible evidence seal → correction을 반영한 authority event를 연결한다. 최신 draft가 기존 승인을 대체하지 않는다. | `scripts/replay_portfolio_mandate_review.py`, `review_projection.py`, 공유 출력 fixture, Today의 Mandate → Evidence → Outcome 안 **A1 version → slice → evidence review** |
| T20 복구 | 기존 dump의 `--no-privileges` 때문에 권한 손실이 검출되지 않던 결함을 재현했다. GRANT/REVOKE를 보존하고 table/function 유효 권한·owner·RLS·security-definer를 source/restore 간 비교한다. | 폐기형 PostgreSQL 17.11에서 수정 전 `restored checksum mismatch: security`, 수정 후 schema/journal/projection/security 일치. RTO 0.078초, journal RPO 0, 해당 cluster 종료 및 임시 디렉터리 제거 확인 |

A1 검토 projection은 전체 A1 validator를 재사용하며 실패 메시지에 입력값을 넣지 않는다. 승인·만료와 evidence seal/event 시각에는 주입된 clock을 적용한다. 원문 thesis, account hash, actor, 수량, source span은 출력하지 않는다. A1 watermark에는 freshness timestamp가 없으므로 모든 row가 `BROKER_FRESHNESS_UNPROVEN`, `PRODUCTION_ADVICE_NOT_CONNECTED`, `action=null`을 유지한다. **이 화면은 합성 snapshot의 검토용 연결이며 실제 DB read RPC나 private 8종목 policy 변환기가 아니다.**

안전한 CLI 재현은 저장소의 기존 Python 환경에서 다음과 같다. 첫 두 명령에는 provider/credential/DB 접근이 없다. 폐기형 복구 실행은 PostgreSQL 17.11의 설치된 도구가 PATH에 있어야 하며 기존 DB를 입력받지 않는다.

```sh
UV_CACHE_DIR=.uv-cache uv run python scripts/replay_portfolio_mandate_review.py
UV_CACHE_DIR=.uv-cache uv run python scripts/replay_portfolio_long_term_t19.py
UV_CACHE_DIR=.uv-cache uv run python scripts/portfolio_mandate_t20_rehearsal.py
```

## 남은 요구사항과 완료 조건

아래 분류에서 “별도 승인 필요”는 구현이 이미 전부 있다는 뜻이 아니다. 빠진 integration은 별도 열에 명시한다. 관련된 신규 migration 작성은 이번 요청의 승인 범위 밖이므로 SQL을 생성하지 않았다.

| 분류·항목 | 기대하는 사용자 결과와 현재 빠진 동작 | 관련 파일·최소 검증 | 완료 조건 |
| --- | --- | --- | --- |
| 완료 및 근거 확인: T1–T17 | 기존 US SWING, local LONG_TERM, Outcome seam, persistence prototype을 유지한다. 운영 완성과 동일시하지 않는다. | `docs/portfolio-dogfood-t17.md`, 기존 계약·runner·UI 및 이번 전체 gate | 기존 기능 회귀 없음, 신규 로컬 수정 검증 |
| 완료 및 근거 확인: T18–T21 | private preview, 승인된 12사례/4회 fake cadence replay, 폐기형 복구, 주문 누적 결과 관측을 구분한다. | `docs/portfolio-dogfood-t18-t21.md`, T19 signed manifest, T20 재실행 | 과거 기록 보존 및 새 검증 결과 별도 기록 |
| 사용자 입력 필요: 8종목과 5종목 gate | 실제 private 8종목 모두 승인된 LONG_TERM이다. 기존 계획의 실제 5종목 gate cohort 및 expected action에는 아직 연결되지 않았다. | private v1 원문/schema, T19 replay, `portfolio-mandate-a1-contract.md` | 기존 8개 승인 정보를 보존한 새 gate scope와 사전 expected action 승인. 기존 gate를 덮어쓰지 않음 |
| 사용자 입력 + 별도 승인 필요: 실제 policy 연결 | private composite invalidation의 결과는 `THESIS_INVALIDATED_REVIEW_REQUIRED`다. scalar A1/T13 SELL 조건으로 손실 없이 변환되지 않는다. 관측 metric/기간/기준값·복합 조건 provenance와 review-only 효과를 표현할 구현이 남았다. | `long_term.py`, `review_projection.py`, private schema, A1 contract. 복합 ALL/ANY·분기/결측/반례·수정 event의 shared fixture부터 검증 | review-only 의미와 gate cohort 확정 → 필요한 계약 및 migration 작성 승인 → 손실 없는 adapter/policy 구현. 실제 advice 활성화는 별도 |
| 별도 승인 필요: 실제 일관된 읽기 | Today가 실제 승인 version·slice·evidence·policy를 같은 snapshot으로 읽고 stale/mismatch를 차단해야 한다. 현재 A1에는 freshness가 봉인된 atomic read RPC가 없고 local projection만 있다. | `supabase/migrations/`, `sab/portfolio_mandate/`, Web server data boundary. 같은 transaction의 revision/digest/freshness·권한·race 검증 | 새 migration 작성 승인 후 RPC와 typed adapter 구현·폐기형 검증. production DB apply/credential/route 연결은 별도 |
| 별도 승인 필요: 전체 persistence/writer | A1은 create-only 핵심 계약이다. 전체 Source/EvidencePacket/DecisionRun/Decision/Outcome 및 publish/outbox 소유권 경로가 완성된 것으로 간주할 수 없다. backfill도 private composite를 축약할 수 없다. | A1 migration, `persistence_rehearsal.py`, `docs/portfolio-mandate-a1-contract.md`. idempotency·동시성·late failure rollback·journal replay | 필요한 schema/API diff 승인 및 구현 → disposable 검증 → 별도 실제 target/owner/window 승인 → backup/apply/backfill/writer 순차 실행 |
| 별도 승인 필요: 기존 DB 복구 | 폐기형 성공만으로 운영 row·role·용량·app 호환을 증명하지 못한다. 실제 backup 및 last-known-good read-only board rehearsal이 남았다. | `scripts/portfolio_mandate_t20_rehearsal.py`, 운영 manifest/runbook. schema/data/ACL/RLS checksum, RTO/RPO, row-count, restore 후 read-only health | 정확한 DB identity, backup 위치, owner, window, rollback 권한 확정. RTO ≤30분, journal RPO 0, broker RPO ≤1 run |
| 사용자 입력/실제 capability 필요: Outcome | 주문별 누적 체결 결과 표시는 된다. 개별 fill identity·correction lineage가 증명되지 않아 실제 T15 matching, 중복 fill 방지 및 90% coverage를 평가할 수 없다. | `outcome_history.py`, `toss_order_probe.py`, T15/O1 계약. 아래 capability 표 참조 | 증명된 단위만 사용. order ID→fill ID 복제와 누적량 차이의 가상 fill 생성 금지. 정밀 연결에는 별도 capability와 연결 승인 |
| 실제 시간·표본 필요: v5 | 2026-10-01~10-28 승인된 XNYS 20세션·40슬롯이 아직 도래하지 않았다. | `shadow_gate.py`, `shadow_evaluation.py`, `docs/decision-board-shadow-evaluation.md`, 기존 approved manifest/ledgers | exact-slot 표본, frozen hash, evaluator 수치 조건, 사용자 human PASS 모두 충족. verify-only·fake replay는 표본 아님 |
| 별도 승인 + 실제 표본 필요: horizon 전환 | US SWING과 LONG_TERM의 gate/owner를 독립적으로 전환해야 한다. v5 SWING PASS가 private LONG_TERM 승인을 대체하지 않는다. | design의 Migration and cutover, `docs/runbook.md`, horizon별 source/target manifest | 각 gate 및 restore 통과 후 projection/outbox owner·배포·스케줄 승인. 실제 LONG_TERM gate 별도 |
| 별도 승인 + 실제 시간 필요: rollback/archive/removal | cutover 후 v1-only event를 legacy writer에 축약하지 않는다. 장애 시 v1 writer/outbox 중지, last-known-good v1 read-only projection 유지가 필요하다. | 원본 design §Migration and cutover 9–11, 파일별 dependency inventory | ≥10거래일 안정화 → 승인된 horizon별 read-only archive → 90일 archive/rollback window 종료 → 별도 제거 승인. 공통 dependency는 두 horizon gate 전 제거 금지 |
| 사용자 참여 필요: 실제 UX | 에이전트 E2E는 사용자의 60초 무도움 수행을 증명하지 않는다. 실제 근거/반대 근거/무효화 연결이 부족한 화면은 실사용 gate를 통과할 수 없다. | 아래 5개 합성 task 및 실제 cohort 절차, `web/e2e/decision-board-reports.spec.ts` | task별 실제 사용자 시간·정답·도움 여부 기록, 각 task ≤60초. 실패는 UI/통합 backlog로 반환 |

## private 승인과 gate 범위 제안

기존 private 문서의 8종목, 5 CORE/3 SATELLITE, 승인·active·LONG_TERM, composite rule과 review-required 효과는 유지한다. 실제 8종목 입력을 다시 요청하지 않는다. 추천하는 다음 결정은 **원래의 최소 5종목 기준을 충족하는 8종목 전체 검토 gate**이며, 별도 새 manifest에 review-only expected action을 먼저 승인하는 방식이다. 이는 아직 사용자 결정이나 승인으로 기록하지 않았다. 원문을 T13의 합성 SELL/HOLD로 변환하지 않는다. 필요한 metric/period/baseline이 원문에 없다면 해당 항목만 질문하고 `REVIEW`/미평가로 남긴다.

## 토스 capability 경계

2026-09-07 [공식 OpenAPI](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)의 Order History, OrderExecution, OAuth 정의를 공개 읽기로 재확인했다. 문서상 CLOSED 목록은 cursor/limit/date를 지원하고 execution은 누적량·평균가·최종 체결 시각이다. 개별 fill identity 및 정정 연결 필드는 확인되지 않았다. 조건주문 설명의 다른 채널 포함 문구를 일반 주문에 확대 적용하지 않는다. OAuth scopes가 비어 있으므로 read-only token 권한을 증명하지 않는다. 토큰 재발급은 같은 client의 이전 token을 즉시 무효화하므로 추가 one-shot 승인에는 기존 사용자의 영향과 실행 시간을 포함해야 한다.

| 항목 | 현재 근거 | 아직 필요한 확인 |
| --- | --- | --- |
| 종료 주문 접근·누적 결과 | 2026-09-05 별도 승인된 probe 및 화면 조회, 각각 2요청/1페이지 완료 | 소비된 승인 재사용 불가. 누적 총 4요청은 과거 기록 |
| pagination | 합성 2페이지/완결·중복·loop·상한 실패 테스트, 실제 1페이지 tail 종료 | 실제 continuation page 미관측. 새 bounded approval 범위 내에서만 확인 가능 |
| 수동 주문 포함 | 일반 주문에 대한 전체 채널 보장 미확인 | provider 공식 확인 또는 사용자가 이미 알고 있는 앱 주문과 제한 조회 대조. 에이전트의 주문 생성은 금지 |
| 보존 기간 | from/to 필터는 지원, 서버 보존 기간은 미확인 | provider 명시 확인. 제한 조회의 빈 결과로 retention 단정 금지 |
| 부분체결·정정·취소 | schema 및 합성 상태 처리, 실제 두 one-shot에서는 미관측 | 기존에 발생한 주문의 제한된 관측 및 provider 명세. 시험용 주문 생성/수정/취소 금지 |
| OAuth 권한 | client credentials 접근 관측, scopes 빈 객체 | read-only scope 지원 여부에 대한 provider 근거. 토큰 발급 성공만으로 권한 최소화 통과 금지 |
| fill lineage·Outcome | 주문별 결과만 관측 | 별도 fill/correction identity의 권위 있는 근거 전에는 정밀 Outcome 연결 금지. 이미 구현한 합성 O1/T15 유지 |

## v5 현재 상태

2026-09-07 읽기 전용 재검증에서 gate/양쪽 ledger/runtime freeze 검증이 통과했다. 설치된 ENTRY/HOLDING plist는 승인 후보와 byte-identical하며 두 label 모두 loaded, `runs=0`, not running이었다. evaluator는 `IN_PROGRESS`, completed 0/20, terminal 0/40, due 0이었다. 표본이 없는 hard metric을 PASS로 표시하지 않는다. 디렉터리 이름의 candidate와 실제 승인 상태를 혼동하지 않는다.

기존 v5 cleanup automation은 ACTIVE이며 마지막 승인 슬롯 후 2026-10-29 08:10 KST에 exact 두 label/plist를 정리하는 기존 범위다. 새 automation이나 schedule을 만들지 않았다. 기존 v4 terminal 실패와 `CONFIG_UNAVAILABLE`/`MISSED_EXPECTED`는 과거 증거로 보존한다. v5/private 보호 파일 28개의 세션 시작·종료 hash가 일치했다.

## 수동 UX 평가 준비

`web/playwright.decision-board.config.ts`의 fixture server와 fixture-only Web 서버가 실제 데이터 없이 동일 화면을 제공한다. 기존 테스트를 headed 모드로 실행하거나 같은 fixture 서버를 열어 아래 화면을 사용할 수 있다. 운영 Docker를 재시작하지 않는다. 로그에는 task ID·걸린 초·성공 여부·도움 여부·문제 코드만 기록하고 실제 private 값은 기록하지 않는다.

이번 세션에는 평가용 Web `http://127.0.0.1:43117/login`과 GET 전용 fixture 서버 43118을 열었다. 로그인은 저장소의 공개 테스트 값 `fixture-admin` / `fixture-password`이며 throttle은 memory store다. `SAB_SKIP_ROOT_ENV=1`과 명시적 placeholder 환경만 사용한다. 이 개발 서버의 수명은 현재 로컬 세션에 한정되며 재개 시 위 E2E 설정의 같은 환경으로 다시 시작한다.

| task | 시작 화면과 지시 | 성공 조건 |
| --- | --- | --- |
| UX1 | `/reports?type=decision-board`에서 최신 ENTRY를 열어 한 action과 근거·반대 근거·freshness를 찾는다. | 올바른 report/run kind, action 및 연결된 근거를 ≤60초 안에 찾음 |
| UX2 | `/today` LONG_TERM 합성 lane에서 무효화 조건과 stale 사례를 찾는다. | 조건/기간과 REVIEW 이유를 구분, 합성 advice가 실제 활성화가 아님을 식별 |
| UX3 | `/today` private preview에 저장소의 **합성** private fixture를 선택한다. | 문서 승인 상태와 운영 미연결을 구분, Clear 후 복원되지 않음을 확인 |
| UX4 | `/today?dogfood=corrected-lineage#mandate-evidence-outcome`의 A1 상세를 연다. | exact 승인 version, correction 반영, rebase/freshness 때문에 실제 action이 없는 이유를 찾음 |
| UX5 | `/today` 주문 합성 미리보기에서 정상과 미완결 결과를 차례로 선택한다. | 누적 결과와 개별 fill을 구분하고 미완결을 성공으로 해석하지 않음 |

각 task는 화면이 준비된 시점부터 타이머를 시작하며 에이전트가 답이나 클릭 위치를 알려주지 않는다. 합성 task 결과도 현재 `NOT_EVALUATED`다. 이후 승인된 실제 gate cohort의 각 종목에서 action/근거/반대 근거/invalidation을 찾는 별도 검사를 한다. 실제 연결이 준비되기 전에는 private preview만으로 그 실사용 기준을 통과 처리하지 않는다.

## 정량 성공 기준 대조

| 원본 기준 | 현재 근거와 미완료 범위 |
| --- | --- |
| 수량 100% 배정, 합계 일치, 음수 0 | A1 합성/폐기형 계약 통과. 실제 최신 broker snapshot 기반 배정은 미평가 |
| 불법 상태/미승인 전이/AI 승인 0 | Python/Web/SQL 계약 및 T13 보강. 실제 writer 적용은 미평가 |
| 미승인 mandate action 0, 주문 조작 0 | local policy/projection·egress 계약. 운영 activation 근거 아님 |
| token POST 외 허용 GET, deny/egress audit | 고정 one-shot allowlist·fake transport tests. 장기 운영 egress/권한 audit 미평가 |
| 모든 결정의 policy·반대 근거·freshness·source, critical PRIMARY 강제 | SWING 계약 및 T13 합성 검증. 실제 private composite 입력·sealed source 연결 미구현 |
| canonical payload/hash 재현 | 기존 sealed replay 및 이번 A1 injected-clock correction replay. 실제 integrated DecisionRun 저장 경로 미구현 |
| 합성 5task 및 실제 cohort 60초 무도움 | 자동 responsive/keyboard E2E 통과. 사용자 수행 미평가 |
| 20거래일 UNEXPLAINED 0 | v5 미래 20세션/40슬롯, 현재 0표본 |
| LT 12사례·4cadence·실제 cohort, frozen set 밖 0, gate 전 알림 0 | T19 12+4는 승인된 historical/fake replay. 실제 cohort 및 운영 gate 미평가 |
| 주문 90% Decision 또는 명시적 unlinked/ambiguous, 중복 fill 0 | O1/T15 합성만 통과. 실제 lineage/coverage 분모 미확정 |
| feedback 집계 재현, private note 유출 0 | 기존 O1/public projection 계약. 실제 Outcome connection 미평가 |
| RTO≤30분, journal RPO0, projection checksum | 이번 폐기형 0.078초/RPO0/ACL 포함 checksum 일치. 실제 target 부하·app rollback 미평가 |

## 검증 및 재개 순서

이번 검증은 Python 전체 품질 검사, Web lint/format/typecheck/coverage/build, fixture E2E, 폐기형 PostgreSQL 복구를 사용한다. 상세 최종 개수는 아래 완료 기록에 남긴다. `just ci-web` 대신 이미 설치된 의존성으로 같은 lint/format/typecheck/coverage/build를 실행했다. 불필요한 clean/install/sync를 생략하고 `SAB_SKIP_ROOT_ENV=1` 및 고정 CI placeholder로 개인 `.env`를 로드하지 않았다. loader 테스트는 opt-out일 때 파일 read가 없음을 확인한다. Python 첫 시도는 제한 PATH가 Bash 3.2를 선택해 wrapper 테스트 22개가 실패했으며, 설치된 Bash 5.3을 우선한 재실행으로 판정한다.

최종 검사: `just quality`의 Ruff/format/mypy 및 pytest **3,636 passed, 25 skipped**. A1 PostgreSQL 23개는 T20의 별도 폐기형 harness로 실행했다. 나머지 broker snapshot DB 계약 2개는 해당 DB 경로를 변경하지 않아 실행하지 않았다. Web은 **111 files / 942 tests**, coverage gate·lint·format·typecheck·Next build를 통과했다. Today/Reports E2E 5개와 별도 one-shot 합성 E2E 3개가 통과했고, A1 상세 문구 수정 후 해당 component 6개와 responsive journey 1개를 추가 확인했다. 375/1280px 합성 스크린샷을 육안 검토했으며 페이지 overflow는 375/768/1280px에서 검사했다. 기존 calendar 의존성의 NumPy timedelta deprecation warning은 남아 있다.

운영 provider 재조회, credential 사용, 새 migration 작성/apply/backfill/writer, 운영 Docker 배포, schedule/notification 변경, push는 이번에 실행하지 않았다. 실제 사용자의 60초 UX 및 미래 표본은 대체 검증으로 PASS 처리하지 않았다. 전체 goal과 운영 전환은 미완료다.

| 로컬 커밋 | 변경 |
| --- | --- |
| `40405907` | 주문 누적 결과·일회성 화면 WIP 및 private 승인 표시 |
| `ff1dd0c8` | fixture 검증의 root env 미로딩 |
| `fe9bb063` | T20 복구 권한/RLS checksum |
| `91dcf8e9` | T13 승인·실제 조건 비교 |
| `c2d5289b` | A1 version/slice/evidence 검토 projection 및 UI |

T20 evidence의 app revision은 실행 당시 `f9a7473a`이며 미커밋 수정이 있던 상태다. 해당 runner 수정은 이후 `fe9bb063`으로 기록했다. evidence의 revision 하나만으로 당시 전체 작업 트리가 clean했다고 해석하지 않는다. 원본 .gstack 두 계획은 별도 백업 및 diff 검토 후 쓰기 직전 원본 hash를 확인하고 갱신 내용을 read-back했다.

다음 의존 순서는 다음과 같다.

1. 사용자에게 **기존 승인 8종목 전체 + review-required 효과를 유지하는 새 gate 범위**를 확인하고, 미정 metric/period만 묻는다. 동시에 준비된 합성 UX task를 사용자가 수행한다.
2. 이 결정에 근거해 **추가 migration 작성만** 승인받는다. 대상은 composite review-only provenance, atomic freshness/version read, 필요한 journal/policy persistence다. 기존 DB apply·credential·writer·배포 권한은 포함하지 않는다. 승인 뒤 최소 schema diff, typed adapter와 폐기형 integration을 완성한다.
3. 실제 capability가 필요한 경우에만 새 조회의 기간·계정 선택·token 영향 시간·횟수·표시/저장 범위를 정한다. 기존 두 one-shot을 재실행하거나 부분체결을 만들기 위한 주문은 하지 않는다.
4. 구현·검증된 diff와 checksum을 토대로 실제 DB target/owner/window/backup/restore를 특정한 별도 승인을 받는다. A1 적용만으로 전체 Outcome/publisher가 준비됐다고 간주하지 않는다.
5. v5는 승인된 날짜에 기존 스케줄이 표본을 만든다. exact-slot evaluator와 human PASS 후 해당 horizon의 cutover만 별도 검토한다. LONG_TERM gate, 알림 owner, 안정화·archive·legacy 제거는 각각의 조건을 따른다.
