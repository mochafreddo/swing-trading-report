# Portfolio Outcome O1 합성 계약

상태: Accepted (synthetic contract only, not deployed)

Portfolio Outcome O1은 실제 broker 주문 이력에 연결하기 전의 capability contract다.
합성 Decision과 execution lineage만 받아 매칭 제안, 보존 범위, 사용자 정정 감사
trail을 실행 가능한 계약으로 고정한다. Toss, provider, DB, writer와 성과 귀속은 이
계약의 생산자나 소비자가 아니다.

## 범위와 전파 경로

계약의 유일한 입력 생산자는 저장소의 합성 fixture다. 동일 fixture를 JSON Schema,
Python validator/matcher와 Web Zod validator가 각각 검증한다.

```text
synthetic decisions + synthetic order/fill lineages
  -> strict JSON Schema / Python / Zod validation
  -> deterministic UNLINKED | MATCH_PROPOSED | AMBIGUOUS proposal
  -> append-only USER confirmation/correction events
  -> strict public projection without execution-private fields
```

`capability.input_mode`는 항상 `SYNTHETIC_ONLY`이고
`provider_history_state`는 항상 `NOT_EVALUATED`다. `retention_window`는 fixture가
완전하게 포함한다고 선언한 합성 시간 범위일 뿐 Toss나 다른 provider의 실제 보존
기간을 증명하지 않는다. `performance_attribution`은 항상 `DISABLED`다.

## 매칭 규칙

Decision은 `slice_id`와 `candidate_id` 중 정확히 하나만 가진다. 보유 포지션 실행은
하나 이상의 `slice_candidate_ids`와 null `candidate_id`를 가지고, 미보유 후보
실행은 빈 slice 목록과 non-null `candidate_id`를 가진다. matchable candidate
Decision/execution은 `BUY`, matchable slice Decision/execution은 `SELL`만 허용한다.

matcher는 다음 조건을 모두 만족하는 Decision만 후보로 남긴다.

- stable `instrument_id`와 `side`가 일치한다.
- 모든 fill 시간이 Decision의 inclusive 유효 구간 안에 있다.
- 모든 fill 가격이 Decision 가격 범위 안에 있다.
- 같은 execution lineage의 partial fill 수량 합계가 Decision 수량 범위 안에 있다.
- slice 또는 candidate target이 정확히 일치한다.

후보가 0개면 `UNLINKED`, 1개면 `MATCH_PROPOSED`, 2개 이상이면
`AMBIGUOUS`다. 여러 slice 또는 Decision이 겹쳐도 자동 연결하지 않는다. matcher는
`MATCH_CONFIRMED`나 그 이후 상태를 만들 수 없다.

order lineage는 취소 후 재주문을 ordered direct supersedes chain으로 표현한다.
partial fill은 lineage에 속한 모든 fill의 fixed-six-decimal 수량을 정확히 합산한다.
`(broker_order_id, broker_fill_id, account_ref_hash)` identity가 중복되면 전체 fixture를
fail closed한다.

## Wire 형식과 개인정보

- 모든 aggregate ID는 lowercase canonical UUID다.
- 모든 시간은 UTC millisecond 형식 `YYYY-MM-DDTHH:MM:SS.mmmZ`다.
- 가격과 수량은 음이 아닌 fixed-six-decimal 문자열이며 의미상 필요한 값은 0보다
  커야 한다.
- account reference는 `hmac-sha256:v1:<64 lowercase hex>` keyed hash만 허용한다.
- broker ID는 길이와 문자 집합이 제한된 opaque identifier다.
- 모든 객체는 unknown field를 거부한다.

public projection은 `outcome_lineage_id`, 상태, nullable `decision_id`, nullable
`feedback_reason`, 마지막 event ID와 시간만 허용한다. quantity, price, account hash,
broker order/fill ID와 `feedback_note_private`가 추가되면 strict reject한다.

## 사용자 확인과 정정

Outcome status enum은 다음 전체 집합을 보존한다.

