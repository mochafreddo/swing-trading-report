# AI Brief US Source Provider Decision

상태: Accepted (provider decision record)

## Decision

2026-05-21 현재 US scheduled AI Brief의 repository variable은
`AI_BRIEF_SOURCE_PROVIDER_US=benzinga-news`로 설정되어 있다. `POLYGON_API_KEY`를
추가해 `polygon-news`와 비교했고 2026-05-21에 70초 간격으로 live comparison을
3회 재실행했지만, 현재 표본에서는 어떤 US vendor provider도 source coverage exit
criteria를 통과하지 못했다. 따라서 기존 scheduled default는 그대로 두되,
production-ready default로 확정하지 않는다.

OpenAI quota blocker는 로컬 재실행에서 해소된 것으로 확인했다. 다만 source-backed
recommendation eval은 여전히 통과하지 못했다. `TODOS.md` Completed에는 추가하지
않는다.

## Evidence

- GitHub repository variables:
  - `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`
  - `AI_BRIEF_SOURCE_PROVIDER_US=benzinga-news`
  - `OPENAI_AI_BRIEF_MODEL=gpt-5.4-mini`
- GitHub repository secrets:
  - Configured: `BENZINGA_API_TOKEN`, `POLYGON_API_KEY`, `OPENAI_API_KEY`,
    `KIS_APP_KEY`, `KIS_APP_SECRET`
  - Not configured among US provider candidates: `FINNHUB_API_KEY`,
    `ALPHA_VANTAGE_API_KEY`, `MARKETAUX_API_TOKEN`
- Local `.envrc.local` contains `BENZINGA_API_TOKEN`, `POLYGON_API_KEY`,
  `OPENAI_API_KEY`, `OPENAI_AI_BRIEF_MODEL`, `KIS_APP_KEY`, `KIS_APP_SECRET`,
  `AI_BRIEF_SOURCE_PROVIDER_KR`, and `AI_BRIEF_SOURCE_PROVIDER_US`. Values must
  be exported, or sourced with `set -a`, before running `uv run`/`just` commands
  that need child-process access.

## Provider Matrix

| Provider | GitHub secret | Local secret | Status |
| --- | --- | --- | --- |
| `finnhub` | missing | missing | excluded, not configured |
| `polygon-news` | configured | configured | comparison candidate, failed coverage/rate-limit evidence |
| `alpha-vantage-news` | missing | missing | excluded, not configured |
| `marketaux-news` | missing | missing | excluded, not configured |
| `benzinga-news` | configured | configured | current scheduled default, failed coverage evidence |

## Live Comparison Runs

Initial live comparison was blocked because `just ai-brief-source-live-compare`
requires at least two `--provider LABEL=PROVIDER` values and only
`BENZINGA_API_TOKEN` was configured at that time. After adding `POLYGON_API_KEY`,
three local live comparison runs were executed against the 2026-05-20 US entry
report. The same entry/buy report pair was then rechecked on 2026-05-21 with
three additional local runs.

Manual workflow evidence:

- Run `26137066499` (`workflow_dispatch`, `market=US`, `model_provider=openai`,
  `source_provider=benzinga-news`) succeeded at the workflow level and produced
  artifacts, but `sab ai-brief` recorded an OpenAI `model_provider_failed`
  system issue.
- Run `26137333442` (`workflow_dispatch`, `market=US`, `model_provider=fake`,
  `source_provider=benzinga-news`) succeeded at the workflow level. Logs showed
  `PARAM_SOURCE_PROVIDER: benzinga-news` and a masked `BENZINGA_API_TOKEN`, but
  this path cannot prove source-backed recommendations because the fake model
  provider records `fake_provider_no_external_sources`.

Raw run artifacts were downloaded only under ignored `tmp/` paths and were not
committed.

Local comparison evidence:

