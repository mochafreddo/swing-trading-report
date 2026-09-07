# Portfolio composite review R1

상태: Accepted · `LOCAL_ONLY`. 2026-09-08 사용자가 기존 승인 8종목 전체의 review-only 의미 유지와 추가 migration 작성을 승인했다. 기존 DB 적용·backfill·writer 활성화·배포는 포함하지 않는다. 이 승인은 실제 관측별 expected result나 운영 조언 승인이 아니다.

## 연결과 사용

`20260907150228_create_portfolio_review_r1.sql`은 기존 A1 위에 holding 원문 보존 테이블과 append-only 관측 테이블, 한 snapshot 읽기 RPC를 추가한다. `review_policy.py`는 RPC envelope를 검증하고 복합 조건을 결정적으로 평가한다. Today의 Mandate → Evidence → Outcome 안 **Long-term composite review**는 폐기형 SQL에서 생성한 합성 8개 결과를 표시한다. T14 scenario와 독립된 고정 snapshot이며 실제 계좌와 연결되지 않는다.

```sh
UV_CACHE_DIR=.uv-cache uv run python scripts/replay_portfolio_mandate_review.py --review-r1
UV_CACHE_DIR=.uv-cache uv run python scripts/portfolio_mandate_t20_rehearsal.py --include-review
```

첫 명령은 커밋된 합성 RPC 응답만 사용한다. 두 번째는 설치된 PostgreSQL 17.11 도구를 PATH에서 사용해 새 loopback cluster를 만들고 검증·복구 후 정리한다. 기존 DB 주소를 받지 않는다. 기본 리허설은 R1을 적용하지 않으며 상속된 opt-in 환경변수를 제거한다.

## 계약과 경계

- Policy는 exact `mandate_version_id`에 결속한다. `holding_document` 원문과 그 생성 hash, 전체 승인 원문의 source hash를 별도로 유지한다. thesis·cadence·concentration·addition·special rule을 scalar SELL predicate로 축약하지 않는다. 원문 hash는 출처 동일성 표식이며 사용자 서명이나 올바른 종목 매핑 자체를 증명하지 않는다.
- Observation은 rule 배열 경로, period, metric/unit, decimal 문자열 또는 boolean, PRIMARY evidence seal, source content hash, USER 또는 DETERMINISTIC_PARSER authority, parser version을 보존한다. 정정은 같은 version/rule/period의 이전 observation을 참조하는 새 row다. 수정·삭제·분기 정정은 거부한다. 미래 정정은 과거 snapshot에 소급하지 않는다.
- `read_portfolio_review_r1`은 `authenticated`에게만 실행을 허용하는 invoker wrapper다. private definer는 빈 search_path, `auth.uid()`, JWT의 top-level role, 모든 요청 버전의 owner를 검사한다. 누락·다른 owner·중복 UUID는 요청 전체를 거부한다. public/anon/authenticated/service_role/candidate의 직접 table 접근과 writer 권한은 열지 않는다.
- `STABLE` 함수의 모든 subquery는 같은 MVCC snapshot을 사용한다. 기존 A1 broker의 `captured_at`, 최신 snapshot version, active allocation과 exact-version slice를 함께 읽는다. A1 JSON 합성 계약에는 없던 timestamp가 실제 A1 DB에는 이미 있어 새 freshness 테이블이 필요하지 않았다.
- Envelope는 정확한 payload text와 SHA256이며 compiler는 중복 JSON key, schema, 크기, hash, 시각과 버전 집합을 검증한다. 결과에는 원문·관측 값·계좌·수량·actor가 없다. 오류도 고정 코드만 반환한다. adapter는 기본 비활성이고 승인된 authenticated RPC callable을 명시적으로 주입해야 한다.

