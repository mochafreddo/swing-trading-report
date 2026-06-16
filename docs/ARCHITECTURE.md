# 아키텍처 개요 — Swing Trading Report

상태: Accepted (v1.1 기준)  
대상: 로컬 단일 사용자 운영 + GitHub Actions 자동 실행

## 문서 상태

### 현재 제공

- `scan`/`sell`/`entry` 파이프라인, 로컬/수동/scheduled workflow `ai-brief`, 로컬 Docker scheduled AI Brief primary, GitHub monitor/fallback, AI Brief source payload 수집/평가/live 비교, AI Brief recommendation artifact 평가, 웹 Reports/Holdings/Run/Metrics, schedule/opt-in 알림 경로를 현재 아키텍처 기준으로 설명합니다.
- `report_index`와 `runtime_state`, Supabase Storage, GitHub Actions `scan`/`sell`/`cleanup`/`ai-brief` 연결이 현재 제공 범위입니다.

### 실험

- 별도 experimental runtime topology는 두지 않습니다. 구현되지 않은 운영 흐름은 backlog로 분리합니다.

### 백로그

- 웹 `Run` 탭과 GitHub Actions workflow에 standalone `entry` 전용 실행 경로 추가
- branch protection stage1/stage2 적용은 별도 governance backlog

### 폐기 후보

- `ADR-0006` 시절 가정(Storage listing 직접 조회, 인증 미도입)으로 되돌리는 방향은 채택하지 않습니다.

## 관련 문서

- 운영 절차: [operations.md](operations.md)
- 배포/롤백: [deployment.md](deployment.md)
- 장애 대응: [troubleshooting.md](troubleshooting.md)
- API/CLI 계약: [api.md](api.md)
- 설정: [configuration.md](configuration.md), [config-reference.md](config-reference.md)

## 1. 시스템 목적

- Python 엔진(`sab`)으로 KR/US 종목을 평가해 `buy`/`sell`/`entry` JSON 리포트를 생성하고, entry 결과를 로컬 `ai-brief` JSON으로 요약합니다.
- Next.js 웹(`web`)은 리포트 열람, 운영 메트릭 대시보드, 보유 종목 CRUD, 워크플로우 실행 트리거를 제공합니다.
- Supabase는 보유 종목(Postgres), 리포트(Storage), 런타임 상태(Postgres, 기본값)를 저장하는 단일 백엔드입니다.
- GitHub Actions는 `scan`/`sell`/`cleanup` 스케줄과 수동 AI Brief 실행을 담당하고, scheduled AI Brief에서는 로컬 Docker primary를 감시하거나 fallback을 수행합니다.

## 2. 시스템 컨텍스트

```mermaid
flowchart LR
  U["User (Local Browser)"] --> W["Next.js Web (web)"]
  W -->|CRUD / 조회| SDB["Supabase Postgres"]
  W -->|리포트 목록/상세| SST["Supabase Storage (reports)"]
  W -->|workflow_dispatch| GHA["GitHub Actions (scan/sell/cleanup/ai-brief)"]
  U -->|manual workflow_dispatch| GHA
  LD["macOS launchd"] --> DK["One-shot Docker scheduler"]
  DK --> P

  GHA --> P["Python Engine (sab scan/sell/entry/ai-brief)"]
  P --> KIS["KIS Open API"]
  P --> PY["PyKRX (KR fallback/provider)"]
  P --> SRC["AI Brief Source Providers (local-json/http-json/finnhub/polygon-news/alpha-vantage-news/marketaux-news/benzinga-news/naver-news)"]
  P --> LF["Local Filesystem (data/, reports/)"]
  P -->|업로드 + 인덱스 upsert| SST
  P -->|report_index / runtime_state| SDB

  GHA --> TG["Telegram / Slack (monitor/fallback + manual opt-in)"]
  DK --> TG
```

## 3. 런타임 컴포넌트

