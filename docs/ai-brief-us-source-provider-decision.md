# AI Brief US Source Provider Decision

상태: Accepted (provider decision record)

## Decision

2026-06-15 기준 US scheduled AI Brief 기본 source provider는 Finnhub-first chain으로 운용한다:

- Preferred chain: `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US=finnhub,benzinga-news,polygon-news`
- Rollback/single-provider fallback: `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`
- KR fallback remains: `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`

2026-05-23의 원 결정은 `AI_BRIEF_SOURCE_PROVIDER_US=finnhub` 단일 provider를 US 기본값으로 확정한 것이다. 2026-06-15 변경은 Finnhub를 첫 provider로 유지하되, Benzinga/Polygon을 source chain fallback/diagnostic coverage 후보로 붙이는 운영 개선이다.

근거는 `reports/2026-05-20.entry.json`의 US `ENTER` 후보 `AXTI.NAS`, `WELL.NYS`, `BABA.NYS`에 대한 3회 live comparison이다. Finnhub는 3회 모두 세 후보를 모두 커버했고, provider-level `ERROR` 없이 offline source eval과 OpenAI recommendation eval을 통과했다. Polygon은 backup/comparison provider로 남기되, 현재 표본에서는 freshness coverage와 rate limit 때문에 기본값으로 쓰지 않는다. Benzinga는 current candidate set에서 raw response부터 빈 배열을 반환해 기본값 후보에서 제외한다.

같은 entry report 기준의 3회 캡처라는 한계는 수용한다. 이유는 이 slice의 blocker가 동일 후보군에서 Benzinga/Polygon이 반복 실패하던 문제였고, Finnhub는 동일 조건에서 일관되게 3/3 coverage와 source-backed recommendation ratio 1.000을 보였기 때문이다. 다음 scheduled US run은 운영 모니터링 follow-up으로 본다.

## Evidence

- GitHub repository variables, verified 2026-05-23:
  - `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`
  - `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`
- GitHub repository secrets, verified by name only 2026-05-23:
  - `FINNHUB_API_KEY`
  - `POLYGON_API_KEY`
  - `BENZINGA_API_TOKEN`
  - `OPENAI_API_KEY`
- Local `.envrc.local` contains the same source/model provider keys needed for local evidence runs. Values must be exported, or sourced with `set -a`, before running `uv run`/`just` commands that need child-process access.

## Provider Matrix

| Provider | GitHub secret | Local secret | Status |
| --- | --- | --- | --- |
| `finnhub` | configured | configured | selected US scheduled default |
| `polygon-news` | configured | configured | backup/comparison candidate; failed freshness/rate-limit evidence |
| `benzinga-news` | configured | configured | backup/comparison candidate; failed current ticker coverage |
| `alpha-vantage-news` | missing | missing | excluded, not configured |
| `marketaux-news` | missing | missing | excluded, not configured |

## Live Comparison Runs

The concrete evidence report pair is:

- Buy report: `reports/2026-05-19.buy.json`
- Entry report: `reports/2026-05-20.entry.json`
- Eligible US `ENTER` tickers: `AXTI.NAS`, `WELL.NYS`, `BABA.NYS`

Earlier 2026-05-20 and 2026-05-21 runs compared only Benzinga and Polygon. Benzinga repeatedly returned 0 usable sources. Polygon covered only `BABA.NYS` and once returned HTTP 429.

After `FINNHUB_API_KEY` was configured, three local live comparison runs were executed on 2026-05-23:

| Run | Artifact dir | Benzinga result | Polygon result | Finnhub result | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | `reports/ai-brief-source-live-compare/2026-05-23-run-1/` | 0 sources, coverage 0.000, 2244 ms | 2 sources, coverage 0.333, 2808 ms | 7 sources, coverage 1.000, 1212 ms | Finnhub WARN, comparison FAIL |
| 2 | `reports/ai-brief-source-live-compare/2026-05-23-run-2/` | 0 sources, coverage 0.000, 1649 ms | 2 sources, coverage 0.333, 1183 ms | 7 sources, coverage 1.000, 1053 ms | Finnhub WARN, comparison FAIL |
| 3 | `reports/ai-brief-source-live-compare/2026-05-23-run-3/` | 0 sources, coverage 0.000, 1443 ms | HTTP 429, 0 sources, 964 ms | 7 sources, coverage 1.000, 1065 ms | Finnhub WARN, comparison FAIL |

The comparison result remains `FAIL` because non-selected providers failed. The selected-provider evidence is the single-provider Finnhub source eval for each run, which returned zero `FAIL` issues and coverage 1.000.

## Offline Source Eval

Finnhub single-provider eval was executed for all three 2026-05-23 captured payloads:

```bash
just ai-brief-source-eval \
  --entry-report reports/2026-05-20.entry.json \
  --source-report reports/ai-brief-source-live-compare/2026-05-23-run-N/finnhub.sources.json \
  --market US \
  --pretty
```

Results for runs 1, 2, and 3:

