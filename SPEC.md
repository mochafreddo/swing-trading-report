# SPEC: US AI Brief source-backed provider unblock

## Problem Brief

### Context

Phase 2 AI Brief는 KR/US pre-open review를 OpenAI 판단과 source-backed news
provider로 운영 가능하게 만드는 단계다. KR은 `naver-news`를 scheduled provider로
사용하는 경로가 남아 있고, US는 `finnhub`, `polygon-news`,
`alpha-vantage-news`, `marketaux-news`, `benzinga-news` adapter가 이미 구현되어
있다.

2026-05-20 기준 repository variable은
`AI_BRIEF_SOURCE_PROVIDER_US=benzinga-news`로 설정되어 있지만, 이 값은 scheduled
fallback을 막기 위한 현재 기본값일 뿐 production-ready default로 확정되지 않았다.
`docs/ai-brief-us-source-provider-decision.md`의 최신 근거에 따르면 Benzinga는
usable source 0개, Polygon은 3개 eligible US ticker 중 1개만 커버했고 한 번은
HTTP 429를 맞았다. OpenAI quota 문제는 로컬 재실행에서 해소됐지만,
recommendation eval은 source-backed ratio `0.000`으로 계속 실패했다.

### Problem

US scheduled AI Brief가 OpenAI로 실행되더라도, source-backed source provider가
충분한 coverage와 reliability를 증명하지 못하면 Phase 2 US exit criteria를 완료할
수 없다. 현재 실패를 단순히 provider 선택 문제로만 볼 수 없다. 가능한 원인은
다음 셋 중 하나다.

- 현재 후보 ticker에 실제 fresh company-specific news가 부족하다.
- configured provider 조합이 부족하거나 plan/quota가 scheduled 용도에 맞지 않는다.
- adapter 정규화, symbol mapping, freshness 처리, comparison/eval 계약에 bug가 있다.

이 셋을 구분하지 않고 default를 확정하거나 eval 기준을 낮추면 source disclosure와
추천 품질을 production-ready로 판단할 근거가 약해진다.

### Goal

US Phase 2 blocker를 해소한다. 성공 상태는 selected US provider setup으로
offline source eval과 OpenAI recommendation eval이 모두 통과하고, scheduled
configuration과 운영 문서가 그 선택을 정확히 설명하는 것이다.

### Non-Goals

- 새 vendor adapter를 바로 추가하지 않는다. 추가 adapter는 configured provider와
  existing adapter로 해결할 수 없는 구체적 gap이 확인된 뒤에만 별도 slice로 다룬다.
- `minimum_coverage_ratio`, `minimum_source_backed_ratio`, freshness window를
  통과 목적만으로 낮추지 않는다.
- entry 전략, ticker eligibility, ranking rule, OpenAI prompt policy를 이 blocker
  해결과 무관하게 변경하지 않는다.
- KR `naver-news` scheduled behavior를 변경하지 않는다.
- secret 값, private endpoint, vendor raw payload, 민감한 account metadata를
  커밋하지 않는다.
- Release Please가 관리하는 release file은 건드리지 않는다.

### Constraints

- Source row는 기존 ticker eligibility, freshness, future-time, duplicate URL,
  cap, URL safety, DNS validation 계약을 계속 통과해야 한다.
- Provider failure는 `system_issues[]`, `source_issues[]`, 또는 live comparison
  top-level `ERROR` issue로 드러나야 한다. 실패를 숨겨 eval을 통과시키지 않는다.