| 컴포넌트 | 역할 | 주요 코드 |
|---|---|---|
| CLI 엔트리 | `scan`/`sell`/`entry`/`ai-brief`/`ai-brief-scheduled` 서브커맨드 라우팅 | `sab/__main__.py` |
| Scan 오케스트레이션 | 티커 로드, 스크리너, 시세 수집, 매수 평가, 리포트 생성 | `sab/scan.py`(엔트리), `sab/scan_screener.py`, `sab/scan_evaluation.py` |
| Sell 오케스트레이션 | 보유종목 기준 시세 수집, 매도/점검 평가, 리포트 생성 | `sab/sell.py`(엔트리), `sab/sell_evaluation.py`, `sab/sell_runtime.py` |
| AI Brief 오케스트레이션 | entry 리포트 소비, recommendable/watch/excluded 후보 분류, source provider chain context, `fake`/`openai` 모델 provider 요약, 리포트 생성/업로드 | `sab/ai_brief.py`, `sab/ai_brief_candidates.py`, `sab/ai_brief_source_chain.py`, `sab/ai_brief_sources.py`, `sab/ai_brief_providers.py` |
| Scheduled AI Brief runner | market/session/role guard, runtime_state lock/marker, 로컬 one-shot scan→entry→ai-brief 실행, notification reconciliation, GitHub monitor/fallback 공통 entrypoint | `sab/scheduler/*`(시간 정책: `schedule_policy.py`), `docker-compose.scheduler.yml`, `scripts/launchd/*`, `.github/workflows/ai-brief.yml` |
| AI Brief source 수집 보조 | RSS/Atom/RDF 로컬 파일 또는 live HTTPS feed URL을 `http-json`/`local-json` 호환 `sources[]` payload로 변환 | `sab/ai_brief_source_collectors.py`, `scripts/collect_ai_brief_sources.py` |
| AI Brief source 품질 평가/비교 | 수집한 `http-json` 호환 source payload는 네트워크/secret 없이 기존 source 정규화 규칙으로 평가/비교하고, live provider capture는 provider 호출 후 저장된 payload를 같은 evaluator로 비교하며 provider별 `duration_ms`를 남김 | `sab/ai_brief_source_eval.py`, `sab/ai_brief_source_live_compare.py`, `scripts/eval_ai_brief_sources.py`, `scripts/compare_ai_brief_live_sources.py` |
| AI Brief recommendation 품질 평가 | 생성된 `*.ai-brief.json`을 네트워크/secret 없이 entry 후보 기준으로 검증하고, rank 연속성/source-backed ratio/confidence 안전성/summary count를 수동·scheduled 성공 경로의 fail-closed 품질 게이트로 평가 | `sab/ai_brief_eval.py`, `scripts/eval_ai_brief_recommendations.py` |
| 데이터 파이프라인 | KIS/PyKRX 초기화, 캐시 조회, 폴백/재시도 | `sab/market_data_pipeline.py`, `sab/data/kis_client.py`(facade), `sab/data/kis/{auth,calendar,common,quote,ranking}.py` |
| 시그널 엔진 | EMA/RSI/ATR 기반 평가 로직 | `sab/signals/*` |
| 리포트 계층 | 로컬 JSON 원자적 저장 + Supabase 업로드/인덱싱 + 알림 텍스트 렌더링, AI Brief 판단 상태(`NO_SIGNAL`/`NEEDS_REVIEW_WATCH_ONLY`/`FINAL_JUDGMENT`/`NEEDS_REVIEW_WEAK_NEWS`)와 scheduled skip 상태 결정 | `sab/report/markdown.py`, `sab/report/sell_report.py`, `sab/report/entry_report.py`, `sab/report/ai_brief_report.py`, `sab/report/ai_brief_skip_report.py`, `sab/report/ai_brief_state.py`, `sab/report/notification_text.py`, `sab/report/supabase_storage.py`, `sab/report/storage_key.py` |
| 웹 API 경계 | 페이지 접근 제어(미들웨어) + API 가드 단일 진입점(route helper) | `web/middleware.ts`, `web/src/lib/admin-api-guard.ts`, `web/src/app/api/**/route.ts` |
| Supabase 어댑터 | holdings/report_index/runtime_state/storage 접근 + holdings add-buy/YAML replace-all RPC 브리지 | `web/src/lib/supabase-admin.ts` |
| 운영 메트릭 로더 | `report_index.summary` 기반 최근 30-run 운영 건강도 집계 + 패널별 장애 격리 | `web/src/lib/metrics-data.ts`, `web/src/app/(console)/metrics/page.tsx` |
| 실행 트리거 | GitHub workflow_dispatch 호출 | `web/src/lib/github-actions.ts` |
| 티커 디렉토리(웹) | buy 리포트 기반 티커/회사명 캐시 + 검색/최근 후보 제공(증분 갱신) | `web/src/lib/ticker-directory.ts`, `docs/holdings-ticker-lookup.md`, ADR-0008 |
| 배치 워크플로우 | scan/sell 실행, 업로드, 알림, cleanup, 수동 AI Brief artifact 생성, scheduled AI Brief monitor/fallback | `.github/workflows/scan.yml`, `.github/workflows/sell.yml`, `.github/workflows/cleanup.yml`, `.github/workflows/ai-brief.yml` |

## 4. 핵심 플로우

### 4.1 `scan` 플로우

1. `load_config()`로 설정 로드 후 티커 소스를 결합합니다(워치리스트 + 선택적 스크리너).
2. 데이터 제공자(`kis` 또는 `pykrx`)를 초기화하고 환율/휴일 메타를 준비합니다.
3. adjusted 캔들 데이터는 캐시를 먼저 로드해 초기값으로 사용한 뒤, 선택한 provider 경로(`kis` 또는 `pykrx`)로 최신 조회를 시도합니다.
4. `kis` 경로에서는 호출 실패 시 캐시 유지 또는 KR 종목에 한해 PyKRX 폴백을 적용합니다.
5. 선택적으로(`strategy.use_market_regime_filter=true`) 시장별 benchmark 종가가 SMA200 위인지 먼저 확인하고, 레짐이 약세인 시장의 ticker는 평가 전에 제외합니다. benchmark를 못 구하면 `strategy.market_regime_unavailable_policy`에 따라 경고 후 계속 진행하거나(`warn_continue`) 해당 시장을 제외합니다(`block_market`).
6. 시그널 평가 후 후보 티커에 대해서만 raw 캔들을 배치 warmup하고, cache hit 기반으로 `entry_reference_close_raw_value`를 보강한 뒤 후보를 정렬하고 통화/시장 상태 표시를 덧붙입니다. `ema_cross`는 기존 점수/RS/유동성 순서를 유지하고, `sma_ema_hybrid`는 `quality_state`를 먼저 적용한 뒤 같은 tie-breaker를 사용합니다.
7. `reports/YYYY-MM-DD(.n).buy.json`을 원자적으로 기록합니다.
8. 업로드 조건 충족 시(SA: GitHub Actions에서는 필수, 로컬에서는 `SAB_UPLOAD_REPORTS=true`일 때) Supabase Storage 업로드 + `report_index` upsert를 수행합니다. GitHub Actions에서는 인덱스 upsert 실패를 경고로 무시하지 않고 즉시 실패 처리합니다.
9. `scan`은 holdings 파일을 읽지 않습니다. `entry`는 포트폴리오 가드가 설정된 경우 holdings 파일 입력을 읽을 수 있지만, 신호 계산은 buy report 기준을 유지합니다.

### 4.2 `sell` 플로우

1. 보유 종목을 로드해 런타임을 구성합니다(로컬 기본: `holdings.yaml`).
   - `quantity > 0`인 활성 보유분만 sell 평가 대상으로 사용합니다.
   - 로컬 `holdings.yaml`의 선택적 `entry_pattern`은 hybrid sell evaluator에 전달됩니다. 구조화 marker는 exact ID로만 해석하며, failed-breakout marker로 쓰이는 값은 `swing_high_breakout`뿐입니다.
2. KIS/PyKRX로 캔들 데이터를 수집하고 매도/점검 규칙을 평가합니다.
3. `reports/YYYY-MM-DD(.n).sell.json`을 생성하고, 필요 시 Supabase에 업로드합니다.
4. GitHub Actions `sell.yml` 실행 시에는 사전 단계에서 Supabase `holdings`를 읽어 `holdings.generated.yaml`을 만들고 `--holdings` 인자로 주입합니다.
   - Phase A 기준 scheduled export field set은 `entry_pattern`을 아직 선택하지 않습니다. Supabase DB는 런타임 보존 경로가 필드를 소유하기 전까지 non-null `entry_pattern` write를 닫아둡니다.

