# Task 6 fix2 report — exact ordering scalar issuance

## Outcome

Reviewer의 non-enum ordering scalar issuance gap을 TDD로 수정했다. `item_id`,
`research_priority`, `research_order`는 이제 factory와 selection/compile 매 invocation에서
동일한 exact scalar validator를 통과해야 한다. 정렬, 중복 검사, universe binding은 live
caller field가 아니라 이 validated snapshot만 사용한다.

Task 1 public payload/schema와 T3/T4/T5 계약은 변경하지 않았다. runner, storage, Web,
network/model, order capability도 추가하지 않았다.

## RED evidence

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q
tests/test_decision_board_compiler.py -k
'ordering or nonexact_priority or ordering_scalars or lane_binding'`

- `3 failed, 12 passed, 93 deselected`

실패는 다음 gap을 직접 재현했다.

- issued ENTRY의 `item_id`를 값이 같은 `str` subclass로 바꾸면 snapshot `==`를 통과한 뒤
  output ordering이 caller의 악성 `encode()`를 호출했다.
- HOLDING `research_priority=1`을 `True` 또는 값이 같은 `int` subclass로 바꾸면 selection
  snapshot equality를 통과해 research selection에 참여했다.
- 즉 factory exact-type 검사만으로는 `object.__setattr__` post-issuance mutation을 막을 수
  없었고, selection/order/canonical payload hash가 caller scalar method에 영향을 받을 수
  있었다.

## Fix and propagation path

전파 경로는 `factory input -> process-local issuance snapshot -> research selection/full-universe
binding -> compiler canonical ordering -> Task 1 payload/hash`다.

- `_validated_item_id()`는 exact `str`, conservative ASCII grammar, ENTRY/HOLDING lane prefix,
  trusted instrument canonical ticker binding을 함께 검사한다.
- `_validated_research_priority()`는 exact `int`와 `0..1_000_000` range를 검사해 `bool`과
  모든 `int` subclass를 거부한다.
- `_validated_research_order()`는 exact `str`과 conservative ASCII grammar를 검사한다.
- factory와 `_entry_snapshot()`/`_holding_snapshot()`이 같은 validator를 재사용한다.
- compiler item dedupe/order는 validated item ID와 exact six-field instrument snapshot만
  사용한다.
- research selection과 selection issuance validation도 validated selection snapshot에서
  exact item ID/priority/order를 추출한다. `str(snapshot[0])` 같은 caller conversion과 live
  `item.*` ordering field 접근을 제거했다.

따라서 값이 같은 `str`/`int` subclass, `bool`, lane/ticker mismatch, invalid grammar,
post-selection mutation은 selection 전과 bound compile 모두 `CompilerInputError`로 닫힌다.
검증이 먼저 수행되므로 악성 `encode()`나 comparison method는 호출되지 않는다. 이전 exact
enum authority와 full-universe selection binding은 그대로 유지된다.

## GREEN evidence

Focused compiler/policy:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q
tests/test_decision_board_compiler.py`

- `116 passed`

추가 regression은 ENTRY item ID, HOLDING item ID/research order `str` subclass,
priority `int` subclass/`bool`, factory rejection, `object.__setattr__`, lane/ticker/grammar
mutation, selection 전 rejection, selection 후 bound compile rejection을 포함한다.

Compiler + T1/T3/T4/T5 regressions:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q
tests/test_decision_board_compiler.py tests/test_claim_validation.py
tests/test_decision_board_contracts.py tests/test_decision_board_instruments.py
tests/test_decision_board_instruments_bootstrap.py tests/test_research_deadline.py
tests/test_research_provider_contract.py tests/test_research_source_safety.py
tests/test_evidence_researcher.py`

- `423 passed`

Full quality:

`UV_CACHE_DIR=.uv-cache mise exec -- just quality`

- ruff: passed
- format: `291 files already formatted`
- mypy: `278 source files`, no issues
- pytest: `2805 passed, 8 skipped, 1297 warnings`

`git diff --check`: passed. 경고는 기존 NumPy/pandas calendar deprecation이다. schema/Web
변경이 없어 `just ci-web`은 실행하지 않았다.

## Changed files

- `sab/decision_board/compiler.py`
- `sab/decision_board/policy.py`
- `tests/test_decision_board_compiler.py`
- `docs/ARCHITECTURE.md`
- `docs/STRATEGY.md`
- `.superpowers/sdd/task-6-fix2-report.md`

## Rollout, rollback, and remaining uncertainty

Rollout 순서는 기존과 같이 T3 identity -> T4/T5 evidence -> full-universe research selection
-> bound compiler -> 향후 runner/storage다. 이 commit만 함께 revert하면 이전 compiler API로
복원되며 schema/data migration이나 production mutation은 없다. scalar invocation 검증만
부분적으로 되돌리면 caller subclass method가 다시 canonical ordering에 개입하므로 안전하지
않다.

Runner/storage integration은 여전히 구현되지 않았다. 따라서 process-local selection
issuance의 cross-process 전달, run-level `BLOCKED|FAILED`, storage idempotency/RLS/index,
Web rendering은 검증되지 않은 후속 범위다. 향후 runner도 serialized equal scalar를 authority로
복원하지 말고 같은 process의 issued objects와 full-universe binding을 보존해야 한다.
