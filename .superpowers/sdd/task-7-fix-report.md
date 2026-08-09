# Task 7 review fix report

## 범위와 불변식

세 차례의 리뷰 수정은 Decision Board V0의 local writer, Supabase object/index 정합성, Web server-only index read 경계만 다뤘다. legacy report naming/upload/query, runner/CLI/scheduler, Toss/order, notification 동작은 변경하지 않았다.

유지한 핵심 불변식은 다음과 같다.

- 한 identity에는 canonical bytes 하나만 존재한다.
- index failure 뒤 Storage object를 비원자적으로 삭제해 dangling index를 만들지 않는다.
- lock namespace가 교체된 writer는 final report를 성공 반환하지 않는다.
- malformed Decision index row는 노출하지 않되, 유효한 older row 탐색을 막지 않는다.
- legacy detail key의 trim 동작은 유지하고 Decision key만 strict하게 처리한다.

## Review fix 1

- caller report를 strict canonical bytes로 한 번 snapshot하고 alias-free built-in graph를 validate해 key와 bytes가 동일 snapshot에서 나오게 했다. caller mutation, container subclass, cycle, non-finite value 회귀를 추가했다.
- `_open_lock`의 `fstat`/`flock` 실패가 열린 FD를 항상 닫게 했다.
- 새 object의 index 실패 뒤 authoritative row를 재확인한다. matching row는 경쟁 writer repair로 성공 수렴하고, absent/mismatch/error는 object를 보존하면서 `cleanup_failed=true`, `rollback_skipped=true`를 노출한다. `GET absent -> competing insert -> DELETE` race 때문에 Decision path에서는 rollback delete를 하지 않는다.
- Decision Board detail key의 surrounding whitespace를 거부하고 legacy key trim은 보존했다.

Review fix 1 commit은 `259ee3b3`이다.

## Review fix 2

- target별 lock에 더해 열린 report directory FD 자체를 advisory lock해 cooperating writer가 pathname replacement로 다른 lock inode에 진입하지 못하게 했다.
- target lock의 최초 device/inode를 guard에 저장하고 temp write 전후, target link 직전, directory fsync 직전, 성공 직전, final cleanup 직전에 pathname과 open FD가 같은 regular single-link inode인지 재검증한다.
- post-return lock replacement 뒤 별도 inode가 `LOCK_NB`를 획득하는 deterministic probe에서도 첫 writer는 temp/final을 남기지 않고 fail closed한다.
- 새 object를 만든 뒤 authoritative index metadata가 충돌하면 `DecisionBoardIdempotencyConflictError` 타입을 보존하고 `storage_key`, `cleanup_failed`, `rollback_skipped`를 함께 제공한다.
- Decision pagination cursor는 emitted item이 아니라 마지막 raw row의 strict Decision ordering fields에서 계산한다. 안전한 exact raw cursor가 있는 all-malformed page는 legacy cursor로 강등하지 않고 다음 keyset page로 진행한다.
- latest lookup은 page size 1 + lookahead keyset을 최대 100 page로 제한해 malformed newest rows를 건너뛰고 older valid row를 찾거나 안전하게 `null`로 끝낸다.
- Python index state 문자열은 `StrEnum`으로 고정했다. TypeScript row interface의 discriminated-union 전환은 공개 동작과 무관한 후속 maintainability refactor로 남겼다.

Review fix 2 commit은 `8ed39fdf`이다.

## Review fix 3

- writer final cleanup은 target unlock, target close, directory unlock, directory close를 서로 독립된 `try` 경계에서 모두 시도한다. 여러 cleanup failure가 나면 첫 cleanup error를 deterministic하게 노출하고, writer body의 primary exception이 있으면 cleanup failure가 이를 덮지 않는다. FD와 directory lock release를 probe하고 다음 writer가 막히지 않는지 확인했다.
- 최초 authoritative readback에서 확정된 `DecisionBoardIdempotencyConflictError`는 후속 safety recheck가 HTTP/request/invalid JSON으로 불확실해져도 generic index error로 강등하지 않는다. object는 보존하며 typed error에 `storage_key`, `cleanup_failed=true`, `rollback_skipped=true`를 유지한다.
- latest lookup page를 25 raw rows + 1 lookahead로 넓혀 cursor로 안전하게 표현할 수 없는 malformed newest row 뒤의 valid older row도 같은 응답에서 찾는다. output row parser의 strictness는 완화하지 않았다.
- full page가 모두 malformed이면 마지막 raw row의 exact, non-whitespace, quote-safe Decision ordering scalars만 cursor로 사용한다. exact cursor가 없는데 lookahead가 있으면 `502 SupabaseApiError`를 내고, 100-page cap에 도달해도 같은 typed observable failure를 낸다. 실제 exhaustion만 `null`이다.
- 100-page cap은 page당 25 emitted raw rows이므로 한 latest lookup이 노출 검사하는 최대 범위를 2,500 rows로 제한한다.

## 검증

- second-round TDD RED: Python 2 failed / 45 passed, Web 4 failed / 15 passed.
- final-round TDD RED: Python 8 failed / 48 passed, Web 6 failed / 16 passed.
- review-fix Python focused: 57 passed.
- Decision Board + legacy storage: 115 passed.
- Decision Board Web index focused: 22 passed; key/detail 포함 focused 38 passed.
- full `just quality`: Ruff, 295-file format check, mypy 282 sources, pytest 2874 passed / 8 skipped / 1297 dependency warnings.
- full `just ci-web`: install/lint/format/typecheck, 91 files / 655 tests, coverage gate, Next 16 production build all passed.
- `git diff --check`: passed.

테스트는 local filesystem과 recorded fake HTTP만 사용했다. linked/production Supabase, Toss account, order endpoint, deploy/push는 건드리지 않았다.

## Rollout과 남은 위험

Application rollout 순서는 기존대로 migration 이후 Python/Web이다. Review fix는 additive schema를 변경하지 않는다.

Index failure 뒤 orphan object가 남을 수 있지만, 비원자 delete로 authoritative index가 가리키는 object를 제거하는 것보다 안전한 fail-closed 선택이다. 운영 cleanup이 필요하면 DB index와 Storage delete를 묶는 별도 원자 coordination 설계가 선행돼야 한다.