### 4.3 `entry` 플로우

1. 입력 buy 리포트를 읽고 후보(`candidates[]`)를 시장별로 정규화합니다.
2. 현재 세션 가격 스냅샷을 조회해 종목 단위 `ENTER|REVIEW|SKIP` 액션과 `gap_pct`를 계산합니다. US KIS 해외 `price-detail`은 `PRE_OPEN|INTRADAY`에서 날짜/시각 marker 없이 `last` 계열 가격을 줄 수 있어 `curr`가 있으면 `USD`일 때만 양수 가격 필드를 스냅샷으로 사용하고, KR KIS domestic `price-detail`은 `PRE_OPEN`에서 날짜/시각 계열 스냅샷 marker가 없으면 ambiguous snapshot으로 보고 가격 없음으로 처리합니다.
3. holdings를 읽어 활성 보유 수(`quantity > 0`)를 집계한 뒤, 설정된 포트폴리오 상한이 있으면 최종 `ENTER` 후보에만 포트폴리오 가드를 적용합니다. 전체 보유 상한은 기존 활성 보유를 포함하고, 시장별 신규 진입 상한은 이번 run에서 승인된 신규 진입만 셉니다.
4. `reports/YYYY-MM-DD(.n).entry.json`을 생성합니다.
   - `entry.summary`는 `missing_entry_price_by_reason`과 `entry_price_sources`로 가격 조회 실패 원인과 사용된 가격 소스를 집계합니다.
5. 로컬에서는 `SAB_UPLOAD_REPORTS=true` 또는 명시적 `sab entry --upload`일 때, GitHub Actions에서는 정상/비fatal entry 리포트를 Supabase Storage에 업로드하고 `report_index`를 upsert합니다. fatal missing-price 정책으로 non-zero 종료한 entry 리포트는 이미 로컬에 작성된 진단 artifact로 남으며, 수동 AI Brief workflow가 별도 GitHub artifact로 노출합니다.

### 4.3.1 `ai-brief` 로컬/수동/scheduled workflow 플로우

1. `sab ai-brief --entry-report <path>`가 entry 리포트의 `entries[]`를 읽습니다.
2. `sab/ai_brief_candidates.py`가 각 row를 `recommendable`, `watch_only`, `excluded`로 분류합니다. Base gate(`entry_state=READY`, `entry_price_status=available`)를 통과한 `ENTER`, 포트폴리오 상한 `SKIP`, tight-stop risk-alignment `REVIEW`는 recommendable입니다. `entry_price_status`가 없는 legacy row는 유효한 `entry_price`가 있을 때만 available로 취급합니다. Hybrid trigger guard `SKIP`은 watch-only이며, 나머지는 excluded입니다.
3. 모델 ranking 입력은 recommendable 후보 중 entry report 순서를 보존해 최대 5개로 제한하며, 초과 recommendable 행은 `cap_excluded_candidates[]`로 기록합니다. Watch-only 후보는 ranking 대상이 아니지만 `watch_candidates[]`/`watch_tickers[]`로 모델 provider와 artifact에 분리 전달합니다.
4. source provider는 `none`, `local-json`, `http-json`, `finnhub`, `polygon-news`, `alpha-vantage-news`, `marketaux-news`, `benzinga-news`, `naver-news`를 지원하며, scheduled/환경 경로에서는 comma-separated source provider chain을 사용할 수 있습니다.
   - Chain은 순서대로 provider를 실행하고, 이미 ticker별 source row cap을 채운 ticker를 제외한 남은 ticker만 다음 provider에 요청합니다. Provider별 status/coverage와 final recommendable/watch coverage는 `source_provider_summary`에 남습니다. 중간 provider의 0건/실패는 fallback 뒤에도 source가 없는 ticker에 대해서만 top-level issue로 승격합니다.
   - `local-json`은 로컬 source report의 `sources[]`를 후보 source universe에 붙입니다.
   - `http-json`은 외부 source API에 `schema`, `tickers`, `max_sources_per_ticker`, `freshness_hours`를 POST하고, 응답의 `sources[]`를 같은 계약으로 정규화해 후보 source universe에 붙입니다.
   - `finnhub`은 `FINNHUB_API_KEY`로 Finnhub Company News를 티커별 1회 조회하는 US-only provider입니다. `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 변환하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다.
   - `polygon-news`는 `POLYGON_API_KEY`로 Polygon.io Stocks News endpoint(`https://api.polygon.io/v2/reference/news`)를 티커별 1회 조회하는 US-only provider입니다. `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 변환하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `ticker`, `limit=10`, `order=desc`, `sort=published_utc`로 보내며 API key는 `Authorization: Bearer` header로만 전송합니다.
   - `alpha-vantage-news`는 `ALPHA_VANTAGE_API_KEY`로 Alpha Vantage `NEWS_SENTIMENT` endpoint(`https://www.alphavantage.co/query`)를 티커별 1회 조회하는 US-only provider입니다. `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 변환하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `function=NEWS_SENTIMENT`, `tickers`, `time_from=<now-72h UTC>`, `sort=LATEST`, `limit=10`으로 보냅니다.
   - `marketaux-news`는 `MARKETAUX_API_TOKEN`으로 Marketaux Finance & Market News endpoint(`https://api.marketaux.com/v1/news/all`)를 티커별 1회 조회하는 US-only provider입니다. `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 변환하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `symbols`, `countries=us`, `language=en`, `filter_entities=true`, `must_have_entities=true`, `published_after=<now-72h UTC>`, `limit=10`으로 보냅니다.
   - `benzinga-news`는 `BENZINGA_API_TOKEN`으로 Benzinga News endpoint(`https://api.benzinga.com/api/v2/news`)를 티커별 1회 조회하는 US-only provider입니다. `AAPL.NAS`는 `AAPL`, `BRK.B.NYS`는 `BRK.B`로 변환하고, KR ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다. 요청은 `token`, `tickers`, `pageSize=10`, `displayOutput=headline`, `sort=created:desc`, `publishedSince=<now-72h UTC Unix>`로 보냅니다.
   - `naver-news`는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`로 Naver Search API 뉴스 endpoint(`https://openapi.naver.com/v1/search/news.json`)를 티커별 1회 조회하는 KR-only provider입니다. buy report 회사명을 검색어로 우선 사용하고, 없으면 6자리 ticker를 사용하며, `display=10`, `start=1`, `sort=date`로 요청합니다. US ticker는 요청하지 않은 채 `source_issues[]` WARN으로 남깁니다.
   - `local-json`/`http-json`/`finnhub`/`polygon-news`/`alpha-vantage-news`/`marketaux-news`/`benzinga-news`/`naver-news` source row URL은 HTTP(S), hostname, freshness/future-time, cap 검증을 통과해야 합니다. `local-json`과 source eval은 offline 계약을 지키기 위해 DNS 조회 없이 literal local/private IP와 localhost를 거부하고, live/http 경로(`http-json`, `finnhub`, `polygon-news`, `alpha-vantage-news`, `marketaux-news`, `benzinga-news`, `naver-news`)의 응답 row는 DNS 검증까지 적용해 local/private host를 거부합니다.
   - source row의 ticker가 후보 집합에 없거나 source가 stale/미래 시간/invalid URL이면 source issue로 기록하고 모델 입력에서 제외합니다.
   - `scripts/collect_ai_brief_sources.py`는 RSS/Atom/RDF 로컬 파일 또는 live HTTPS feed URL을 `sab.ai_brief_sources.v1` payload로 변환하는 외부 source API 보조 경로입니다. 로컬 feed 파일은 offline으로 item URL의 literal local/private IP와 localhost만 거부하고, live URL은 HTTPS, userinfo 금지, DNS 기반 local/private host 차단, redirect 거부, 1MB body 제한을 적용합니다. HTTP/timeout/invalid feed는 ticker별 WARN issue로 격리합니다.
   - 수집한 `http-json` 호환 payload는 `scripts/eval_ai_brief_sources.py`로 오프라인 평가하거나, 여러 captured payload를 같은 entry 후보 기준으로 비교할 수 있습니다. `scripts/compare_ai_brief_live_sources.py`는 `http-json`/`finnhub`/`polygon-news`/`alpha-vantage-news`/`marketaux-news`/`benzinga-news`/`naver-news` live provider 결과를 먼저 source payload로 저장한 뒤 같은 evaluator 비교를 실행합니다. provider 실패는 해당 payload의 top-level `ERROR` issue로 격리되어 비교 결과에서 FAIL로 표시되며, provider별 `duration_ms`와 fastest leader를 최종 summary에 남깁니다. Scheduled source provider는 request `--source-provider`, `AI_BRIEF_SOURCE_PROVIDER_CHAIN_<MARKET>`, `AI_BRIEF_SOURCE_PROVIDER_CHAIN`, 시장별/전역 단일 `AI_BRIEF_SOURCE_PROVIDER`, 시장별/전역 `AI_BRIEF_SOURCE_API_URL`, `none` 순서로 fallback합니다. Scheduled runner는 source provider/chain과 API URL origin을 URL 값 없이 구조화 로그로 남기며, unsupported provider/chain이나 `http-json` URL 누락/비 HTTPS/userinfo/local·private literal/invalid port/whitespace-control char는 scan/entry 전에 `source_config_invalid`로 fail-fast합니다.
   - 생성된 `*.ai-brief.json`은 `scripts/eval_ai_brief_recommendations.py`로 recommendable/watch/excluded/cap-excluded entry alignment, summary count consistency, rank continuity, watch contract, source-backed ratio, confidence safety를 오프라인 평가합니다.
