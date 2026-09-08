# Portfolio review R2 저장과 실제 연결 인계

상태: Accepted · `LOCAL_ONLY`. 2026-09-08. 이 문서는 구현 계약과 검증 기록을 설명한다. R2는 승인된 LONG_TERM 원문을 이용하는 **review-only 저장 경로**다. 운영 연결이나 전체 V1 Decision 제품의 완료를 뜻하지 않는다.

## 새로 연결한 흐름

```text
명시적 authenticated owner/version → Auth 확인 → R1 snapshot
  + 독립된 승인 원문/hash 매핑 + PRIMARY seal/content
  → importer → exact packet + R1 compiler result
  → 단일 transaction: R1 policy/observation import + packet / run / review decision / journal / local outbox
  → authenticated Today read RPC → strict Web projection
  → UNLINKED / AMBIGUOUS / 사용자 확인 NO_ACTION 및 정정 이력
```

`review_transport.py`와 `portfolio-review-store.server.ts`는 기본 비활성이다. 명시적 publishable key와 사용자 bearer를 받아 `/auth/v1/user`를 확인한 뒤 고정 read RPC만 호출한다. owner, top-level authenticated role, 비익명 사용자, 요청 version 전체가 일치해야 한다. 관리자 쿠키와 Supabase 사용자는 별개다. service-role/secret key, user_metadata 기반 owner 추정, 환경변수 credential fallback은 없다. 리디렉션·오류 응답·다른 owner·불완전 version·크기 초과·중복 JSON key는 차단하며 원문 오류를 출력하지 않는다. Web transport는 명시한 freshness budget보다 오래되거나 미래인 저장 결과를 `STALE`로 가린다.

`review_import.py`는 IO 없는 importer다. 독립적으로 승인된 `ApprovalBinding`의 owner/exact version/instrument, 승인 source 원문 hash, holding hash와 원문 포함 관계를 검증한다. `EvidenceBinding`은 PRIMARY content bytes/hash, seal, instrument, source event/seal 시각을 연결한다. rule path·metric/unit·관측 시각·정정의 같은 rule/period·한 갈래 append-only 이력을 확인한다. 승인 hash는 서명이나 인증 자체를 증명하지 않으므로 RPC 응답에서 승인 매핑을 역으로 생성해서는 안 된다. 합성 테스트의 `synthetic_import`는 이 경계의 공개 test double이며 운영 importer가 아니다.

Source와 EvidencePacket을 별도의 범용 프레임워크로 다시 만들지 않았다. 기존 A1 evidence seal/issuer/instrument를 재사용하고, exact R1 envelope·승인 원문·독립 source binding·content·compiler version·freshness/review period를 불변 packet에 함께 저장한다. SQL도 source seal의 instrument/event/sealed 시각과 content hash를 확인한다. replay는 저장한 clock/budget으로 importer와 compiler를 다시 실행하고 canonical packet/projection bytes와 SHA256을 모두 비교한다. 실제 원문을 Web fixture로 복사하지 않는다.

R2의 Decision은 action이 null인 검토 결과다. 한 row라도 `BLOCKED`이면 run과 packet 및 `REVIEW_BLOCKED` journal만 저장하고 Decision/outbox를 만들지 않는다. Today는 최신 run을 읽으므로 이전 정상 결과로 실패를 가리지 않는다. 이는 V1의 BUY/HOLD/SELL Decision, researcher lifecycle, 운영 scheduler journal을 활성화하지 않는다.

## 저장·정정·권한

