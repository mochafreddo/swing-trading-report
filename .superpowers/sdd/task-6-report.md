# Task 6 report — ENTRY/HOLDING pure compiler truth table

## Outcome and propagation path

`DecisionCompilerV0`가 T3 exact public instrument, compiler-issued typed policy fact,
T5 original issuance inputs를 받아 Task 1 `DecisionPayloadV0`를 만드는 순수 shadow
compiler를 구현했다.

전파 경로는 다음과 같다.

1. upstream seal/identity gate가 exact `InstrumentRefV0`, lane-local approval/dependency/
   signal/exposure/hard-exit/research enum, `sha256:` sealed input hash를 제공한다.
2. `EntryCompilerItemV0`/`HoldingCompilerItemV0` factory가 public-only 값을 trusted copy와
   process-local issuance snapshot으로 봉인한다.
3. `CompilerEvidenceV0`는 T5 validation dict가 아니라 validation과 원래 request/article/
   source/policy object binding을 보관한다.
4. compiler invocation마다 input/evidence issuance를 다시 확인하고 T5
   `is_action_change_eligible_v0`를 호출해 unchanged action-changing `SUPPORTED`만 action
   authority와 evidence reference로 사용한다.
5. precedence lattice를 적용한 item을 UTF-8 rule로 정렬·dedupe하고, Task 1
   `validate_decision_payload()`로 완성 payload를 검증한다.
6. replay byte/hash는 기존 `canonical_json_bytes()`/`decision_payload_hash()`만 사용한다.

runner, envelope `BLOCKED|FAILED` aggregation, storage/index, CLI/scheduler, Web, model,
network, Toss/order는 연결하지 않았다. shared JSON Schema/Web shape도 바꾸지 않았다.

## TDD evidence

### RED

첫 focused RED:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q tests/test_decision_board_compiler.py`

- collection error: `ModuleNotFoundError: No module named 'sab.decision_board.compiler'`

최소 truth-table GREEN 뒤 hardening RED:

- lane prefix가 없는 arbitrary item identity를 factory가 허용함
- 동일 값이지만 wrong binding으로 의도한 T5 fixture가 원래 snapshot과 구별되지 않아
  test fixture를 genuinely changed article/source/policy로 보강함
- 관찰 결과: `2 failed, 35 passed`

후자는 production defect가 아니라 same-value copy도 유효하게 deep revalidate하는 T5 계약에
맞지 않은 fixture였다. article text, source publisher, policy freshness를 실제로 변경한
wrong-binding fixture로 교정했고 모두 action authority를 얻지 못함을 확인했다.

### GREEN

Focused compiler/policy:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q tests/test_decision_board_compiler.py`

- `37 passed`

Focused compiler + T1/T3/T4/T5 regressions:

`UV_CACHE_DIR=.uv-cache mise exec -- uv run pytest -q
tests/test_decision_board_compiler.py tests/test_claim_validation.py
tests/test_decision_board_contracts.py tests/test_decision_board_instruments.py
tests/test_decision_board_instruments_bootstrap.py tests/test_research_deadline.py
tests/test_research_provider_contract.py tests/test_research_source_safety.py
tests/test_evidence_researcher.py`

- `344 passed`

## Complete ENTRY truth table

위 행이 아래 행보다 우선한다.

| Condition | Published result | Evidence effect |
|---|---|---|
| item or identity `REVIEW` | `REVIEW`, no action, typed issue | eligible ref may annotate only |
| signal `ABSENT` or `NOT_READY_ENTER` | omitted | evidence cannot create candidate |
| signal `MISSING|STALE|AMBIGUOUS|CONFLICTED` | `REVIEW` | cannot authorize direction |
| mandate/price `MISSING|STALE|AMBIGUOUS|CONFLICTED` | `REVIEW` | cannot authorize direction |
| exposure `MISSING|STALE|AMBIGUOUS|CONFLICTED` | `REVIEW` | cannot authorize direction |
| exposure `FAIL` | `DECIDED/AVOID` | deterministic fail is sufficient |
| research `NOT_SELECTED_CAP|TIMEOUT|FAILED|COVERAGE_GAP|STALE|CONFLICTED` | `REVIEW` | no guessed veto |
| eligible `MATERIAL_ADVERSE` exists | `DECIDED/AVOID` | only unchanged action-changing `SUPPORTED` |
| otherwise | `DECIDED/BUY` | supportive eligible refs may annotate; cannot create candidate |

Collision proof:

- identity REVIEW + signal absent -> REVIEW, not silent omit.
- stale required price + exposure fail -> REVIEW.
- exposure fail + stale research/adverse evidence -> deterministic AVOID; stale claim itself does
  not grant authority.
- material adverse + evidence conflict -> REVIEW, not guessed AVOID.
- `CONTRADICTED`, `UNCLEAR`, context-only support, raw/mutated/wrong-bound validation -> BUY when
  all deterministic inputs otherwise pass.

## Complete HOLDING truth table

위 행이 아래 행보다 우선한다.