5. 모델 provider는 `fake`와 `openai`를 지원합니다.
   - `fake`는 외부 뉴스/API를 호출하지 않는 deterministic contract exerciser입니다.
   - `openai`는 Responses API structured output을 사용하며 timeout/요청 실패/모델 출력 계약 실패 시 추천 없이 `system_issues[]`를 남긴 artifact를 생성합니다.
   - OpenAI 출력 sources는 candidate에 주입된 source URL만 cite할 수 있고, 소스 없는 추천은 ticker별 `source_issues[]`를 요구합니다. `recommendations[].rank`는 배열 순서대로 `1..N` 연속값이어야 하며, 한국어/영어 자동 주문·체결 문구는 계약 오류로 처리합니다. Watch-only 후보는 추천으로 승격할 수 없고 `action=WATCH` row로만 반환됩니다.
6. 최종 추천은 최대 3개이며, 모델이 preselected recommendable 후보를 추천하지 않기로 판단한 경우 `vetoed_candidates[]`에 추천과 별도로 보존합니다. `reports/YYYY-MM-DD(.n).ai-brief.json`은 로컬 파일 락 + 원자적 쓰기로 생성합니다.
7. writer는 새 artifact에 top-level `brief_state`/`brief_reason`을 주입합니다. 상태는 `NO_SIGNAL`, `NEEDS_REVIEW_WATCH_ONLY`, `FINAL_JUDGMENT`, `NEEDS_REVIEW_WEAK_NEWS` 중 하나이며, preselected recommendable count, watch count, recommendation source coverage, source/system issue count만으로 결정합니다.
8. AI Brief recommendation 품질 게이트는 생성 artifact와 source entry report를 함께 평가합니다. 수동 GitHub workflow는 진단 artifact upload 뒤, Telegram/Slack 알림 전 단계에서 실행하고, scheduled runner는 로컬 `ai-brief` path 확정 직후 Storage upload/성공 marker/notification reconciliation 전에 실행합니다. `FAIL`이면 해당 성공 경로를 중단합니다.
9. `notification_text`는 생성된 artifact를 Telegram 본문/Slack key-value 요약 텍스트로 렌더링할 수 있습니다. Telegram은 `NO_SIGNAL`이면 휴식 문구, `NEEDS_REVIEW_WATCH_ONLY`이면 watch-only 재트리거 확인 문구, `FINAL_JUDGMENT`이면 source-backed 후보, `NEEDS_REVIEW_WEAK_NEWS`이면 downgraded copy와 issue 요약을 보여주며, `watch_candidates[]`, `source_provider_summary`, `vetoed_candidates[]`가 있으면 추천과 별도로 표시합니다. Slack 요약은 watch/source chain/veto count를 key-value로 포함합니다.
10. mixed KR/US entry 리포트는 `--market KR|US`를 요구하고, 출력 artifact는 단일 시장만 다룹니다.
11. 로컬에서는 `SAB_UPLOAD_REPORTS=true` 또는 명시적 `sab ai-brief --upload`일 때 Supabase Storage 업로드 + `report_index` upsert를 수행합니다. Scheduled runner는 `sab ai-brief --report-date <sessionDate>`로 artifact date를 session date에 고정한 뒤 직접 AI Brief upload와 marker 기록을 수행합니다.
12. `.github/workflows/ai-brief.yml`의 수동 `workflow_dispatch`는 기존 단일 시장 `scan` → Supabase holdings snapshot → `entry --upload` → `ai-brief --upload` 흐름을 유지합니다. `sab entry`가 fatal missing-price 정책으로 non-zero 종료해도 이미 작성된 entry report는 workflow output과 별도 artifact upload step으로 노출해 진단 가능성을 유지합니다. AI Brief 품질 게이트가 실패하면 생성 artifact는 GitHub artifact로 남지만 알림 전송은 진행하지 않습니다.
13. Scheduled AI Brief primary는 macOS `launchd`가 host wrapper를 실행하고, wrapper가 role window guard 통과 후 one-shot Docker scheduler를 실행하는 구조입니다. Runner는 `runtime_state`에 `attempt`, `lock`, `artifact`, `skip-artifact`, `entry-failure-artifact`, `notification:claim`, `notification:sent`, `success`, `late-alert:*` marker를 기록해 같은 시장/session date 리포트와 알림을 dedupe합니다. `attempt`는 pre-lock 관측 marker이고, artifact/skip/entry-failure/notification/success/late-alert sent marker는 main lock이 필요한 경로에서 소유권을 재확인한 뒤에만 기록합니다. Pipeline runner가 runtime guard에서 중단되면 정상 AI Brief 판단과 섞지 않고 `*.ai-brief-skip.json` artifact(`skip_state=RUNTIME_GUARD_SKIPPED`)를 Storage/`report_index`에 기록합니다. Scheduled AI Brief 품질 게이트가 실패하면 AI Brief Storage upload, artifact marker, success marker, notification reconciliation을 수행하지 않고 pipeline failure로 기록합니다. Scheduled entry 실패 진단은 `DefaultScheduledPipeline`의 typed entry-step failure만 late-alert marker reason `scheduled_entry_failed`로 분리하고, 안전한 기본 `reports/...*.entry.json`은 main lock 소유권과 중복 marker를 확인한 뒤 `entry` artifact로 Storage/`report_index`에 업로드합니다. 업로드 후 marker/late-alert 전에도 main lock 소유권을 다시 확인해 오래된 runner가 성공한 fallback 뒤에 실패 상태를 게시하지 못하게 하고, lock을 잃으면 이미 업로드된 객체의 storage key만 반환하며 canonical runtime marker는 쓰지 않습니다. 소유권이 유지될 때만 `entryReportStorageKey`를 late-alert/state에 남깁니다. DefaultScheduledPipeline이 unsafe path를 만든 경우에는 `unsafe` sentinel을 남기며 업로드하지 않습니다. 외부/원시 wrapper의 문자열 메시지는 scheduled entry 실패로 분류하지 않고, 로그에서만 맥락을 유지하되 unsafe raw path를 `entry_report_path=unsafe`로 축약합니다.
14. GitHub Actions schedule은 US canary 기간에 `early-monitor`, `github-fallback`, `cutoff-alert`만 수행합니다. `resolve_context` job이 dependency-free boundary로 checkout 후 stdlib-only `sab/scheduler/schedule_policy.py`를 import해 cron mapping과 role window 정책으로 market/session_date/schedule_role/runner_role을 산출하고, scheduled job concurrency는 `market + session_date + schedule_role` 기준으로 묶되 cancel은 하지 않습니다. `github-fallback`은 같은 runtime_state lock/artifact marker를 사용하므로 로컬 primary와 동시 실행되어도 새 report 생성은 한 runner만 진행합니다. GitHub queue delay로 `github-fallback`이 명목 08:55 <= t < 09:25 ET window 이후 시작되면 09:29 ET 전까지만 bounded grace로 role guard를 통과시키며, PRE_OPEN/runtime_state guard는 그대로 적용합니다.