- 새 migration만 추가했다. A1/R1 migration 이력은 수정하지 않았다. `ReviewStore`는 연결을 만들지 않으며, 활성화된 compiler RPC callable을 명시적으로 주입해야 한다.
- `portfolio_mandate_review_compiler_r2`는 NOLOGIN·NOINHERIT·NOBYPASSRLS이며 membership을 부여하지 않는다. compiler private RPC만 실행할 수 있고 직접 table 접근은 거부한다. authenticated/anon/service_role/candidate도 신규 table을 읽거나 쓸 수 없다. 신규 6개 table에는 강제 RLS를 적용하고 조회는 기존 R1 owner 검사를 재사용한 STABLE invoker/비공개 definer 경계로 제한한다.
- R1 원문·관측 import와 packet/run/Decision/journal/outbox는 한 transaction이다. 기존 원문·관측 ID는 전체 값이 일치할 때만 재사용하며 초기 import와 관측 정정도 말미 실패 시 함께 rollback한다. owner 단위 advisory lock과 `(owner, trigger, revision)` unique key로 같은 요청은 같은 결과를 반환하고, 같은 key의 다른 전체 payload는 충돌로 거부한다. owner 단위 직렬화의 병렬 처리 한계는 코드에 TODO로 기록했다.
- 새 revision은 같은 owner/version 집합/trigger의 바로 이전 revision을 supersede한다. 원문·관측의 기존 row를 삭제하거나 덮어쓰지 않으며 한 이전 run에서 둘로 갈라지는 정정을 허용하지 않는다. 먼저 수집했지만 늦게 도착한 오래된 snapshot이 더 최신 Today 결과를 가리지 못한다.
- Outcome은 review-only 범위에서 `UNLINKED`, `AMBIGUOUS`, `NO_ACTION`만 저장한다. 주문 누적 결과는 `ORDER_AGGREGATE_ONLY`이며 fill ID·수량·체결 확정·Decision 자동 연결을 만들지 않는다. `NO_ACTION`은 DB가 실제 authenticated owner를 확인하는 전용 RPC로만 기록한다. caller의 actor 문자열만으로 확인을 대신할 수 없다. 동일 event 재시도와 정정 분기를 검사한다.
- outbox의 유일한 목적지는 `LOCAL_REVIEW_SINK`다. 외부 payload/address/전송 adapter가 없으며 DB receipt를 원자적으로 기록한다. superseded run은 새 receipt 대상에서 제외한다. receipt 재시도는 중복되지 않으며 운영 notification delivery로 해석하지 않는다.

## 재현

저장소에 이미 설치된 의존성과 PostgreSQL 17.11 도구를 사용한다. DB runner는 기존 DSN을 인자로 받지 않고 매번 새 `/private/tmp` cluster를 생성한다. subprocess에는 실행용 환경만 전달하며 PG routing/credential과 provider credential을 상속하지 않는다. root env는 읽지 않는다.

```sh
SAB_SKIP_ROOT_ENV=1 UV_CACHE_DIR=.uv-cache uv run --no-sync pytest -q tests/test_portfolio_review_store.py
SAB_SKIP_ROOT_ENV=1 UV_CACHE_DIR=.uv-cache uv run --no-sync python scripts/portfolio_mandate_t20_rehearsal.py --include-store --evidence tmp/portfolio-r2-evidence.local.json
SAB_SKIP_ROOT_ENV=1 DECISION_BOARD_E2E_WEB_PORT=43217 DECISION_BOARD_E2E_FIXTURE_PORT=43218 pnpm --dir web run test:e2e:decision-board
```

`--include-store`는 A1/R1/R2 migration·합성 저장/조회·concurrency·권한·late rollback·source와 restore checksum·read-only RPC를 검증한 뒤 cluster를 정리한다. `.pytest.xml`에는 해당 실행의 직접 결과, `.advisors.json`에는 그 폐기형 DB advisor 결과를 남긴다. 일반 T20 모드에서는 R2를 적용하지 않는다. `PORTFOLIO_REVIEW_R2_EXPORT=1`을 명시하면 합성 DB Today 결과를 `web/fixtures/portfolio-review-store.r2.synthetic.json`으로 갱신한다. 기본 실행은 커밋된 fixture를 갱신하지 않는다.

