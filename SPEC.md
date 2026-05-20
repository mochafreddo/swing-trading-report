# SPEC: US AI Brief 기본 Source Provider 선정

## Context

Phase 2 AI Brief는 OpenAI 판단과 여러 live source provider를 지원한다. KR은
`naver-news`를 scheduled 기본 provider로 둘 수 있는 경로가 명확하지만, US는
vendor adapter가 여러 개 구현된 상태에서 아직 기본 provider가 선정되지 않았다.

현재 지원되는 US source provider:

- `finnhub`
- `polygon-news`
- `alpha-vantage-news`
- `marketaux-news`
- `benzinga-news`

Scheduled AI Brief는 이미 US source provider 기본값을
`AI_BRIEF_SOURCE_PROVIDER_US` -> `AI_BRIEF_SOURCE_PROVIDER` -> source API URL
fallback -> `none` 순서로 결정한다.

## Problem

US scheduled AI Brief는 OpenAI로 실행될 수 있지만, source-backed provider 하나를
기본값으로 선정하고 그 선택을 captured payload 품질, 실패 양상, 비용/신뢰성,
offline eval 결과로 뒷받침하기 전까지는 production-ready로 보기 어렵다.

이 단계를 마치지 않으면 US scheduled brief가 `none` 또는 임시 provider로 실행될
수 있고, source disclosure와 추천 품질이 약해진다.

## Goal

US AI Brief의 기본 source provider 하나를 선정하고 문서화한 뒤, 해당 provider와
OpenAI 조합으로 scheduled 설정이 운영 가능함을 검증한다.

선정된 provider는 소스 코드에 하드코딩하지 않고 repository variable/secret으로
설정한다.

## Non-Goals

- 새 뉴스 provider adapter를 추가하지 않는다.
- eval에서 blocking correctness 문제가 드러나지 않는 한 entry 전략, ticker
  eligibility, ranking rule, OpenAI prompt policy를 변경하지 않는다.
- API key, token, 민감한 account metadata가 포함된 live payload, private endpoint
  URL을 커밋하지 않는다.
- `naver-news` 기반 KR provider 동작을 변경하지 않는다.
- Release Please가 관리하는 release 파일을 미리 bump하지 않는다.

## Constraints

- Provider 선정은 기존 live comparison과 offline eval 도구를 사용해야 한다.
- `finnhub`, `polygon-news`, `alpha-vantage-news`, `marketaux-news`,
  `benzinga-news`는 v1에서 US-only provider다.
- Source row는 ticker eligibility, freshness, future-time, duplicate URL, cap,
  URL safety, DNS validation을 계속 통과해야 한다.
- Provider 실패는 `system_issues[]`, `source_issues[]`, 또는 live comparison
  `ERROR` issue로 드러나야 한다. 비교를 통과시키기 위해 실패를 숨기지 않는다.
- GitHub secret과 variable은 이름만 문서화한다.

## Assumptions

- Live comparison을 위해 최소 2개 이상의 US vendor provider secret이 준비되어
  있다. 준비된 provider가 더 적으면, 설정된 provider만 비교하고 그 제약을
  decision record에 남긴다.
- 기존 report fixture나 최근 live `*.entry.json` report로 offline eval을 실행할
  수 있다. 충분하지 않으면 새 US `scan`/`entry` report를 생성한다.
- 기본 provider 선정은 운영 결정이다. 이후 captured evidence가 바뀌면 재선정할
  수 있다.

## Decision Options

Option A: Captured live comparison 데이터에서 가장 강한 provider를 고른다.

- Pros: repository-local evidence와 기존 eval gate를 사용한다.
- Cons: configured secret과 여러 live capture가 필요하다.
- Risk: 짧은 sample window가 특정 뉴스 사이클에 과적합될 수 있다.

Option B: 가장 저렴하거나 이미 사용 가능한 provider를 비교 없이 고른다.

- Pros: 가장 빠르게 설정할 수 있다.
- Cons: Phase 2 quality/reliability exit criteria를 충족하지 못한다.
- Risk: scheduled output은 source-backed일 수 있지만 품질이 낮을 수 있다.

Decision: Option A를 사용한다. Live access가 불완전하면 configured provider
안에서만 고르고, 누락된 provider coverage를 follow-up으로 문서화한다.

## Selection Rubric