| Run | Artifact dir | Captured at | Benzinga result | Polygon result | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | `tmp/ai-brief-us-provider-selection/2026-05-20/run-1/` | 2026-05-20 | 0 sources, coverage 0.000 | 3 sources, coverage 0.333 | FAIL |
| 2 | `tmp/ai-brief-us-provider-selection/2026-05-20/run-2/` | 2026-05-20 | 0 sources, coverage 0.000 | HTTP 429, 0 sources | FAIL |
| 3 | `tmp/ai-brief-us-provider-selection/2026-05-20/run-3/` | 2026-05-20 | 0 sources, coverage 0.000 | 3 sources, coverage 0.333 | FAIL |
| 4 | `tmp/ai-brief-us-provider-selection/2026-05-20/run-4/` | 2026-05-21 15:05 KST | 0 sources, coverage 0.000, 2389 ms | 3 sources, coverage 0.333, 2204 ms | FAIL |
| 5 | `tmp/ai-brief-us-provider-selection/2026-05-20/run-5/` | 2026-05-21 15:07 KST | 0 sources, coverage 0.000, 1932 ms | 3 sources, coverage 0.333, 1492 ms | FAIL |
| 6 | `tmp/ai-brief-us-provider-selection/2026-05-20/run-6/` | 2026-05-21 15:08 KST | 0 sources, coverage 0.000, 2218 ms | 3 sources, coverage 0.333, 1570 ms | FAIL |

Polygon was the coverage/source-count leader in runs 1, 3, 4, 5, and 6, but only
covered `BABA.NYS`; `AXTI.NAS` and `WELL.NYS` rows were rejected as stale. Run 2
hit Polygon HTTP 429, consistent with a low-rate-limit plan. The 2026-05-21
reruns were spaced by at least 70 seconds and did not hit provider-level ERROR or
HTTP 429, but still failed coverage.

The concrete evidence report pair remains:

- Buy report: `reports/2026-05-19.buy.json`
- Entry report: `reports/2026-05-20.entry.json`
- Eligible US `ENTER` tickers: `AXTI.NAS`, `WELL.NYS`, `BABA.NYS`

The fresh report did not change the coverage result. Benzinga returned no usable
sources and no provider issues. Polygon returned 3 usable sources, all for
`BABA.NYS`; `AXTI.NAS` and `WELL.NYS` rows were rejected as stale.

## Offline Source Eval

Executed against run 3 captured payloads:

- Command: `just ai-brief-source-eval --entry-report ... --compare-source-report
  benzinga=... --compare-source-report polygon=... --market US --pretty`
- Status: `FAIL`
- Benzinga: 0 sources, coverage 0.000
- Polygon: 3 sources, coverage 0.333
- Eval failure: `source_coverage_below_threshold`

Executed again against the 2026-05-21 run 4, 5, and 6 captured payloads:

- Command shape: `just ai-brief-source-eval --entry-report
  reports/2026-05-20.entry.json --compare-source-report
  benzinga=tmp/ai-brief-us-provider-selection/2026-05-20/run-N/benzinga.sources.json
  --compare-source-report
  polygon=tmp/ai-brief-us-provider-selection/2026-05-20/run-N/polygon.sources.json
  --market US --pretty`
- Status for runs 4, 5, and 6: `FAIL`
- Benzinga in each run: 0 sources, coverage 0.000
- Polygon in each run: 3 sources, coverage 0.333
- Single-provider Polygon eval in runs 4, 5, and 6: `FAIL`
- Eval failure: `source_coverage_below_threshold`
- Failure classification: Benzinga returned no provider rows. Polygon returned
  usable fresh rows only for `BABA.NYS`; `AXTI.NAS` and `WELL.NYS` rows were
  correctly rejected by the documented 72-hour freshness contract, and additional
  `BABA.NYS` rows were rejected by the per-ticker cap. No captured row proved a
  repository adapter/eval bug.

The fake-model verification run is useful only as an evaluation guardrail check,
not as proof that Benzinga returned no sources:

- Entry report:
  `tmp/ai-brief-us-provider-selection/run-26137333442/reports/2026-05-19.entry.json`
- Eligible US `ENTER` tickers: `AXTI.NAS`, `WELL.NYS`, `BABA.NYS`
- AI Brief artifact:
  `tmp/ai-brief-us-provider-selection/run-26137333442/reports/2026-05-20.ai-brief.json`
- Recommendation eval status: `FAIL`
- Source-backed recommendation ratio: `0.000`
- Eval failures: `fake_provider_no_external_sources`,
  `unbacked_low_confidence_recommendation`,
  `source_backed_ratio_below_threshold`