수동 평가 서버는 Bash 5 이상의 `bash scripts/portfolio_review_fixture.sh`로 시작하며 `Ctrl-C`로 해당 두 서버만 종료한다. 기본 포트는 43217/43218이며 `PORTFOLIO_FIXTURE_WEB_PORT`와 `PORTFOLIO_FIXTURE_DATA_PORT`로 바꿀 수 있다. 로그인은 공개 합성 값 `fixture-admin` / `fixture-password`다. 이 서버는 credential을 상속하지 않고 주문 실행을 비활성화한다.

기존 `scripts/portfolio_review_fixture.sh` 단독 실행과 decision-board E2E는 폐기형 DB에서 내보낸 정적 snapshot을 사용한다. 다음 live 모드는 같은 Today 화면을 현재 살아 있는 새 폐기형 DB에 연결한다.

```sh
SAB_SKIP_ROOT_ENV=1 UV_CACHE_DIR=.uv-cache uv run --no-sync python -m scripts.portfolio_mandate_t20_rehearsal --review-ui --evidence tmp/portfolio-r2-live-evidence.local.json
SAB_SKIP_ROOT_ENV=1 UV_CACHE_DIR=.uv-cache uv run --no-sync python -m scripts.portfolio_mandate_t20_rehearsal --review-ui --review-ui-seconds 600 --evidence tmp/portfolio-r2-manual-evidence.local.json
```

첫 명령은 DB 검증과 실제 로그인·브라우저 조작을 수행한다. 둘째 명령은 DB 준비 후 600초 동안 `http://127.0.0.1:43317/today#stored-review`를 사용할 수 있게 한다. 공개 계정은 `fixture-admin` / `fixture-password`이며 로그인 throttle은 기존 memory 구현을 사용한다. `tmp/portfolio-review-live.local.log`의 서버 준비 기록을 확인한다. 수동 창의 최대 길이는 3,600초이며 창이 끝나면 해당 서버 종료 → 사용 후 DB backup/restore/checksum·authenticated read-only 대조 → cluster 정리를 수행한다. 브라우저 탭을 닫아도 창이 즉시 끝나지는 않는다. 기존 합성 dev 서버가 `.next-portfolio-fixture`를 사용 중이면 그 서버를 시작한 터미널에서 먼저 종료해야 한다. runner는 다른 세션 서버를 종료하지 않는다.

화면의 버튼은 합성 입력 재검토, 입력 부족 차단, 관측 값 `2`/`-2`의 append-only 정정, `UNLINKED` → `AMBIGUOUS` 및 사용자가 직접 선택한 `NO_ACTION`을 기록한다. 관측 값과 PRIMARY content는 공개 합성 fixture로 고정한다. 실제 투자 의미나 source를 추정하지 않는다. 결과는 실제 authenticated read RPC를 통해 표시되며 새로고침해도 유지된다. run 선택이 오래됐으면 저장을 거부하고 같은 request ID의 같은 요청은 DB에 동일 bytes로 재시도한다. 세션당 새 요청은 128개로 제한하며 재시작은 새로운 DB를 만든다.

`SAB_SKIP_ROOT_ENV=1`과 `SAB_PORTFOLIO_R2_FIXTURE=1`, 검증된 loopback port가 모두 있어야 live adapter와 API가 활성화된다. 고정 cohort의 합성 Auth HTTP test double을 실제 typed reader에 주입하고 실제 HTTPS 요구를 완화하지 않는다. API는 공통 관리자·local·동일 출처 guard와 1KiB 입력 제한을 사용한다. DB test double은 loopback Host와 고정 합성 bearer를 확인하고 브라우저 Origin, 임의 owner/version/SQL/URL, 알 수 없는 command를 거부한다. 그 bearer는 공개 테스트 표식이며 실제 인증 자격 증명이 아니다. 공개 projection만 반환하고 원문·관측값·source content를 브라우저에 보내지 않는다. 수집·주문·외부 전송 경로가 없다.