### 4.4 웹 리포트 조회 플로우

1. `/api/reports`는 `report_index`에서 목록을 조회합니다.
2. `/api/reports/detail`은 storage key를 검증 후 Storage 원본 JSON을 반환합니다.
3. 서버(`web/src/lib/reports-data.ts`)는 in-memory TTL/LRU 캐시를 사용합니다.
   - 목록: `type/q/limit/searchWindow` 키 기준 단기 TTL(검색 없음 5초, 검색 10초)
   - 상세: `report_key` 기준 장기 TTL(1시간)
4. 클라이언트(`ReportsClient`)는 목록/상세 요청에 in-flight dedupe + 세션 메모리 캐시를 적용합니다.
5. ticker 검색(`q`) 시에는 `report_index`만 페이지 단위로 순회하고, `tickers_hydrated=false` 항목은 결과에서 제외하며 경고를 반환합니다.
6. 검색 중 일부 페이지 조회 실패가 발생하면 이미 수집된 부분 결과를 반환하고 경고를 함께 제공합니다.
7. Report Detail의 buy 후보 근거 표시는 `candidates[].reasons[]`(구조화 근거)를 우선 사용하고, 누락 시 `score_notes`/`pattern_reasons`/`entry_state_reason` 문자열 필드로 폴백합니다.
8. entry 상세는 `entries[]` 전용 표와 `source_buy_report`, `signal_eval_date`, `entry_session_date`(또는 시장별 date map) 메타를 함께 렌더링합니다.
9. AI Brief 상세는 `brief_state`, `brief_reason`, `recommendations[]`, `watch_candidates[]`, `vetoed_candidates[]`, `source_provider_summary`, `source_issues[]`, `system_issues[]`, `source_entry_report`, `model_provider/model_name` 메타를 함께 렌더링합니다. 레거시 artifact에 state/reason이 없으면 상세 화면에서 동일 규칙으로 fallback 추론하고, 새 watch/source chain 필드가 없으면 빈 placeholder를 표시하지 않습니다.