## OpenAI AI Brief Verification

OpenAI quota was previously blocked, then restored.

- Earlier run `26137066499` generated a US AI Brief artifact with:
  - `model_provider=openai`
  - `model_name=gpt-5.4-mini`
  - `entry_count=3`
  - `recommendation_count=0`
  - `system_issue_count=1`
- Offline recommendation eval status: `FAIL`
- Failure: `ai_brief_system_issue_error`
- Runtime error: OpenAI HTTP 429 quota exceeded.

Local rerun after quota restoration:

- AI Brief artifact: `reports/2026-05-20.ai-brief.json`
- `model_provider=openai`
- `model_name=gpt-5.4-mini`
- `recommendation_count=3`
- `system_issue_count=0`
- `source_issue_count=3`
- Offline recommendation eval status: `FAIL`
- Source-backed recommendation ratio: `0.000`
- Eval failure: `source_backed_ratio_below_threshold`

No OpenAI AI Brief was rerun on 2026-05-21 because the refreshed source evidence
did not produce a provider that passed offline source eval.

The OpenAI Help Center documents HTTP 429 rate-limit handling and notes that the
account limits/usage tier may need to be increased:
https://help.openai.com/en/articles/5955604-how-can-i-solve-429-too-many-requests-errors

## Cost and Quota

Checked on 2026-05-20.

Benzinga official documentation states:

- API base URL: `https://api.benzinga.com`
- News endpoint: `GET /api/v2/news`
- News endpoint supports ticker-scoped queries and `pageSize`.
- Benzinga applies rate limits and returns HTTP 429 when exceeded.

References:

- https://docs.benzinga.com/api-reference/introduction
- https://docs.benzinga.com/api-reference/news-api/get-news-items
- https://docs.benzinga.com/introduction/introduction
- https://polygon.io/docs/rest/stocks/news
- https://polygon.io/pricing

Repository runtime estimate:

- The adapter calls the provider once per eligible US ticker.
- The 2026-05-20 manual US run had 3 eligible `ENTER` tickers, so expected
  vendor request count for that run was 3 per provider.
- Polygon Basic publicly lists 5 API calls/minute. Because the adapter calls
  once per eligible ticker, repeated three-ticker comparison runs can hit this
  limit unless spaced out or upgraded to a higher plan.
- Monthly request volume depends on future eligible ticker counts and US trading
  days. Account-level plan/quota was not visible from repository metadata and
  must be confirmed by the account owner before marking the default production
  ready.

## Repository Configuration

Required current configuration:

- Repository variable: `AI_BRIEF_SOURCE_PROVIDER_US=benzinga-news`
- Repository secret: `BENZINGA_API_TOKEN`
- Comparison candidate secret: `POLYGON_API_KEY`
- Scheduled model provider requirements: `OPENAI_API_KEY`,
  `OPENAI_AI_BRIEF_MODEL`
- Scheduled scan/entry requirements: `KIS_APP_KEY`, `KIS_APP_SECRET`
- KR default remains: `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`

## Rollback

If US scheduled runs continue producing source-backed failures or provider
errors:

1. Unset `AI_BRIEF_SOURCE_PROVIDER_US` to fall back through the existing chain.
2. Configure or upgrade another US provider secret and rerun live comparison.
3. Keep `BENZINGA_API_TOKEN` available until the failed runs are inspected.
4. Do not mark the Phase 2 US source provider slice complete until source eval
   and OpenAI recommendation eval pass.

## Follow-ups

1. Configure `FINNHUB_API_KEY` as the smallest next provider expansion and rerun
   live comparison with Benzinga, Polygon, and Finnhub against the next suitable
   US `PRE_OPEN` entry report.
2. Re-run live comparison when the US entry candidate set changes or when the
   candidates have current company-specific news.
3. If staying on Polygon Basic, space comparison runs to avoid the 5 calls/minute
   limit, or upgrade to a plan that supports the intended request rate.
4. Rerun US AI Brief with `model_provider=openai` only after a selected provider
   passes source eval.
5. Require `just ai-brief-source-eval` and `just ai-brief-eval` to pass before
   updating `TODOS.md` Completed.