- Status: `WARN`
- Eligible ticker count: 3
- Covered ticker count: 3
- Coverage ratio: 1.000
- Source count: 7
- Issue count: 11
- Failure count: 0

The warnings were stale rows and per-ticker cap rejections. They do not indicate provider failure and do not reduce accepted coverage because each eligible ticker still had at least one valid fresh source.

## OpenAI AI Brief Verification

Finnhub-backed OpenAI AI Brief generation succeeded locally on 2026-05-23:

- AI Brief artifact: `reports/2026-05-23.ai-brief.json`
- Entry report: `reports/2026-05-20.entry.json`
- `model_provider=openai`
- `model_name=gpt-5.4-mini`
- `recommendation_count=3`
- `system_issue_count=0`
- `source_issue_count=11`
- `brief_state=NEEDS_REVIEW_WEAK_NEWS`
- `brief_reason=weak_news_coverage`

Recommendation eval:

```bash
just ai-brief-eval \
  --entry-report reports/2026-05-20.entry.json \
  --ai-brief-report reports/2026-05-23.ai-brief.json \
  --market US \
  --pretty
```

Result:

- Status: `WARN`
- Source-backed recommendation ratio: 1.000
- Source-backed recommendation count: 3
- System issue count: 0
- Failure count: 0

`NEEDS_REVIEW_WEAK_NEWS` is retained as owner-facing caution because the source provider reported WARN diagnostics. It is not a blocker for selecting Finnhub: the artifact was source-backed, had no system `ERROR`, and passed the offline recommendation evaluator without lowering thresholds.

## Raw Provider Diagnosis

Raw response checks were run on 2026-05-23 without committing raw vendor payloads or printing API keys.

Benzinga:

- `AXTI`, `WELL`, and `BABA` returned HTTP 200 with an empty JSON array.
- Removing the 72-hour `publishedSince` filter still returned 0 results for the same three tickers.
- Control tickers such as `AAPL` and `MSFT` returned news, so the token and endpoint were live.
- Conclusion: current candidate coverage failed at the provider query/data level, not because of repository normalization.

Polygon:

- `AXTI` returned 10 rows, but the newest raw row was `2026-05-13T15:05:40Z`.
- `WELL` returned 10 rows, but the newest raw row was `2026-05-14T15:18:50Z`.
- `BABA` returned 10 rows with 2 rows inside the 72-hour freshness window.
- One repeated comparison run returned HTTP 429.
- Conclusion: Polygon raw data is usable as backup/comparison input, but current default-provider evidence fails because only one of three eligible tickers had fresh sources and the current plan can hit rate limits.

## Cost and Quota

Repository runtime estimate:

- The adapter calls the provider once per eligible US ticker.
- AI Brief model preselection is capped at 5 recommendable candidates, but the source provider universe includes all recommendable candidates plus watch-only candidates. A chain provider therefore makes up to one request per remaining uncovered source-universe ticker, not only the model-input tickers.
- The 2026-05-20 US evidence set had 3 eligible `ENTER` tickers.

Finnhub:

- No provider-level `ERROR` or HTTP 429 was observed in the three evidence runs.
- Account-level quota and plan are not stored in the repository; monitor the next scheduled runs for quota or throttling issues.

Polygon:

- Polygon's public REST free tier is 5 requests/minute. Because this repository calls once per eligible ticker, repeated three-ticker comparison runs can hit that limit unless spaced out or upgraded.

Benzinga:

- The observed key had generous response rate headers during raw checks, but the current ticker coverage was empty for this candidate set.

## Repository Configuration

Required current configuration:

- Preferred repository variable: `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US=finnhub,benzinga-news,polygon-news`
- Rollback repository variable: `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`
- Repository secret: `FINNHUB_API_KEY`
- Backup/comparison candidate secrets: `POLYGON_API_KEY`, `BENZINGA_API_TOKEN`
- Scheduled model provider requirements: `OPENAI_API_KEY`, `OPENAI_AI_BRIEF_MODEL`
- Scheduled scan/entry requirements: `KIS_APP_KEY`, `KIS_APP_SECRET`
- KR default remains: `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`

## Rollback

If US scheduled runs later produce source-backed failures, quota failures, or provider errors:

1. Inspect the scheduled artifacts and provider issues before changing defaults.
2. Temporarily unset `AI_BRIEF_SOURCE_PROVIDER_CHAIN_US` to fall back to `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`, or set the chain to another provider order only after live comparison and eval pass.
3. Keep `FINNHUB_API_KEY` available until failed Finnhub runs are inspected.
4. Re-run live comparison with Finnhub, Polygon, and Benzinga against the next suitable US `PRE_OPEN` entry report.
5. Update this decision record if the default changes.

## Follow-ups

1. Monitor the next US scheduled AI Brief run with `source_provider_chain=finnhub,benzinga-news,polygon-news`.
2. Capture another comparison set when the US entry candidate set changes.
3. Keep Polygon as a backup/comparison provider, but do not promote it without fresh coverage and rate-limit evidence.
4. Keep Benzinga as a diagnostic comparison provider, but do not promote it until raw ticker coverage is demonstrated for current candidates.