### 4.5 웹 운영 메트릭 대시보드 플로우

1. `/metrics`는 `report_index`에서 `buy`, `sell`, `entry` 최근 30개 row를 타입별로 각각 조회합니다.
2. 집계는 Storage 원본을 다시 읽지 않고 `report_index.summary`만 사용합니다.
3. `buy.summary`는 후보 수 외에 `data_coverage_ratio`, `provider_fallback_ratio`, `rs_benchmark_unavailable_ratio`를 함께 기록합니다.
   각 ratio는 요청 티커 수를 분모로 쓰며, 분모가 0이면 `null`입니다.
4. `sell.summary`는 `data_coverage_ratio`, `provider_fallback_ratio`를 함께 기록합니다.
5. `entry.summary`는 기존 `missing_entry_price_ratio`, `system_issue_count`를 그대로 사용합니다.
6. 오래된 리포트처럼 새 summary 키가 없는 경우 UI는 이를 `0`이 아니라 `N/A`로 표시합니다.
7. 한 타입 조회 실패는 해당 패널만 에러 상태로 렌더링하고, 다른 패널은 계속 표시합니다.

### 4.6 웹 보유종목 CRUD 플로우

1. `/api/holdings`가 cursor 기반 페이지네이션으로 목록을 제공합니다.
2. `/api/holdings` `POST`, `/api/holdings/[ticker]` `PATCH`/`DELETE`로 PostgREST를 통해 `holdings`를 수정합니다.
3. `/api/holdings/[ticker]/add-buy` `POST`는 Supabase RPC(`holdings_add_buy_v1`)를 호출해 추가매수(수량/평단/진입일/통화)를 원자적으로 갱신합니다.
   - `Idempotency-Key`(UUID) 헤더를 필수로 받아 중복 요청 시 기존 결과를 반환합니다(멱등 처리).
   - 동일 키에 서로 다른 payload가 들어오면 `409` 충돌로 차단하며, 멱등 이벤트 로그는 별도 cleanup 함수/스케줄 작업으로 90일 경과 항목(`processed=true` 기준 + 장기 미처리 항목)을 정리합니다.
4. `/api/holdings/yaml` `GET`은 전체 holdings snapshot을 `holdings.yaml`로 export하고, `POST`는 YAML 파싱/검증 후 dry-run 또는 apply를 수행합니다.
   - import apply는 Supabase RPC(`replace_holdings_v1`)로 원자적 replace-all을 수행합니다.
   - export는 `quantity=0` row를 포함한 전체 snapshot을 내보내고, import는 파일에 없는 ticker를 삭제합니다.
   - Phase A의 `entry_pattern` DB 컬럼은 웹 CRUD/YAML API에서 아직 select/accept/export하지 않습니다. non-null marker는 런타임 export/write 경로가 배포될 때까지 DB constraint로 막습니다.
5. (구현, ADR-0008) Holdings 입력 UX는 “회사명/별칭 검색”과 “최근 buy 후보”로 ticker 입력을 보조합니다.
   - 검색/후보 데이터는 buy 리포트(`candidates[].{ticker,name}`)에서 파생한 “티커 디렉토리(캐시)”를 사용합니다.
   - 캐시는 Supabase `runtime_state`에 저장되며 stale 시 증분 갱신합니다.

### 4.7 웹 실행 트리거 플로우

1. `/api/run`은 Zod 스키마와 provider-universe 정책(`pykrx`는 `KR`만 허용)을 검증합니다.
2. GitHub Actions `scan.yml`/`sell.yml`에 `workflow_dispatch`를 발행합니다.
3. ref는 고정 `main`입니다.

## 5. 데이터 저장소

### 5.1 로컬 파일

- `data/`
  - KIS 토큰 캐시(`kis_token_*`)
  - 종목 캔들 캐시(`candles_*`, `candles_overseas_*`)
  - 기타 런타임 캐시
- `reports/`
  - `YYYY-MM-DD(.n).buy.json`
  - `YYYY-MM-DD(.n).sell.json`
  - `YYYY-MM-DD(.n).entry.json`
  - `YYYY-MM-DD(.n).ai-brief.json`
  - `YYYY-MM-DD(.n).ai-brief-skip.json`

### 5.2 Supabase Storage

- 버킷: `reports` (private, JSON MIME 제한)
- 키 규칙: `YYYY/MM/YYYY-MM-DD(.n).{buy|sell|entry|ai-brief|ai-brief-skip}.json`

### 5.3 Supabase Postgres

- `holdings`: 보유 종목 단일 소스(웹 CRUD 대상)
  - 앱과 동일한 ticker 계약을 DB 제약으로 강제합니다(`KR 6자리` 또는 명시 거래소 suffix `.NAS/.NYS/.AMS`).
  - 모호한 `.US` suffix는 DB에서도 허용하지 않으며, 기존 row는 migration 시 수동 정리 대상으로 남깁니다.
  - Phase A는 nullable `entry_pattern` 컬럼과 length/allowlist/active-only constraint를 추가합니다. 웹/scheduled export가 marker를 보존하기 전까지 임시 write-closed constraint(`entry_pattern is null`)가 non-null 저장을 막습니다.
- `report_index`: 리포트 목록 조회 최적화 인덱스(날짜/타입/중복 인덱스 + summary/tickers, `buy|sell|entry|ai-brief|ai-brief-skip`)
  - `summary`는 Reports 목록 요약과 `/metrics` 운영 대시보드의 단일 집계 소스입니다.
  - `buy.summary`: `candidate_count`, `system_issue_count`, `data_requested/covered/missing_count`, `data_coverage_ratio`, `provider_fallback_count/ratio`, `rs_benchmark_requested/unavailable_count`, `rs_benchmark_unavailable_ratio`, `market_regime_unavailable_count`, `market_regime_blocked_count`, `market_regime_blocked_by_market`, `market_regime_unavailable_by_market`
  - `sell.summary`: `evaluated_count`, `issue_count`, `data_requested/covered/missing_count`, `data_coverage_ratio`, `provider_fallback_count/ratio`
  - `entry.summary`: `entry_count`, `system_issue_count`, `missing_entry_price_count`, `missing_entry_price_ratio`, `missing_entry_price_by_reason`, `entry_price_sources`
  - `ai-brief.summary`: `entry_count`, `recommendable_count`, `watch_count`, `preselected_count`, `recommendation_count`, `excluded_count`, `vetoed_count`, `cap_excluded_count`, `source_issue_count`, `system_issue_count`; artifact top-level에는 `brief_state`, `brief_reason`, `eligible_tickers`, `watch_tickers`, `source_provider_summary`가 함께 저장됩니다.
  - `ai-brief-skip.summary`: `skip_state`, `skip_reason`, `session_state`, `expected_state`, `trading_session`; artifact top-level에는 `skip_state`, `skip_reason`, `session_date`, `local_time`, `run_url`이 함께 저장됩니다.