| Condition | Published result | Evidence/research effect |
|---|---|---|
| `HARD_STOP|CONFIRMED_EXIT` and broker/candle/rule all `CURRENT` | `DECIDED/SELL` | cannot be lowered |
| item or identity `REVIEW` | `REVIEW`, no action | unless valid hard SELL already won |
| broker/candle/rule `MISSING|STALE|AMBIGUOUS|CONFLICTED` | `REVIEW` | hard-exit flag is not publishable SELL |
| eligible `MATERIAL_ADVERSE` exists | `REVIEW` | evidence cannot create SELL |
| research `NOT_SELECTED_CAP|TIMEOUT|FAILED|COVERAGE_GAP|STALE|CONFLICTED` | `REVIEW` | item-specific gap |
| otherwise | `DECIDED/HOLD` | supportive eligible refs may annotate |

Hard-SELL proof:

- hard stop/confirmed exit + supportive/adverse evidence, timeout, conflict,
  `NOT_SELECTED_CAP`, item/identity review all stayed SELL when broker/candle/rule were current.
- hard-exit flag + stale candle compiled REVIEW with no action.
- required inline ASCII lattice comment is next to the hard-SELL branch.
- one REVIEW holding and one ordinary holding compiled independently as REVIEW and HOLD.

## Research-cap proof

`select_holding_research_v0` is separate from compilation. It accepts exact issued holding inputs,
sorts `(priority, UTF-8 order, UTF-8 item_id)`, and permits only `0..5` selected items. Zero,
fewer than five, exactly five, duplicate priority/order ties, input permutation, invalid cap 6,
and duplicate items are covered.

Six eligible holdings produced five selected IDs and item six `NOT_SELECTED_CAP`. All six were
then compiled exactly once; item six had a current deterministic hard stop and remained the sixth
published `SELL`. Selection never truncates the compiler universe and never calls T4 or async work.

## T5 trust path and evidence contract

- compiler evidence wrapper is itself process-local issued and exact-type checked.
- every invocation calls T5 `is_action_change_eligible_v0` with the original validation, request,
  article, expected source, and policy; serialized claim dict is never accepted as authority.
- supported + action-changing + unchanged full binding is the only eligible path.
- contradicted, unclear, context-only support, wrong request, changed article, changed source,
  changed policy, raw dict, raw validation, subclass validation, and post-issuance mutation never
  changed BUY/HOLD.
- wrong instrument binding is an internal compiler input error, not a cross-instrument action.
- published evidence is deduped and UTF-8 ordered exact `{claim_id, entailment: SUPPORTED}` only.

## Canonical replay, input hardening, and privacy proof

- input permutation produced equal payload values, canonical bytes, and payload hashes.
- item order uses conservative ASCII item identity UTF-8 bytes; issue/evidence order uses explicit
  UTF-8 code ordering. duplicate item ID or full instrument identity fails closed.
- sealed hash is accepted only through Task 1 `sha256:` validation. ENTRY actions are only
  `BUY|AVOID`; HOLDING actions only `HOLD|SELL`; every REVIEW has issues and no action.
- item/evidence factory issuance snapshots reject post-factory mutation, raw allocation,
  subclassing, and nested identity replacement. unknown fields cannot enter exact factory
  signatures.
- lane prefixes (`entry-`, `holding-`)와 canonical ticker의 exact 결속이 arbitrary
  account/broker identity를 ordering key 밖에 둔다. instrument는 exact public six-field
  projection only다.
- privacy sentinel was absent from payload/error projection. compiler tests patched filesystem,
  socket, subprocess, and URL-open side-effect seams to fail on use; compilation succeeded without
  touching them. No logs, network, model, Toss, order, clock, random, or filesystem call exists in
  the compiler/policy path.

## Changed files

- `sab/decision_board/compiler.py`
- `sab/decision_board/policy.py`
- `sab/decision_board/contracts.py` — narrow public payload validator seam
- `sab/decision_board/__init__.py`
- `tests/test_decision_board_compiler.py`
- `docs/ARCHITECTURE.md`
- `docs/STRATEGY.md`
- `.superpowers/sdd/task-6-report.md`

No shared JSON Schema or Web contract file changed, so `just ci-web` was not required.

## Verification

- focused compiler/policy: `37 passed`
- focused T1/T3/T4/T5 + compiler regression: `344 passed`
- `UV_CACHE_DIR=.uv-cache mise exec -- just quality`
  - ruff passed
  - format: `291 files already formatted`
  - mypy: `278 source files`, no issues
  - pytest: `2726 passed, 8 skipped, 1297 warnings`
- `git diff --check`: passed

Warnings are the existing NumPy/pandas calendar deprecations.

## Rollout, rollback, and remaining uncertainty

Rollout order is T3 identity/freshness producer validation -> T4/T5 recorded synthetic shadow
issuance -> compiler canonical replay -> separately reviewed runner/envelope -> storage/index -> Web
consumer. Rollback removes the future compiler consumer wiring or this pure owner while preserving
T1-T5 contracts and stored producer data. No migration or destructive rollback exists.

Remaining uncertainty: no runner currently maps actual scan/entry/sell facts into compiler input,
classifies shared prerequisite failure as run-level `BLOCKED|FAILED`, or proves cross-process replay
of private sealed input. No storage/index idempotency, Supabase RLS, report discovery, Web rendering,
notification, production provider/model adapter, or live broker/Toss behavior is verified by this
task. Those integrations must preserve the complete holding universe and must not reconstruct T5
action authority from serialized claim dictionaries.