`UNLINKED | MATCH_PROPOSED | AMBIGUOUS | MATCH_CONFIRMED | EXECUTED |
PARTIALLY_EXECUTED | DISMISSED | NO_ACTION | UNKNOWN`

첫 user event는 `MATCH_CONFIRMATION`이고 actor는 항상 `USER`다. 이후
`CORRECTION`과 `FEEDBACK`은 같은 outcome lineage의 현재 head를 직접
`supersedes_event_id`로 가리키고 이전 event보다 늦어야 한다. helper는 기존 event
배열을 변경하지 않고 검증된 복사본을 반환한다. append helper는 caller가 만든
proposal을 받지 않고 synthetic Decision과 execution lineage를 필수 입력으로 받아
matcher 결과와 known Decision 집합을 내부에서 다시 계산한다. confirmation과
correction의 non-null decision은 해당 lineage의 deterministic
`candidate_decision_ids`에 속해야 한다. `UNLINKED`의 빈 후보에는 confirmation을
추가할 수 없다. 최초 confirmed quantity는 proposal의 fill 합계와 같아야 하고 이후
non-null 정정 수량은 0보다 커야 한다. `FEEDBACK`은 matching state를 변경하지 않는다.

```python
append_user_outcome_event(
    existing_events,
    new_event,
    decisions=synthetic_decisions,
    execution_lineages=synthetic_execution_lineages,
)
```

O1a user event와 public projection은
`MATCH_CONFIRMED | EXECUTED | PARTIALLY_EXECUTED | DISMISSED | UNKNOWN`만 생성한다.
앞의 세 상태는 decision과 private confirmed quantity가 모두 필요하다.
`DISMISSED`와 `UNKNOWN`은 두 값을 모두 null로 지운다. 전체 호환 enum의
`UNLINKED | MATCH_PROPOSED | AMBIGUOUS`는 deterministic proposal 전용이고,
`NO_ACTION`은 no-fill lineage가 설계될 때까지 생성할 수 없는 예약값이다.

feedback reason enum은 다음과 같다.

`EVIDENCE_DISAGREEMENT | TIMING_OR_PRICE | POSITION_RISK | LIQUIDITY_OR_CASH |
EXTERNAL_CONSTRAINT | CHANGED_MIND | OTHER`

note는 private event에만 존재한다. reason이 `OTHER`이면 nonempty note가 필수이고,
reason이 없으면 note도 허용하지 않는다. 다른 reason에서는 note가 선택이다.

## 명시적 비활성 경계

O1은 다음 기능을 추가하거나 활성화하지 않는다.

- Toss 또는 다른 broker/provider의 주문 이력 호출과 pagination 검증
- OAuth scope 또는 실제 보존 기간 판정
- DB schema, migration, RPC, RLS, persistence writer와 projection writer
- 주문 생성, 변경, 취소와 외부 알림
- 자동 `MATCH_CONFIRMED`, 실행 평가 또는 성과 attribution
- Today, Mandate, Evidence 또는 Outcome UI route

실제 capability spike가 주문 이력 범위와 read-only 권한을 별도로 증명한 뒤에만 해당
adapter나 writer를 설계한다. 이 단계의 rollout은 runtime에 연결되지 않은 계약 파일을
merge하는 것뿐이다. 문제가 발견되면 이 독립 파일과 export를 되돌리면 되며 DB,
journal 또는 외부 상태 복구는 필요하지 않다.

## 검증

다음 명령이 O1 경계를 검증한다.

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_portfolio_outcome_contracts.py
pnpm --dir web test -- portfolio-outcome-schema.test.ts
UV_CACHE_DIR=.uv-cache uv run ruff check sab/portfolio_mandate/outcomes.py tests/test_portfolio_outcome_contracts.py
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml sab/portfolio_mandate/outcomes.py tests/test_portfolio_outcome_contracts.py
pnpm --dir web run typecheck
pnpm --dir web run lint
pnpm --dir web run format:check
```