PostgREST의 JWT는 [`request.jwt.claims`](https://docs.postgrest.org/en/stable/references/transactions.html)에 들어간다. R1 검사는 이 형식을 사용하며 legacy 개별 role GUC에 의존하지 않는다. MVCC 의미는 [PostgreSQL STABLE 함수 문서](https://www.postgresql.org/docs/17/xfunc-volatility.html), 권한 설계는 [Supabase database functions](https://supabase.com/docs/guides/database/functions)를 따른다.

## 정책 결과

승인·ACTIVE·LONG_TERM·effective window·broker freshness·allocation·slice·policy visibility를 먼저 확인한다. 실패 row는 `BLOCKED`이며 조건을 평가하지 않는다. freshness budget과 review quarter는 호출자가 명시하고 범위를 검증한다.

구조화된 분기 조건은 Decimal로 비교한다. ALL/ANY는 결측을 false로 덮지 않는 3값 논리를 사용한다. deterioration은 각 연속 분기에서 minimum matches를 충족해야 하며 분기 공백을 건너뛰지 않는다. issuer/instrument, metric/unit, source/seal/record 시각, freshness가 불일치하면 확인된 trigger로 세지 않는다. 유효하지 않은 정정 때문에 과거의 true 관측을 다시 사용하지 않는다.

하나 이상의 hard trigger 또는 deterioration이 확인되면 `THESIS_INVALIDATED_REVIEW_REQUIRED`다. 확인되지 않은 조건·자유 규칙·연간 검토 기한은 `REVIEW_REQUIRED`를 남긴다. 모두 관측되어 미충족인 경우에만 `NO_TRIGGER_OBSERVED`다. 어느 결과든 `action=null`, `advice_enabled=false`다. 매수·매도·보유 권고를 만들지 않는다.

현재 YEAR/TRAILING_YEAR/EVENT의 기간 결속, 신용등급 서열, 비구조화 trigger와 special rule의 의미 판단은 자동 평가하지 않는다. `PERIOD_MAPPING_REQUIRED`, `CONDITION_MAPPING_REQUIRED`, `UNSTRUCTURED_RULE_REQUIRES_REVIEW`, `SPECIAL_RULE_REQUIRES_REVIEW`로 드러낸다. 추가 매수·집중 한도는 원문 보존 범위이며 이번 invalidation compiler의 평가 대상이 아니다. 실제 정책 8개 모두 schema 적합성을 값 출력 없이 확인했지만 실제 관측·expected result·운영 gate를 평가한 것은 아니다.

## 직접 검증과 한계

폐기형 PostgreSQL의 A1/R1 계약 26개가 통과했다. transaction 말미의 의도적 실패가 신규 schema를 남기지 않는지, 8개 합성 정책의 RPC→compiler, 다른 owner/권한 거부, null CHECK 우회, append-only, 동시 broker commit 전후 MVCC를 확인했다. 백업·복구는 schema/journal/projection/table·function 권한/owner/RLS와 신규 policy/observation data checksum을 비교했다. 실행 당시 HEAD는 `677efee5`이며 검증 대상 수정은 아직 미커밋이었다. 실제 운영 DB의 복구 시간·권한을 증명하지 않는다.

Supabase CLI 2.109.1 advisors를 정확한 폐기형 DSN에 대해 실행했다. WARN/ERROR 0개, INFO 58개였다. R1 관련 4개 중 두 개는 의도적인 RLS deny-all과 직접 table 접근 금지다. seal index의 unused 경고는 극소 합성 부하 결과다. correction 복합 FK의 covering-index 경고에는 선두 `supersedes_observation_id`의 UNIQUE index가 이미 있어 최대 한 row를 찾는다. append-only 테이블에 추가 중복 index를 만들지 않았다. 나머지 A1의 INFO는 기존 범위다. TLS URL 설정을 유실하는 [CLI 이슈 #5873](https://github.com/supabase/cli/issues/5873)를 확인하고, 해당 새 loopback DB의 advisor subprocess에만 `PGSSLMODE=disable`을 명시했다. 실제 연결에 이 설정을 적용하지 않는다.

전체 Python/Web/E2E의 최종 개수와 원본 계획 동기화는 [계획 대조 기록](portfolio-goal-reconciliation-20260907.md)에 기록한다. 실제 HTTP PostgREST/Auth 서버와의 연결, 실사용 60초 UX, provider capability, 기존 DB 적용·backfill·writer·배포는 실행하지 않았다.

## 다음 연결의 입력과 실행 조건

1. 기존 승인 원문을 다시 입력하거나 승인할 필요는 없다. 종목별 exact A1 version과 authenticated owner, 관측의 PRIMARY seal/content hash, 명시적인 기간·freshness budget이 필요하다. 현재 Web의 관리자 세션을 Supabase user로 추정하지 않는다.
2. 실제 값과 원문 매핑이 확보되면 default-off adapter에 연결할 authenticated transport, 승인·checksum을 검증하는 importer, 필요한 publisher/DecisionRun/Outcome persistence를 구현·합성 검증한다. 현재는 SQL read RPC까지 구현됐으며 실제 Today HTTP route·transport·writer가 완성된 것으로 간주하지 않는다. synthetic projection에 service-role 키를 붙여 운영 연결을 대신하지 않는다.
3. review-only 8종목 cohort는 승인됐지만 관측별 expected status는 새 manifest에서 표본 수집 전에 별도로 고정한다. 미정 period/rating/free-text 의미를 추정하지 않는다. T19 historical/fake cadence와 v5 SWING gate는 별도다.
4. 실제 DB 적용은 target identity, app revision, migration checksum, backup 위치, owner와 실행 window, ACL 포함 restore 및 rollback 계획이 구체화된 뒤 별도로 승인받는다. default-off reader를 유지하는 rollback을 우선하며 append-only 자료를 삭제하는 down migration은 제공하지 않는다.