Metric이 충돌할 때는 아래 순서로 판단한다.

1. Correctness/source safety: invalid ticker expansion, unsafe URL,
   stale/future row acceptance, 숨겨진 provider failure가 없어야 한다.
2. Coverage: captured US entry report 기준 eligible ticker coverage가 높아야
   한다.
3. Relevance: source title과 URL이 pre-open review에 쓸 수 있을 만큼
   company-specific해야 하며 broad market noise가 적어야 한다.
4. Freshness: source는 대부분 72시간 freshness window 안에 있어야 하고 다음 US
   session 판단에 유효해야 한다.
5. Reliability: provider-level failure, parse failure, rate-limit, timeout이
   적어야 한다.
6. Latency: `duration_ms`는 품질과 신뢰성이 비슷할 때만 우선한다.
7. Cost/quota fit: weekday scheduled 실행이 provider plan 안에서 안정적으로
   돌아야 한다. Decision record에는 확인 날짜, 확인한 provider plan/quota 근거,
   weekday scheduled 예상 호출량, margin을 남긴다.

Provider 선정 최소 조건:

- Live comparison을 최소 3회 실행한다. 가능하면 2개 이상의 US market date에
  걸쳐 실행한다.
- 선정 provider의 captured payload는 offline source eval을 통과해야 한다.
- 성공 comparison set에서 선정 provider에 provider-level `ERROR` issue가 없어야
  한다.
- Coverage나 latency가 더 낮은 provider를 선택한다면 그 이유를 문서화한다.

## Decision Record

Provider 선정 결과는 `docs/ai-brief-us-source-provider-decision.md`에 남긴다.
`TODOS.md`에는 완료 summary만 추가한다.

Decision record는 다음 항목을 포함해야 한다.

- 결정 날짜와 작성자
- 비교한 provider 후보와 실제 configured provider
- 제외한 provider와 제외 사유
- 사용한 US entry report 경로 또는 GitHub Actions artifact 이름
- Live comparison 실행 횟수와 실행 날짜
- Provider별 coverage, issue summary, latency summary, provider-level failure
  여부
- Provider별 cost/quota 확인 날짜, 확인 근거, weekday scheduled 예상 호출량
- 선택 provider와 최종 rationale
- 선택 provider에 필요한 repository variable/secret 이름
- Rollback 후보 또는 fallback 계획

민감한 payload, secret 값, private endpoint 값은 decision record에 쓰지 않는다.
Live payload를 커밋하지 않는 경우에는 sanitized summary와 artifact reference만
기록한다.

## Implementation Plan