- 현재 configured US candidates는 `benzinga-news`와 `polygon-news`다. 추가 비교는
  `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `MARKETAUX_API_TOKEN` 중 실제로
  설정된 secret이 있을 때만 포함한다.
- Polygon Basic처럼 low-rate-limit plan을 쓰는 provider는 repeated comparison에서
  rate limit을 피할 만큼 간격을 둔다.

## Impact Note

- What changes: US AI Brief source provider evidence, provider decision record,
  scheduled provider documentation, and possibly a small provider/eval bug fix if
  root cause is code.
- What might break: scheduled US source provider selection, provider secret/env
  wiring, source normalization, recommendation eval expectations.
- Tests/docs: live comparison, offline source eval, OpenAI recommendation eval,
  `docs/ai-brief-us-source-provider-decision.md`, `docs/runbook.md`, and
  `TODOS.md`; run `just quality` if runtime code or workflow code changes.

## Success Criteria

Phase 2 US is complete only when all of these are true:

- A single US scheduled source provider is selected as production-ready.
- The selected provider has no provider-level `ERROR` issue in the passing
  evidence set.
- Offline source eval passes for the selected setup against the US entry report
  used as evidence.
- OpenAI AI Brief generation with the selected provider creates an artifact with
  no `ERROR` system issue.
- Offline recommendation eval passes for that OpenAI artifact.
- The decision record documents configured providers, excluded providers,
  comparison dates, entry report paths or artifact references, coverage, issue
  summary, latency, rate-limit behavior, cost/quota fit, final rationale, and
  rollback.
- The passing evidence set includes at least 3 live comparison captures for the
  selected provider. Prefer at least 2 distinct US market dates; if this is not
  available, the decision record must explain why the narrower sample is still
  acceptable before the slice can be completed.
- `AI_BRIEF_SOURCE_PROVIDER_US=<selected-provider>` is actually set and verified
  in GitHub repository variables, not only documented. If automation cannot set
  or verify it, this remains a blocker and `TODOS.md` must not be marked
  complete.
- The selected provider's required GitHub secret names and local setup path are
  documented in `docs/runbook.md` and either `.env.example` or
  `.envrc.local.example`, depending on the existing project convention for that
  variable.
- KR scheduled provider remains `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`.
- No secret values or raw vendor payloads are committed.

If no provider can pass, the slice is not complete. The acceptable output is then
an updated blocker record with root cause, evidence, and the smallest next
configuration or implementation request.

## Decision Options

Option A: Refresh evidence with currently configured providers only.

- Pros: smallest operational change; uses existing adapters and tools.
- Cons: current evidence already failed with Benzinga and Polygon.
- Risk: another sparse-news sample may still fail without proving adapter quality.

Option B: Add one existing-but-unconfigured provider to comparison, preferably
`finnhub` if an API key is available.

- Pros: broadens evidence without adding code or a new adapter.
- Cons: requires a secret/configuration step outside the repository.
- Risk: another vendor may also lack fresh company-specific coverage for the
  current entry set.

Option C: Fix an adapter/eval bug found while diagnosing captured provider
payloads.

- Pros: addresses a real correctness issue if the provider returned usable rows
  that the repository rejected incorrectly.
- Cons: requires code changes and regression tests.
- Risk: easy to overfit to one vendor response shape unless tests capture the
  contract clearly.

Decision: Execute Option A first, but treat another all-fail result as diagnostic
evidence, not completion. If A fails because coverage is sparse and no adapter
bug is found, move to Option B. Use Option C only when provider output proves a
repository bug.

## Execution Plan

### 1. Confirm local and repository configuration

- Confirm which provider variables/secrets are configured by name only:
  `AI_BRIEF_SOURCE_PROVIDER_US`, `BENZINGA_API_TOKEN`, `POLYGON_API_KEY`,
  `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `MARKETAUX_API_TOKEN`,
  `OPENAI_API_KEY`, `OPENAI_AI_BRIEF_MODEL`, `KIS_APP_KEY`, `KIS_APP_SECRET`.
- Do not print secret values.
- For local commands that need `.envrc.local`, export values into child
  processes without echoing them:

```bash
set -a
source .envrc.local
set +a
```

### 2. Select or create evidence entry reports

- Prefer a recent US `PRE_OPEN` entry report with at least one `ENTER` candidate.
- If the latest report is stale or has no US `ENTER` candidates, generate fresh
  US reports:

```bash
just scan --universe both --markets US
just entry --buy-report reports/<buy-date>.buy.json --provider kis --mode PRE_OPEN --market US
```

- Record the exact buy and entry report paths in the decision record. Do not
  assume the buy report date and entry report date are the same; pre-open entry
  often uses a previous-session buy report.
- Keep raw temporary artifacts under `tmp/` unless a sanitized summary is needed.

### 3. Run live provider comparison

- Start with currently configured providers:

```bash
just ai-brief-source-live-compare \
  --entry-report reports/<entry-date>.entry.json \
  --buy-report reports/<buy-date>.buy.json \
  --provider benzinga=benzinga-news \
  --provider polygon=polygon-news \
  --market US \
  --output-dir tmp/ai-brief-us-provider-selection/<entry-date>/run-1 \
  --pretty
```

- Repeat at least three runs for the selected provider. If rate limits, market
  holidays, or missing candidates prevent three captures, record that as an
  unresolved blocker unless the decision record explicitly justifies why the
  smaller evidence set is sufficient.
- If Polygon is included on a 5 calls/minute plan and there are 3 eligible
  tickers, leave at least 70 seconds between comparison runs.
- Add configured existing providers to the command only when their secrets are
  available:

```bash
--provider finnhub=finnhub
--provider alpha=alpha-vantage-news
--provider marketaux=marketaux-news
```

- Exclude unconfigured providers explicitly in the decision record.

### 4. Evaluate captured source payloads offline

For comparison mode:

```bash
just ai-brief-source-eval \
  --entry-report reports/<entry-date>.entry.json \
  --compare-source-report benzinga=tmp/ai-brief-us-provider-selection/<entry-date>/run-1/benzinga.sources.json \
  --compare-source-report polygon=tmp/ai-brief-us-provider-selection/<entry-date>/run-1/polygon.sources.json \
  --market US \
  --pretty
```

