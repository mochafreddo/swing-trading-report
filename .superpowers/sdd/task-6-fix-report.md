# Task 6 fix report — enum authority and full-universe selection binding

## Outcome

Reviewer blocker 두 건을 TDD로 수정했다.

1. compiler-owned `StrEnum` snapshot은 이제 `==` 문자열 equality가 아니라 exact concrete
   enum type과 canonical member singleton identity를 모두 검증한다.
2. HOLDING compilation은 factory-issued `HoldingResearchSelectionV0`를 필수로 받고,
   selection 당시 전체 holding universe snapshot과 compile 당시 전체 universe가 exact
   match하지 않으면 payload를 만들지 않는다.

Task 1 public payload/schema, T3 identity, T4 research transport, T5 claim issuance 계약은
변경하지 않았다. runner/storage/Web/network/model/order 기능도 추가하지 않았다.

## RED evidence

Focused reviewer reproductions:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q
tests/test_decision_board_compiler.py -k
'noncanonical or fresh_equal or compiler_subset or selection_result_mutation'`

- `48 failed, 37 deselected`

실패는 다음을 직접 재현했다.

- ENTRY approval `REVIEW -> 'REVIEW'`가 snapshot equality를 통과한 뒤 `is REVIEW`를
  우회해 BUY가 됨.
- ENTRY exposure `FAIL -> 'FAIL'`가 equality를 통과하지만 `is FAIL`을 우회해 BUY가 됨.
- HOLDING hard exit `NONE -> 'NONE'`이 `is not NONE`을 만족해 current inputs에서 SELL이 됨.
- evidence kind `MATERIAL_ADVERSE -> 'MATERIAL_ADVERSE'`가 action eligibility는 통과하지만
  `is MATERIAL_ADVERSE`를 우회해 AVOID가 BUY로 낮아짐.
- raw `str`, equal `str` subclass, `str.__new__` fresh-equal exact enum이 모든 ENTRY/HOLDING
  enum/state field와 evidence kind에서 fail closed되지 않음.
- factory도 exact enum type만 확인해 fresh-equal non-member를 허용함.
- selection 결과를 compile API에 전달할 수 없어 full universe와 selected subset을 결속할
  방법이 없었고, six-holding selection 뒤 selected five만 compile하는 호출을 막지 못함.

## Enum authority fix

`_is_canonical_enum_member()`는 다음을 모두 요구한다.

- `type(value) is ExpectedEnum`
- `value is member`인 canonical class member가 하나 존재

이 검사를 factory `_require_exact_enum()`와 invocation snapshot에 각각 적용했다.
ENTRY의 item/identity/signal/mandate/price/exposure/research 7개 field, HOLDING의
item/identity/hard-exit/broker/candle/rule/research 7개 field, evidence kind가 precedence에
도달하기 전에 모두 exact identity를 통과해야 한다. selection result의 `ResearchStateV0`
annotation도 같은 검사를 사용한다.

따라서 snapshot의 기존 enum과 문자열 값이 같더라도 raw `str`, `str` subclass,
metadata가 없는 fresh exact enum, `object.__setattr__` post-factory mutation은
`CompilerInputError` 또는 factory `TypeError`로 닫힌다. action branch는 비정상 값을
관찰하지 않는다.

## Research selection/full-universe binding fix

`select_holding_research_v0()`는 public result를 일반 dataclass constructor로 만들지 않고
private allocator와 process-local weakref registry로 발급한다. issuance record는 다음을
소유한다.

- exact selected item ID tuple
- exact ordered `(item_id, ResearchStateV0)` annotation tuple
- selection 당시 전체 holding universe의 canonical snapshot

Universe snapshot에는 item ID/full public instrument, item/identity approval, hard exit,
broker/candle/rule state, research priority/order가 포함된다. research selection 뒤 실제
selected item에 생길 수 있는 research outcome/evidence만 binding에서 제외하며, 이 값들도
각 compiler item/T5 gate에서 독립 검증된다.

`DecisionCompilerV0.compile_holding()`은 이제 `selection=`을 필수로 받는다. compile input을
먼저 exact issued item으로 검증한 뒤 current full-universe snapshot을 selection issuance와
비교한다.

- selected five subset, missing item, duplicate item, changed deterministic fact, 다른
  universe, raw/mutated selection은 `CompilerInputError`다.
- input permutation은 item ID canonical sort 뒤 같은 universe로 인정되며 payload도 같다.
- selected item은 final timeout/error/evidence outcome을 반영할 수 있다.
- unselected item은 caller state와 무관하게 compiler가 effective
  `NOT_SELECTED_CAP`을 적용한다.
- item six current hard stop은 unselected여도 full universe 안에서 compile되어 SELL이다.

이 구조에서는 research cap이 compiler universe를 자를 수 없다. compile이 selection을
생략하거나 selected subset만 전달하는 공개 성공 경로가 없다.

## GREEN evidence

Focused compiler/policy:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q tests/test_decision_board_compiler.py`

- `91 passed`

추가 regression은 모든 enum/state field에 raw string, string subclass, fresh-equal enum
mutation을 교차 적용하고, factory fresh-equal, selection state mutation, selected subset,
changed universe, raw selection, input permutation, selected outcome update를 포함한다.

Compiler + T1/T3/T4/T5 regressions:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q
tests/test_decision_board_compiler.py tests/test_claim_validation.py
tests/test_decision_board_contracts.py tests/test_decision_board_instruments.py
tests/test_decision_board_instruments_bootstrap.py tests/test_research_deadline.py
tests/test_research_provider_contract.py tests/test_research_source_safety.py
tests/test_evidence_researcher.py`

- `398 passed`

Full quality:

`UV_CACHE_DIR=.uv-cache mise exec -- just quality`

- ruff: passed
- format: `291 files already formatted`
- mypy: `278 source files`, no issues
- pytest: `2780 passed, 8 skipped, 1297 warnings`

`git diff --check`: passed.

Warnings are the existing NumPy/pandas calendar deprecations. Shared schema/Web files did not
change, so `just ci-web` was not required.

## Changed files

- `sab/decision_board/compiler.py`
- `sab/decision_board/policy.py`
- `tests/test_decision_board_compiler.py`
- `docs/ARCHITECTURE.md`
- `docs/STRATEGY.md`
- `.superpowers/sdd/task-6-fix-report.md`

## Rollout, rollback, and remaining uncertainty

Rollout order remains T3 identity facts -> T4/T5 evidence -> full-universe selection -> bound
compiler invocation -> future runner/storage. Any runner must retain the issued selection result
through research completion and rebuild final compiler items with unchanged universe facts; only
research state/evidence may differ. A subset-only runner adapter must fail rather than retry with a
smaller universe.

Rollback reverts this compiler/policy hardening commit together. Reverting only the required
`selection=` call would restore the truncation bypass and is unsafe. No data migration, deployment,
production mutation, or destructive rollback exists.

Remaining uncertainty: runner/storage integration is still absent, so cross-process lifetime of
selection issuance is intentionally unsupported. A later runner must perform selection and compile
within one process or introduce a separately designed signed/sealed cross-process authority; it
must not reconstruct authority from serialized selection fields. Storage idempotency, run-level
`BLOCKED|FAILED`, Supabase RLS/indexing, and Web rendering remain outside this fix.