실제 Today에서는 기본 `DISABLED`다. 독립된 Supabase 사용자 세션을 발급·연결하는 실제 UX와 owner mapping의 주입은 아직 남아 있다. fixture의 stale/error 선택은 각각 `/today?stored=stale#stored-review`, `/today?stored=error#stored-review`이며 이 상태에서는 저장 버튼도 숨긴다. freshness budget은 합성 packet의 broker 600초/source 180일, Web 결과 3,600초다. 수동 창이 오래되면 broker freshness에 따라 검토가 차단될 수 있다. fixture Next 출력은 `.next-portfolio-fixture`에 둔다.

## 검증 기록

R2 importer/transport/replay/Outcome 단위 검사 27개가 통과했다. 새 폐기형 A1/R1/R2 검사 35개는 migration 말미 실패 시 schema/role 전부 rollback, 같은 요청의 동시 재시도, 전체 table late rollback, 정확한 owner/role 거부, append-only, 오래된 snapshot 거부, 관측 덮어쓰기 거부, Outcome 정정·사용자 확인, outbox receipt 중복 방지를 포함한다. 이 수치는 기존 26개와 R2 9개를 합한 것이다.

Web 새 계약/transport/component 15개와 전체 112 files / 958 tests·coverage gate가 통과했다. 실제 사용자 60초 평가는 수행하지 않았다. 최종 전체 gate·E2E·restore 수치는 [계획 대조 문서](portfolio-goal-reconciliation-20260907.md)의 R2 실행 기록을 따른다.

검증 중 숨은 streaming content에 focus를 주던 E2E는 실제 표시 이후 keyboard 검사로 고쳤다. Next build와 E2E를 함께 실행할 때 `.next` 안의 fixture 출력이 지워지는 문제는 sibling 출력 디렉터리로 수정했다. Supabase advisor의 R2 foreign-key index INFO에는 실제 covering index를 추가했고, RLS policy가 없다는 INFO 6개는 직접 table 접근을 허용하지 않는 의도적인 deny-all이다. 최종 advisor는 INFO 65개, WARN/ERROR 0개다. 새 index의 unused INFO는 극소 합성 부하 결과이며 나머지 A1/R1 INFO는 이 migration이 변경하지 않는 범위다.

## 실제 연결용 manifest

다음 manifest는 **NOT_READY_FOR_EXECUTION**이다. 미정 필드를 채우지 않고 실행 승인을 요청하거나 임의 기본값을 넣지 않는다. 실제 credential/token 값은 manifest에 기록하지 않는다.

| 항목 | 확정 또는 필요한 값 |
| --- | --- |
| A1 migration SHA256 | `1c23293c9b319020a63a2c71613d62fbb0209074a7ac74b384fb98649fbdb2ba` |
| R1 migration SHA256 | `a4656b8e2487904b0e4ce8ab9e492eb9275912e7c5fe3d36dfef9f173fa20ea1` |
| R2 migration SHA256 | `149d73d9d60d54e92c3bbb933ec01fe999df3263524d391f49163ae55d1050ff` |
| app revision/diff | 저장 core `bc6ba3111df2c337f3ab672eb0dc09f2fd7d5be2`와 후속 live fixture 변경. 실제 실행 후보의 `git rev-parse HEAD`를 고정하고 `git show --stat`과 위 세 migration checksum 재대조 |
| target identity | 미정: 정확한 project/database/server identity, version, 현재 migration 목록 |
| owner/version/source | 미정: 종목별 exact A1 version ↔ authenticated owner, 독립 승인 source/holding hash와 PRIMARY seal/content hash |
| compiler principal | 미정: 전용 role의 운영 connection principal과 bounded role membership. service-role 대용 사용 금지 |
| window/작업 범위 | 미정: 적용 시간·담당자·중단 담당자, schema apply와 data import/reader/writer 각각의 범위 |
| backup | 미정: 비공개·비동기화 저장 위치, 접근 권한, custom dump 및 schema/data/ACL/RLS/owner inventory, checksum |
| restore | 별도 복구 DB identity와 역할 준비, row-count·journal RPO 0·projection/data/security checksum 및 authenticated read-only health, RTO ≤30분 |
| 성공 | 전체 version/owner 일치, source와 canonical replay 일치, expected statuses 일치, private/order/external-send 0 |
| 중단 | owner/hash/권한/row-count/checksum 불일치, 실제 source 부족, 모호한 의미, 예상 밖 write/egress 또는 복구 기준 실패 |
| rollback | reader/writer 연결을 비활성화하고 기존 read-only 경로 유지. append-only 자료와 migration history 삭제·down migration·legacy 역투영 없음 |