- `runtime_state`: 로그인 시도 제한 상태와 scheduled AI Brief idempotency/lock/notification marker 등 단기 런타임 상태(기본 저장소)
- 예외: `SAB_RUNTIME_STATE_STORE=memory` 또는 테스트 환경(`NODE_ENV=test`)에서는 메모리 저장소를 사용합니다.
- 장애 정책: `SAB_LOGIN_THROTTLE_FAIL_MODE=strict`(기본)에서는 Supabase 장애 시 즉시 실패하고, `degrade`에서만 메모리 스로틀로 폴백합니다.

## 6. 보안 경계

- 관리자 인증
  - 로그인 시 `SAB_BASIC_AUTH_USER/PASS` 검증
  - `SAB_SESSION_SECRET` 기반 HMAC 서명 세션 쿠키(`sab_admin_session`) 발급/검증
- 요청 무결성
  - 보호 API 라우트는 `enforceAdminApiGuard()` 단일 진입점에서 인증 + `same-origin` + 로컬 요청 검증(`host`, `x-forwarded-host`, unsafe의 `origin/referer` 또는 `sec-fetch-site=same-origin`)을 수행
  - 공개 API(`/api/auth/login`, `/api/auth/logout`)는 라우트 내부에서 `same-origin` + 로컬 요청 검증을 수행
  - `middleware.ts`는 페이지 라우트 접근 제어/리다이렉트 전용으로 유지
  - 로컬 요청 강제(`localhost/127.0.0.1/::1`, `SAB_ENFORCE_LOCAL_REQUEST=0` 또는 `NODE_ENV=test`에서 완화)
  - 시작 가드는 `SAB_ALLOW_NON_LOOPBACK_BIND=1` 없는 non-loopback bind를 거부하지만, 이 가드는 원격 노출에 대한 완전한 보안 경계가 아니라 로컬 운영 가정의 fail-fast 보조 장치입니다.
- 비밀키 보호
  - Supabase/GitHub 키는 서버 코드(`server-only`)에서만 사용
  - publishable key(`sb_publishable_*`)는 서버 경로에서 거부
- DB 접근 제어
  - `holdings`, `report_index`, `runtime_state`는 RLS 강제 + `anon`/`authenticated` 권한 제거

## 7. 신뢰성/복구 설계

- 설정/입력 Fail-Closed
  - YAML 파싱 실패, 중복 YAML key, 잘못된 루트 타입, 필수 설정 누락 시 즉시 실패
  - `kis.app_key`/`kis.app_secret`를 YAML에 저장하면 보안 정책 위반으로 실패
  - `GITHUB_ACTIONS=true`(또는 `CI=true`)에서는 strict config parsing을 강제 적용하며, 숫자/enum 오입력은 기본값으로 회귀하지 않고 즉시 실패
  - 로컬 운영에서도 `SAB_CONFIG_STRICT=true`를 설정하면 동일한 strict parsing 정책을 강제
- 데이터 수집 내구성
  - KIS 재시도/백오프/토큰 재발급 처리
  - KR 심볼은 KIS 실패 시 PyKRX 폴백 가능(US는 폴백 없음)
  - 캐시가 있으면 API 실패 시 캐시 데이터로 계속 진행
  - 캔들 캐시는 저장 전/재사용 전 `date/open/high/low/close/volume` finite 검증을 거쳐 오염 row를 제거합니다.
  - `holidays_us.json`은 파일 `mtime` 기준 12시간 TTL 내에는 재호출하지 않고 재사용합니다.
  - 부분 수집 누락 시 coverage(`수집성공/평가대상`)가 `0.70` 이상이면 경고로 계속 진행, `0.70` 미만이면 실패 처리
- 산출물 안정성
  - 리포트는 파일 락 + 원자적 쓰기로 기록
  - 중복 파일명은 suffix(`-1`, `-2`, ...)로 충돌 회피
  - Supabase 업로드도 duplicate index를 순차 탐색해 충돌 회피
  - GitHub Actions 실행에서는 Storage 업로드 또는 `report_index` upsert 실패 시 run을 실패 처리(fail-closed)
- 운영 자동화
  - `cleanup.yml`이 보관기간 초과 리포트를 정리
  - schedule 실행에서만 알림(텔레그램/슬랙) 전송
  - scheduled AI Brief는 로컬 Docker primary가 Telegram delivery를 성공해야 `success` marker를 기록합니다. Slack은 secret이 있을 때 best-effort입니다.

## 8. 설정 계층

- 현재 구현 기준
  - CLI 오버라이드: 일부 필드(`provider`, `limit`, `watchlist`, `universe`, `screener-limit`)
    - `limit`은 워치리스트/스크리너 병합 이후 최종 평가 ticker cap으로 적용
  - 환경변수/`.env` 우선
  - `config.yaml` 기본값
- 운영 정책
  - 시크릿은 `.env`/환경변수로 관리
  - `config.yaml`은 비시크릿 기본값 중심

## 9. 제약과 트레이드오프

- 단일 사용자/로컬 중심 설계이며 멀티유저 권한 모델은 범위 밖입니다.
- Python 엔진은 직접 Supabase `holdings`를 읽지 않고, 워크플로우 단계에서 파일 입력으로 브리지합니다.
  - `scan`은 holdings 비의존 경로를 유지합니다.
  - `entry`는 포트폴리오 가드 적용을 위해 holdings 파일 입력을 읽을 수 있지만, 종목 신호 계산은 buy report 기준을 유지합니다.
  - `sell`은 holdings 파일 입력을 요구합니다.