For a single selected payload:

```bash
just ai-brief-source-eval \
  --entry-report reports/<entry-date>.entry.json \
  --source-report tmp/ai-brief-us-provider-selection/<entry-date>/run-1/<label>.sources.json \
  --market US \
  --pretty
```

Inspect failure modes before editing code:

- `source_coverage_below_threshold`: distinguish no provider rows from rejected
  stale/invalid rows.
- Provider top-level `ERROR`: inspect provider failure category and rate-limit
  behavior.
- Ticker-level WARN issues: check whether symbol mapping, company-name
  enrichment, freshness, or URL safety caused the rejection.

### 5. Diagnose and fix only proven code defects

If provider payload contains rows that should pass the documented contract but do
not:

- Read the affected files end-to-end before editing:
  `sab/ai_brief_sources.py`, `sab/ai_brief_source_eval.py`,
  `sab/ai_brief_source_live_compare.py`, and the relevant tests.
- Add a regression test before changing implementation. Likely test locations:
  `tests/test_ai_brief.py` or `tests/test_ai_brief_source_live_compare.py`.
- Keep the fix scoped to the failing provider contract.
- Do not broaden accepted URLs, timestamps, tickers, or market scope beyond the
  documented contract.

If providers truly return no fresh company-specific rows, do not change code.
Document the data gap and move to another configured provider or request the
smallest missing provider secret.

### 6. Verify OpenAI recommendation quality with the selected provider

Generate a US AI Brief artifact with OpenAI and the selected provider:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief \
  --entry-report reports/<entry-date>.entry.json \
  --buy-report reports/<buy-date>.buy.json \
  --market US \
  --model-provider openai \
  --source-provider <selected-provider>
```

Evaluate the artifact:

```bash
just ai-brief-eval \
  --entry-report reports/<entry-date>.entry.json \
  --ai-brief-report reports/<ai-brief-date>.ai-brief.json \
  --market US \
  --pretty
```

The recommendation eval must pass without lowering
`--minimum-source-backed-ratio`.

### 7. Apply and verify scheduled configuration

After source and recommendation evals pass, set the scheduled US provider to the
selected provider. Use GitHub UI or a non-secret CLI command; do not print secret
values.

```bash
gh variable set AI_BRIEF_SOURCE_PROVIDER_US --body "<selected-provider>"
gh variable list | rg '^AI_BRIEF_SOURCE_PROVIDER_US'
```

- Verify the listed value is the selected provider.
- Verify the selected provider's required repository secret exists by name only.
- If the variable cannot be set or verified, stop and update the decision record
  as blocked. Do not update `TODOS.md` Completed.
- Keep `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`.

### 8. Update operational docs and TODOs

If the selected provider passes:

- Update `docs/ai-brief-us-source-provider-decision.md` from blocked evidence to
  final production-ready decision.
- Update `docs/runbook.md` with the selected US default, required secret names,
  rate-limit or quota note, and rollback.
- Update `.env.example` or `.envrc.local.example` when the selected provider or
  model setup requires local variables that are not already represented there.
- Update `TODOS.md` Completed with the US provider completion slice.
- Evaluate whether `docs/ARCHITECTURE.md` or `docs/STRATEGY.md` changed. If the
  runtime responsibility or strategy logic did not change, record that no update
  is needed.

If no provider passes:

- Keep `TODOS.md` incomplete.
- Update the decision record with the new failed evidence and the next smallest
  action, such as configuring `FINNHUB_API_KEY`, upgrading a provider plan, or
  scheduling another comparison when the US candidate set changes.

## Test and Verification Plan

For documentation/spec-only changes:

```bash
git diff --check
```

For provider evidence/configuration changes:

```bash
just ai-brief-source-live-compare ...
just ai-brief-source-eval ...
just ai-brief-eval ...
```

For Python runtime fixes:

```bash
just test tests/test_ai_brief.py tests/test_ai_brief_source_live_compare.py
just quality
```

For workflow YAML changes:

```bash
just test tests/test_ai_brief_workflow.py
just quality
```

If a full gate is skipped, record why in the final work summary.

## Rollback

If the selected provider later fails scheduled runs:

1. Revert `AI_BRIEF_SOURCE_PROVIDER_US` to the previous verified provider, another
   passing candidate, or unset it to use the existing fallback chain.
2. Keep the provider secret available until the failed run and artifacts are
   inspected.
3. Record the failure mode in `docs/ai-brief-us-source-provider-decision.md`.
4. Re-run live comparison before choosing a new default.

## Open Questions

- Is the account owner willing to configure `FINNHUB_API_KEY` if Benzinga and
  Polygon continue to fail coverage?
- Should provider decision evidence reference only sanitized summaries, or are
  non-sensitive captured source payloads acceptable under `reports/`?
- How many distinct US market dates are enough for the first production-ready
  decision if fresh candidates are sparse?