1. Configured live provider access를 확인한다.
   - 필요한 GitHub/local secret 이름:
     `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `ALPHA_VANTAGE_API_KEY`,
     `MARKETAUX_API_TOKEN`, `BENZINGA_API_TOKEN`.
   - Secret 값은 출력하지 않는다.

2. 비교에 사용할 US entry report를 찾거나 생성한다.
   - 가능한 경우 최근 US `PRE_OPEN` entry report를 사용한다.
   - 필요하면 기존 `scan`/`entry` workflow 또는 local command로 fresh report를
     생성한다.
   - report artifact를 커밋해야 한다면 민감 정보가 없는 산출물만 포함한다.

3. 설정된 US provider 대상으로 live comparison을 실행한다.
   - Command shape:

     ```bash
     just ai-brief-source-live-compare \
       --entry-report reports/<date>.entry.json \
       --provider finnhub=finnhub \
       --provider polygon=polygon-news \
       --provider alpha=alpha-vantage-news \
       --provider marketaux=marketaux-news \
       --provider benzinga=benzinga-news \
       --market US \
       --pretty
     ```

   - 설정되지 않은 provider는 제외하고 이유를 기록한다.
   - 비교 summary 또는 sanitized captured payload path를 evidence로 남긴다.

4. Captured source payload를 offline eval로 평가한다.
   - Live comparison이 생성한 captured payload를 `just ai-brief-source-eval`의
     `--compare-source-report`로 비교한다.
   - Coverage, issue count, duplicate URL behavior, freshness, aggregate leader를
     확인한다.

5. Candidate provider와 OpenAI로 source-backed US AI Brief를 실행한다.
   - Manual workflow 또는 local command는 `--model-provider openai`와
     `--source-provider <selected-provider>`를 사용해야 한다.
   - Local command shape:

     ```bash
     uv run -m sab ai-brief \
       --entry-report reports/<date>.entry.json \
       --buy-report reports/<date>.buy.json \
       --market US \
       --model-provider openai \
       --source-provider <selected-provider>
     ```

   - GitHub Actions manual run을 사용할 때는 `.github/workflows/ai-brief.yml`의
     `workflow_dispatch` 입력을 `market=US`, `model_provider=openai`,
     `source_provider=<selected-provider>`로 실행한다.
   - 생성된 `*.ai-brief.json`은 다음 명령으로 평가한다.

     ```bash
     just ai-brief-eval \
       --entry-report reports/<date>.entry.json \
       --ai-brief-report reports/<date>.ai-brief.json
     ```

6. Scheduled 기본값을 설정한다.
   - Repository variable:
     `AI_BRIEF_SOURCE_PROVIDER_US=<selected-provider>`.
   - 선택 provider에 맞는 secret이 설정되어 있는지 확인한다.
   - 기존 `AI_BRIEF_SOURCE_PROVIDER_KR=naver-news`가 있으면 유지한다.

7. 문서를 업데이트한다.
   - `docs/runbook.md`에 선정된 US default, 필요한 secret 이름, rollback 경로를
     반영한다.
   - Scheduled default 동작이나 provider 책임이 바뀌는 경우에만
     `docs/ARCHITECTURE.md`를 업데이트한다.
   - 검증 후 `TODOS.md` Completed에 decision slice를 추가한다.

## Acceptance Criteria

- US 기본 source provider 하나가 명시적으로 선정된다.
- `docs/ai-brief-us-source-provider-decision.md`에 selection decision record가
  작성된다.
- Selection decision record는 provider candidates, configured providers,
  excluded providers, comparison date 또는 entry report, live comparison 실행
  횟수, coverage, issue summary, latency summary, reliability note, cost/quota
  근거, final rationale을 포함한다.
- Live comparison은 최소 3회 실행된다. 2개 이상의 US market date를 확보하지
  못하면 decision record에 이유와 follow-up을 남긴다.
- `AI_BRIEF_SOURCE_PROVIDER_US`가 scheduled default variable로 문서화된다.
- 선택 provider에 필요한 secret 이름이 문서화된다.
- 선택 provider와 OpenAI로 source-backed US AI Brief artifact가 최소 1개 생성된다.
- 선택 provider setup의 offline source eval이 통과한다.
- 생성된 US AI Brief artifact의 offline recommendation eval이 통과한다.
- KR scheduled provider 동작은 `naver-news`로 유지된다.
- Secret이나 private endpoint 값이 커밋되지 않는다.

## Test and Verification Plan

Static/local checks:

```bash
just ai-brief-source-live-compare --entry-report reports/<date>.entry.json \
  --provider <label>=<provider> --provider <label>=<provider> \
  --market US --pretty
just ai-brief-source-eval --entry-report reports/<date>.entry.json \
  --compare-source-report <label>=<path> \
  --compare-source-report <label>=<path> \
  --market US --pretty
just ai-brief-eval --entry-report reports/<date>.entry.json \
  --ai-brief-report reports/<date>.ai-brief.json
```

Code 또는 workflow가 변경되면 regression check를 실행한다.

```bash
just quality
```

문서와 repository variable만 바뀌면 `just quality`를 생략한 이유를 기록한다. Shell
또는 YAML snippet이 바뀌면 최소한 static command validation을 우선한다.

## Rollback

선정 provider가 scheduled run에서 실패하면:

1. `AI_BRIEF_SOURCE_PROVIDER_US`를 이전 provider, 다른 검증된 candidate, 또는
   unset 상태로 돌려 기존 fallback chain을 사용한다.
2. 실패 run을 확인하기 전까지 provider secret은 유지한다.
3. Failure mode를 decision record 또는 `TODOS.md`에 기록한다.
4. 대체 provider를 고르기 전에 live comparison을 다시 실행한다.

## Open Questions

- GitHub와 local `.envrc.local`에는 어떤 provider secret이 설정되어 있는가?
- 첫 결정을 내리기에 충분한 최근 US entry report는 몇 개인가?
- Sanitized comparison summary를 커밋할 것인가, 아니면 GitHub Actions artifact
  이름만 decision record에서 참조할 것인가?