- `workflow_dispatch` 실행 ref를 `main`에 고정해 운영 단순성을 우선합니다.
- Entry 파이프라인(`entry`)은 로컬 JSON 리포트(`*.entry.json`)를 생성하고, Storage/`report_index`/웹 Reports UI와 연동됩니다.
  - 단, 웹 `Run` 탭과 GitHub Actions workflow는 standalone `entry` 전용 실행 트리거를 아직 제공하지 않습니다. `ai-brief.yml`은 내부 단계로 `entry`를 실행합니다.
  - buy report candidate는 adjusted 신호 필드와 함께 동일 `eval_date`의 raw entry reference close를 포함하며, 이 raw 기준가는 `scan`의 후보 전용 배치 warmup으로 준비됩니다.
  - `entry`는 이 raw reference와 실시간/raw snapshot만 비교한 뒤, 필요 시 포트폴리오 가드를 후속 적용합니다.
  - mixed KR/US buy report는 시장별로 분리 평가하며, entry artifact는 `market="MIXED"`와 시장별 날짜 메타(`signal_eval_date_by_market`, `entry_session_date_by_market`)를 함께 기록합니다.
- AI Brief 파이프라인(`ai-brief`)은 entry artifact의 후속 로컬 소비자입니다.
  - 후보를 새로 발굴하지 않고 entry row를 recommendable/watch-only/excluded 역할로 재분류합니다. Recommendable 후보는 `ENTER`, 포트폴리오 cap `SKIP`, tight-stop risk-alignment `REVIEW` 중 base gate를 통과한 row이고, watch-only 후보는 hybrid trigger guard `SKIP`입니다.
  - `fake` provider는 외부 기사/모델 판단을 포함하지 않습니다.
  - `openai` provider는 OpenAI Responses API로 모델 판단을 수행하지만, 후보 ticker를 추가하거나 watch-only/excluded 행을 추천으로 승격할 수 없습니다.
  - `local-json` source provider는 로컬 source report를 모델 입력 context로 붙이지만, 후보 ticker를 추가할 수 없습니다.
  - `http-json` source provider는 외부 source API를 호출하지만, 반환 row도 동일한 ticker universe/freshness/future-time/HTTP(S) URL/local-private host/cap 검증을 통과해야 모델 입력에 들어갑니다.
  - `finnhub` source provider는 `FINNHUB_API_KEY`로 Finnhub Company News를 직접 조회하지만, US ticker만 요청하고 반환 row도 동일한 freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과해야 모델 입력에 들어갑니다.
  - `polygon-news` source provider는 `POLYGON_API_KEY`로 Polygon.io Stocks News를 직접 조회하지만, US ticker만 요청하고 반환 row도 동일한 freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과해야 모델 입력에 들어갑니다.
  - `alpha-vantage-news` source provider는 `ALPHA_VANTAGE_API_KEY`로 Alpha Vantage `NEWS_SENTIMENT`를 직접 조회하지만, US ticker만 요청하고 반환 row도 동일한 freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과해야 모델 입력에 들어갑니다.
  - `marketaux-news` source provider는 `MARKETAUX_API_TOKEN`으로 Marketaux Finance & Market News를 직접 조회하지만, US ticker만 요청하고 반환 row도 동일한 freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과해야 모델 입력에 들어갑니다.
  - `benzinga-news` source provider는 `BENZINGA_API_TOKEN`으로 Benzinga News를 직접 조회하지만, US ticker만 요청하고 반환 row도 동일한 freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과해야 모델 입력에 들어갑니다.
  - `naver-news` source provider는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`로 Naver Search API 뉴스를 직접 조회하지만, KR ticker만 요청하고 반환 row도 동일한 freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과해야 모델 입력에 들어갑니다.
  - RSS/Atom/RDF 로컬 파일/live HTTPS feed 변환 도구, source eval 비교 모드, live provider comparison runner는 source API payload 제작/검증을 위한 보조 경로이며, runtime provider 종류를 늘리지 않습니다.
  - recommendation eval은 생성된 AI Brief artifact의 품질 게이트이며, runtime provider나 매매 신호를 추가하지 않습니다. 수동 GitHub workflow와 scheduled runner에서는 실패 시 정상 알림/성공 marker로 진행하지 않습니다.
  - 모델 출력에 소스가 없으면 ticker별 source issue로 disclose해야 합니다.
  - 생성된 `*.ai-brief.json`은 Storage, `report_index`, 웹 Reports UI와 연동됩니다.
  - 로컬 `notification_text` builder와 `ai-brief.yml` preview 단계는 `ai-brief` artifact를 Telegram/Slack 텍스트로 렌더링합니다. Scheduled path는 runtime_state notification sent marker로 Telegram 중복을 줄이고, artifact만 있고 sent marker가 없으면 report를 재생성하지 않고 notification reconciliation을 수행합니다.

## 10. 관련 문서

- 제품 방향/backlog: `docs/PRD.md`
- 현재 계약(contract): `docs/spec-v1.1.md`
- 백로그/전달 이력: `docs/spec-v1.3.md`
- 운영: `docs/runbook.md`, `docs/kis-setup.md`
- 보유종목 데이터: `docs/holdings-schema.md`, `docs/holdings-add-buy.md`, `docs/holdings-ticker-lookup.md`
- 의사결정 기록: `docs/ai-brief-us-source-provider-decision.md`
- ADR: `docs/adr/README.md`
  - 베이스라인: `docs/adr/ADR-0007-v1.1-current-architecture-baseline.md`
  - 보유종목 디렉터리: `docs/adr/ADR-0008-holdings-ticker-directory.md`
  - 웹 리포트 캐싱: `docs/adr/ADR-0009-web-reports-caching.md`
  - Add Buy 멱등성: `docs/adr/ADR-0010-holdings-add-buy.md`
  - 시세 캐시 정책: `docs/adr/ADR-0011-market-data-cache-policy.md`
  - 로컬 Docker scheduled runs: `docs/adr/ADR-0012-local-docker-scheduled-runs.md`
- 전략/로직 설계(신호/리스크): `docs/STRATEGY.md`