`GRANT`는 Data API 접근 권한이고 RLS는 row 권한이라는 [공식 보안 문서](https://supabase.com/docs/guides/api/securing-your-api)를 따랐다. 기존 DB의 역할·용량·배포 구성은 폐기형 성공으로 입증되지 않는다. 실제 target에서 승인된 backup과 복구 rehearsal을 먼저 거쳐야 한다.

## 남은 의존성

| 분류 | 남은 작업 |
| --- | --- |
| 실제 입력 | exact version/owner, PRIMARY source/hash, freshness/review period, 미정 metric·period·rating/free-text 의미, 표본 관측 전 고정할 expected-status manifest |
| 실제 연결 구현 | 검증된 Supabase 사용자 session과 명시적 owner/version mapping을 Today 호출에 주입하는 실제 로그인 UX, 실제 A1/version/PRIMARY source를 `ApprovalBinding`/`EvidenceBinding`으로 변환하는 확정 매핑. R1 원문·관측 import와 R2 저장 코드는 연결됐으며 기존 DB 실행은 별도 승인 |
| V1 확장 구현 | action을 가진 전체 SWING/V1 Decision lifecycle·research/source 수집·실제 fill 기반 O1 matching persistence·외부 publisher. R2의 review null-action/aggregate-only 경로와 다른 계약이며 현재 운영 adapter가 아님 |
| 승인 | 기존 DB credential/apply/backfill/writer·운영 role membership·배포·provider 조회·notification/cutover. 기존 one-shot 승인 재사용 불가 |
| 실제 capability | order aggregate와 fill lineage의 차이를 유지. pagination/부분체결/정정/수동 주문/보존 기간/read-only scope는 `NOT_EVALUATED` |
| 시간·표본 | v5 2026-10-01~10-28 XNYS 20세션·40슬롯과 evaluator/human PASS, 별도 LONG_TERM gate. fake clock/replay는 표본이 아님 |
| 사용자 평가 | 합성 5task와 실제 cohort의 종목별 60초 무도움 수행. 에이전트 E2E로 PASS 대체 불가 |

사용자 평가에는 [기존 UX1–UX5](portfolio-goal-reconciliation-20260907.md#수동-ux-평가-준비)를 사용한다. 추가 저장 흐름 지시는 “저장된 검토에서 재검토가 필요한 이유를 찾고, 주문 결과가 왜 확정 연결이 아닌지와 어떤 기록이 정정됐는지 설명한다”이다. 기록 필드는 `task_id / 시작·종료시각 / elapsed_seconds / success / help_used / issue_code`이며 개인 원문/종목값을 기록하지 않는다. 현재 모든 사용자 결과는 `NOT_EVALUATED`다.

다음 행동은 위 live 수동 창에서 합성 저장·정정·Outcome 5task 평가를 기록하는 것이다. 실제 연결에는 매핑 입력 확정이 필요하다. 실행을 승인받을 단계가 되면 위 manifest의 미정 필드를 모두 채운 후 “확정된 target/owner/window에서 명시한 세 migration checksum과 diff에 한해 backup·폐기형 restore 대조·schema apply를 승인한다. data import·writer·배포·provider·알림은 제외한다”처럼 범위를 구분한다. 이 문구는 현재 승인이 아니며 미정 target에 적용할 수 없다.
