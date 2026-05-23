# SPEC: US AI Brief source-backed provider unblock

상태: Completed (2026-05-23)

## Outcome

US AI Brief source-backed provider blocker는 Finnhub를 scheduled default로
선택하면서 해소했다. GitHub repository variable은
`AI_BRIEF_SOURCE_PROVIDER_US=finnhub`로 설정 및 확인했고,
`AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`는 유지했다.

선정 근거는 `reports/2026-05-20.entry.json`의 US `ENTER` 후보
`AXTI.NAS`, `WELL.NYS`, `BABA.NYS`에 대한 2026-05-23 live comparison 3회다.
Finnhub는 3회 모두 coverage 1.000을 기록했고 provider-level `ERROR`가 없었다.
동일 조건에서 Benzinga는 0 sources, Polygon은 freshness coverage 부족 또는 HTTP
429로 실패했다.

OpenAI AI Brief도 Finnhub source provider로 생성했고
`just ai-brief-eval`에서 source-backed recommendation ratio 1.000, system issue
0, `FAIL` 0으로 통과했다. Artifact는 source diagnostics 때문에
`NEEDS_REVIEW_WEAK_NEWS` 상태를 유지하지만, 추천 자체는 source-backed이며 평가
기준을 낮추지 않았다.

## Final Configuration

- GitHub repository variable:
  - `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`
  - `AI_BRIEF_SOURCE_PROVIDER_US=finnhub`
- GitHub repository secrets verified by name:
  - `FINNHUB_API_KEY`
  - `POLYGON_API_KEY`
  - `BENZINGA_API_TOKEN`
  - `OPENAI_API_KEY`
- Selected US provider: `finnhub`
- Backup/comparison providers: `polygon-news`, `benzinga-news`

## Evidence

Live comparison command shape:

```bash
just ai-brief-source-live-compare \
  --entry-report reports/2026-05-20.entry.json \
  --provider benzinga=benzinga-news \
  --provider polygon=polygon-news \
  --provider finnhub=finnhub \
  --market US \
  --output-dir reports/ai-brief-source-live-compare/2026-05-23-run-N \
  --pretty
```

Finnhub source eval command shape:

```bash
just ai-brief-source-eval \
  --entry-report reports/2026-05-20.entry.json \
  --source-report reports/ai-brief-source-live-compare/2026-05-23-run-N/finnhub.sources.json \
  --market US \
  --pretty
```

OpenAI recommendation eval:

```bash
just ai-brief-eval \
  --entry-report reports/2026-05-20.entry.json \
  --ai-brief-report reports/2026-05-23.ai-brief.json \
  --market US \
  --pretty
```

Results:

- Finnhub live captures: 3 runs, coverage 1.000 each, source count 7 each,
  provider-level `ERROR` 0.
- Finnhub source eval: status `WARN`, `FAIL` 0, coverage 1.000.
- AI Brief artifact: `reports/2026-05-23.ai-brief.json`.
- AI Brief eval: status `WARN`, `FAIL` 0, source-backed recommendation ratio
  1.000, system issue count 0.

## Provider Diagnosis

Benzinga:

- Raw API checks returned HTTP 200 with empty arrays for `AXTI`, `WELL`, and
  `BABA`, even without the 72-hour `publishedSince` filter.
- Control tickers such as `AAPL` and `MSFT` returned rows, so the key and endpoint
  were live.
- Diagnosis: not a repository normalization bug; current ticker coverage is
  insufficient for default-provider use.

Polygon:

- Raw API checks returned rows for all three tickers.
- `AXTI` newest raw row: `2026-05-13T15:05:40Z`.
- `WELL` newest raw row: `2026-05-14T15:18:50Z`.
- `BABA` had rows inside the 72-hour freshness window.
- Repeated comparison also hit HTTP 429 once.
- Diagnosis: useful backup/comparison provider, but not the current default
  because freshness coverage and rate-limit evidence are weaker than Finnhub.

Finnhub:

- Covered all three eligible tickers across all three captures.
- Returned source diagnostics only as WARN stale/cap rows.
- Selected as US scheduled default.

## Rollback

If Finnhub later fails scheduled runs:

1. Inspect scheduled artifacts and provider issues before changing defaults.
2. Temporarily unset `AI_BRIEF_SOURCE_PROVIDER_US` or set another provider only
   after fresh live comparison and eval pass.
3. Keep `FINNHUB_API_KEY` available until failed runs are inspected.
4. Re-run live comparison with Finnhub, Polygon, and Benzinga on the next suitable
   US `PRE_OPEN` entry report.

## Documentation Updates

The operational source of truth is:

- `docs/ai-brief-us-source-provider-decision.md`
- `docs/runbook.md`
- `TODOS.md`

Runtime strategy and provider adapter code did not change, so
`docs/ARCHITECTURE.md` and `docs/STRATEGY.md` do not require updates for this
slice.
