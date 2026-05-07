# Swing Trading Report (KR, On-Demand)

상태: Accepted (프로젝트 진입점)

간단한 스윙 스크리닝을 원할 때만 실행하고, 결과를 **JSON 리포트**로 저장한 뒤 **로컬 웹(Next.js)** 에서 열람하는 개인용 프로젝트입니다. 데이터 소스는 기본적으로 한국투자증권 KIS Developers(Open API)를 사용하며, 국내(KR) 기본 + (선택) 해외(US)까지 확장 가능합니다. 프로젝트/의존성 관리는 uv를 사용합니다.

권장 구성(개인용):

- 로컬 UI: Next.js(로컬 Docker)
- 데이터: Supabase(Postgres/Storage) - 보유 목록/리포트/실행 이력
- 자동 실행: GitHub Actions `schedule` (자동 실행일 때만 알림 전송)
  - 텔레그램: 리포트 본문(매수 후보/매도·점검 후보) 전송
  - 슬랙: 기존 요약 포맷 유지

로컬 Supabase는 idle Docker CPU/메모리를 줄이기 위해 `realtime`, `studio`, `inbucket`, `analytics`를 기본 비활성화한 최소 프로필을 사용합니다. Studio/Realtime/메일 테스트가 필요한 디버깅 세션에서만 `supabase/config.toml`의 해당 `enabled` 값을 일시적으로 `true`로 바꿔 사용하세요.

상세 문서 인덱스는 [docs/README.md](docs/README.md), 배경/요구사항은 [docs/PRD.md](docs/PRD.md)를 참고하세요.

## 한눈에 보기

- `sab scan`: KR/US 후보를 수집하고 buy 리포트를 생성합니다.
- `sab sell`: 보유 종목을 매도/점검 규칙으로 평가합니다.
- `sab entry`: buy 리포트 후보를 다음 세션 진입 관점으로 재평가합니다.
- `sab ai-brief`: entry 리포트의 `ENTER` 후보를 로컬 AI brief로 요약합니다.
- 결과물: `reports/YYYY-MM-DD(-n).{buy|sell|entry}.json`, `reports/YYYY-MM-DD(-n).ai-brief.json`
- GitHub Actions: `scan.yml`/`sell.yml` 자동·수동 실행, `ai-brief.yml` 수동·scheduled artifact 생성 + 알림 발송
- 로컬 UI: `docker compose up -d --build web` 후 `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)

## Requirements

- 필수: Python 3.14+, uv
- 필수(웹 UI 로컬 배포): Docker Desktop
- 선택: just (`justfile` 레시피 실행)
- 선택: direnv (프로젝트 진입 시 로컬 환경변수 자동 적용)
- 선택(웹 UI를 호스트에서 직접 실행할 때): Node.js + pnpm
  - 권장: `mise` 설치 후 `mise install` (`mise.toml`/`mise.lock` 기준)
  - 권장: 셸 활성화(`eval "$(mise activate zsh)"`) 또는 명령 실행 시 `mise x -- <cmd>` 사용

## Quickstart (uv 기반)

### 1. 도구/의존성 준비

- uv 설치(macOS)
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - 확인: `uv --version`
- 기본(슬림) 프로파일: `UV_CACHE_DIR=.uv-cache uv sync`
- 개발 의존성 포함: `UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- 반복 실행용 레시피 목록: `just --list`
- 도구체인(Node/pnpm) 동기화: `mise install` (`mise.lock`이 함께 커밋되어 있어야 재현성 보장)
- lockfile 갱신(도구 버전 변경 시): `mise lock --platform linux-x64,macos-arm64 && mise install`
- `.env` 자동 로딩은 기본 내장 파서로 동작합니다(추가 의존성 불필요).
- 선택 extras:
  - `python-dotenv` 고급 파싱: `UV_CACHE_DIR=.uv-cache uv sync --extra dotenv`
  - 거래소 휴장일 자동 캘린더: `UV_CACHE_DIR=.uv-cache uv sync --extra calendar`
  - PyKRX 데이터 제공자/폴백: `UV_CACHE_DIR=.uv-cache uv sync --extra pykrx`
  - 전체 기능: `UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups`
  - 잠금 갱신: `UV_CACHE_DIR=.uv-cache uv lock` (업그레이드: `UV_CACHE_DIR=.uv-cache uv lock --upgrade`)
- direnv 사용 시(선택):
  - zsh 훅 추가: `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc`
  - 프로젝트 최초 1회: `direnv allow .`
  - 기본값은 `.envrc`에서 관리(`UV_CACHE_DIR`, `PRE_COMMIT_HOME`), 머신별 오버라이드는 `.envrc.local` 사용(`.envrc.local.example` 참고)
  - `.env`는 direnv가 아니라 애플리케이션(`sab`)이 로드합니다.

### 2. 설정 파일 원칙과 `.env`

- 원칙:
  - `.env`는 **시크릿/환경별 값만** 둡니다(커밋 금지).
  - 비시크릿 설정은 `config.yaml`로 관리합니다(샘플: `config.example.yaml`).
  - `config.yaml`과 `.env`에 **동일 키를 중복 정의하지 않습니다**(충돌 시 실패).
  - 로컬 전용 설정이 필요하면 `config.local.yaml`을 만들고 `SAB_CONFIG=config.local.yaml`로 지정하세요(파일은 커밋하지 않기).
- 최소 예시(필수):
  - `KIS_APP_KEY=...`
  - `KIS_APP_SECRET=...`
- 웹 UI 추가(필수):
  - `SUPABASE_URL=...`
  - `SUPABASE_SECRET_KEY=...` (또는 `SUPABASE_SERVICE_ROLE_KEY=...`)
  - `SAB_BASIC_AUTH_USER=...`, `SAB_BASIC_AUTH_PASS=...`, `SAB_SESSION_SECRET=...`
- 선택(로컬 운영 편의):
  - `LOG_LEVEL=INFO`
- 선택(AI Brief OpenAI provider; scheduled AI Brief는 이 설정 필요):
  - `OPENAI_API_KEY=...`
  - `OPENAI_AI_BRIEF_MODEL=...` (또는 CLI `--model-name`)
  - `AI_BRIEF_MODEL_TIMEOUT_SECONDS=20`
- 선택(AI Brief 외부 source API provider):
  - `AI_BRIEF_SOURCE_API_URL=...`
  - `AI_BRIEF_SOURCE_API_TOKEN=...` (실행 URL이 `AI_BRIEF_SOURCE_API_URL` 변수와 일치할 때만 Bearer 토큰으로 전송)
  - `AI_BRIEF_SOURCE_TIMEOUT_SECONDS=10`
- 전체 키 목록/설명은 `.env.example`을 참고하세요.

### 3. 핵심 실행

- 기본 실행: `UV_CACHE_DIR=.uv-cache uv run -m sab scan`
- 평가 상한 지정(워치리스트+스크리너 병합 후 최종 cap): `UV_CACHE_DIR=.uv-cache uv run -m sab scan --limit 30`
- 스크리너 상위 N 조정(KR/US 공통): `UV_CACHE_DIR=.uv-cache uv run -m sab scan --screener-limit 15`
- 유니버스 선택: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe watchlist` (옵션: `watchlist`, `screener`, `both`)
- 워치리스트 지정: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --watchlist watchlist.txt`
- 보유 평가: `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
- 진입 평가: `UV_CACHE_DIR=.uv-cache uv run -m sab entry`
- AI 진입 브리프: `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json`
- OpenAI 모델 브리프(선택): `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json --model-provider openai --model-name <openai-model>`
- 로컬 source 포함 브리프(선택): `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json --source-provider local-json --source-report reports/YYYY-MM-DD.sources.json`
- 외부 source API 포함 브리프(선택): `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json --source-provider http-json --source-api-url https://source.example/api`
- RSS/Atom/RDF 캡처 source payload 생성(개발용): `UV_CACHE_DIR=.uv-cache uv run python scripts/collect_ai_brief_sources.py --feed-catalog feeds.json --output reports/YYYY-MM-DD.sources.json`
- 캡처한 source payload 오프라인 품질 평가(개발용): `UV_CACHE_DIR=.uv-cache uv run python scripts/eval_ai_brief_sources.py --entry-report reports/YYYY-MM-DD.entry.json --source-report reports/YYYY-MM-DD.sources.json`
- KIS 장애 시 PyKRX 폴백이 필요하면: `UV_CACHE_DIR=.uv-cache uv sync --extra pykrx`

### 4. 웹 UI 빠른 시작

- `.env`에 Supabase/로그인 설정 후 `docker compose up -d --build web`
- 접속: `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
- 로컬 CLI 실행 결과도 웹에서 보고 싶다면 `.env`에 `SAB_UPLOAD_REPORTS=true`를 설정하세요(Supabase 설정 필요).
- `sab entry`만 즉시 업로드하고 싶다면 `UV_CACHE_DIR=.uv-cache uv run -m sab entry --upload`를 사용할 수 있습니다.
- `sab ai-brief`만 즉시 업로드하고 싶다면 `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json --upload`를 사용할 수 있습니다.

### 5. 리포트 아티팩트

- Buy: `reports/YYYY-MM-DD(-n).buy.json`
- Sell/Review: `reports/YYYY-MM-DD(-n).sell.json`
- Entry: `reports/YYYY-MM-DD(-n).entry.json`
- AI Brief: `reports/YYYY-MM-DD(-n).ai-brief.json`
- 웹 대시보드는 Supabase Storage(`SUPABASE_REPORTS_BUCKET`, 기본값 `reports`)의 JSON을 렌더링합니다.
  - 업로드는 GitHub Actions에서 기본 수행하고, 로컬에서는 `SAB_UPLOAD_REPORTS=true`일 때 수행합니다.
  - `entry`는 `--upload`로 1회성 업로드를 강제할 수 있으며, 업로드 시 `report_index`까지 함께 갱신합니다.
  - `ai-brief`도 `--upload`로 1회성 업로드를 강제할 수 있으며, 업로드 시 `report_index`까지 함께 갱신합니다.
  - `ai-brief.yml` workflow에서는 buy/entry/ai-brief JSON과 알림 preview 텍스트를 Actions artifact로 남기고, AI Brief 리포트도 Supabase Storage/report_index에 업로드합니다.
  - 수동 `ai-brief.yml` 실행은 `send_notifications=true`를 선택했을 때만 Telegram/Slack으로 실제 발송합니다. 기본값은 `false`입니다.
  - scheduled `ai-brief.yml` 실행은 KR/US 장전 schedule과 런타임 가드를 사용하며, 장일+PRE_OPEN일 때만 scan/entry/ai-brief와 알림 발송을 진행합니다.

## 실행/입력 정책

- 워치리스트 티커 정책(fail-closed):
  - KR은 6자리 숫자 코드만 허용(예: `005930`)
  - US는 명시 거래소 suffix 필수(예: `AAPL.NAS`, `IBM.NYS`, `SPY.AMS`)
  - US 클래스 티커는 `BASE.CLASS.EXCH`를 캐노니컬로 사용(예: `BRK.B.NYS`), `BRK/B.NYS` 입력은 허용하되 내부에서 `BRK.B.NYS`로 정규화
  - `AAPL`(bare), `.US`(모호 suffix), 미지원 suffix(`AAPL.XNAS`)는 즉시 실패
  - Supabase `holdings`도 동일 계약을 강제하며, 기존 `.US` row가 있으면 관련 migration은 수동 정리 전까지 실패
- 유니버스별 watchlist 로드 정책:
  - `--universe screener`: watchlist 파일을 로드/검증하지 않음
  - `--universe watchlist|both`: watchlist를 로드하며, 파일 누락/티커 검증 실패 시 즉시 실패
- `sab entry` 입력 정책:
  - mixed KR/US buy 리포트도 시장별로 나눠 한 번에 평가합니다.
  - 특정 시장만 평가하려면 `UV_CACHE_DIR=.uv-cache uv run -m sab entry --market US`처럼 지정합니다.
  - 치명 열화 임계치(선택): `ENTRY_FATAL_MISSING_PRICE_RATIO` (기본 `1.0`)
    - `entry_price`가 비어 있는 행 비율이 임계치 이상이면 `sab entry`는 `exit 1`로 종료
    - `0.0`은 "누락이 1건이라도 있으면 실패" 정책으로 해석
- `sab ai-brief` 입력 정책:
  - `--entry-report`는 필수이며, `entries[].action == "ENTER"`인 행만 추천 후보가 됩니다.
  - mixed KR/US entry 리포트에는 `--market KR|US`를 반드시 지정해야 합니다.
  - `--buy-report`는 회사명/기존 buy 근거 보강용이며, entry report에 없는 ticker를 추가하지 않습니다.
  - `--model-provider fake`는 외부 뉴스/API를 호출하지 않고 낮은 confidence와 source issue를 남기는 계약 테스트용 provider입니다.
  - `--model-provider openai`는 OpenAI Responses API를 호출하며, `OPENAI_API_KEY`와 실제 `--model-name` 또는 `OPENAI_AI_BRIEF_MODEL`이 필요합니다.
  - `--source-provider local-json --source-report <path>`는 로컬 JSON source report를 후보별 source context로 주입합니다. source report는 `sources[]` row에 `ticker`, `title`, HTTP(S) `url`, offset 포함 `published_at`을 포함해야 하며, source 시간은 72시간 이내이고 15분 넘는 미래 시간이면 무시됩니다.
  - `--source-provider http-json --source-api-url <url>`는 외부 source API에 `{"schema":"sab.ai_brief_source_request.v1","tickers":[...],"max_sources_per_ticker":3,"freshness_hours":72}`를 POST하고, 응답의 `sources[]` row를 같은 계약으로 정규화해 후보별 source context로 주입합니다. URL은 HTTPS여야 하며 local/private host는 거부합니다. URL은 `AI_BRIEF_SOURCE_API_URL`, timeout은 `AI_BRIEF_SOURCE_TIMEOUT_SECONDS`로도 설정할 수 있으며, `AI_BRIEF_SOURCE_API_TOKEN`은 실행 URL이 `AI_BRIEF_SOURCE_API_URL`과 정확히 일치할 때만 Bearer 토큰으로 전송합니다.
  - `scripts/collect_ai_brief_sources.py --feed-catalog <path>`는 RSS/Atom/RDF 캡처 파일을 `sab.ai_brief_sources.v1` 호환 payload로 변환하는 source API 보조 도구입니다. live network 호출이나 벤더 SDK 없이 `sources[]`를 만들고, 생성 결과는 `local-json` 주입 또는 `ai-brief-source-eval` 검증에 사용할 수 있습니다.
  - source provider는 entry report의 `ENTER` 후보를 추가할 수 없고, preselection에 포함되지 않은 ticker source는 `source_issues[]`로 기록한 뒤 무시합니다.
  - source provider timeout/HTTP/JSON 실패는 실행을 중단하지 않고 `system_issues[]`에 남긴 뒤 source 없는 artifact를 생성합니다.
  - OpenAI provider timeout/응답 계약 실패는 주문 추천 없이 빈 `recommendations[]`와 `system_issues[]`를 남기는 로컬 artifact로 기록합니다.
  - OpenAI provider는 candidate에 주입된 source URL만 cite할 수 있으며, 소스가 없는 추천은 ticker별 `source_issues[]`를 반드시 남겨야 합니다.

## 웹 UI 운영 참고

- 기본 운영 기준: `web` 서비스는 이미지 빌드 시 `pnpm run build`를 수행하고, 런타임 엔트리는 `pnpm run start`만 실행합니다.
- 로컬 Supabase는 idle 리소스 절감을 위해 `realtime`, `studio`, `inbucket`, `analytics`를 기본 비활성화한 최소 프로필을 사용합니다.

### 실행 명령

- 전환 직후 1회 정리: `docker compose down --remove-orphans && docker compose up -d --build web`
- 일반 재기동: `docker compose up -d --build web`
- 개발 모드(HMR): `docker compose --profile dev up -d --build web-dev`
- 개발 모드 중지: `docker compose stop web-dev`
- 강제 재생성(문제 시): `docker compose stop web && docker compose rm -f web && docker compose up -d --build web`
- 로그(prod): `docker compose logs -f web`
- 로그(dev): `docker compose --profile dev logs -f web-dev`
- 중지(prod): `docker compose stop web`
- 접속(prod): `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
- 접속(dev): `http://localhost:${WEB_DEV_HOST_PORT}` (기본값 `55301`)
- 포트 변경(prod): `.env`에 `WEB_HOST_PORT=55444` 설정 후 `docker compose up -d --build web`
- 포트 변경(dev): `.env`에 `WEB_DEV_HOST_PORT=55445` 설정 후 `docker compose --profile dev up -d --build web-dev`

### 직접 실행/바인딩 정책

- 직접 실행(선택): `cd web && pnpm install && pnpm run dev`
- 직접 실행 기본 바인딩: `WEB_BIND_HOST` 미지정 시 `127.0.0.1`
- 직접 실행에서 `SAB_ENFORCE_LOCAL_REQUEST=0`와 non-loopback bind(`0.0.0.0`, 사설 IP 등)를 함께 쓰면 시작 단계에서 차단됩니다.
- Docker Compose는 컨테이너 내부 `0.0.0.0` bind를 쓰더라도 호스트 publish가 `127.0.0.1:${WEB_HOST_PORT}:3000`이면 지원 경로입니다.
- 직접 실행 시 Node 버전은 `web/Dockerfile`/`web/Dockerfile.dev`의 `FROM node:<version>`과 동일하게 맞춥니다.
- 웹 패키지 매니저: `pnpm` (고정)

### 기능 및 보호 경계

- `Reports`
  - 리포트 목록/상세/타입 필터(`buy`/`sell`/`entry`/`ai-brief`)/ticker substring 검색
  - 검색 범위 정책: 서버 환경변수 `REPORT_SEARCH_WINDOW` (기본 100, 최소 10, 최대 1000)
  - 런타임 상태 저장소: `SAB_RUNTIME_STATE_STORE` (`supabase`/`memory`, 기본은 테스트 외 `supabase`)
  - 로그인 스로틀 장애 정책: `SAB_LOGIN_THROTTLE_FAIL_MODE` (`degrade`/`strict`, 기본 `strict`)
  - 응답의 `truncated=true`는 "정책상 검색 대상이 잘려 더 오래된 리포트는 미검색"을 의미
  - 보호 경계: `/api/reports` 및 `/api/reports/detail`은 관리자 세션 인증(`requireAdminAuth`) + same-origin 검증을 필수로 요구
- `Holdings`
  - Supabase `holdings` CRUD
  - 보호 경계: `/api/holdings` 및 `/api/holdings/[ticker]`는 관리자 세션 인증 + same-origin 검증을 필수로 요구
  - 목록 조회: cursor 기반 페이지네이션(`limit`, `cursor`) + UI `Load more`
  - 추가매수(`POST /api/holdings/[ticker]/add-buy`): `Idempotency-Key`(UUID) 헤더 필수, 동일 키 재시도 시 기존 결과 반환, 동일 키-다른 payload는 `409` 충돌 처리
  - `sell` 평가는 `quantity > 0` 활성 보유분만 대상으로 처리
- `Run`
  - `scan.yml`/`sell.yml` `workflow_dispatch` 트리거
  - 기능 플래그: `RUN_DISPATCH_ENABLED=1`에서 활성화(하위 호환: 플래그 미설정 + `GITHUB_OWNER/GITHUB_REPO/GITHUB_PAT` 모두 설정 시 자동 활성)
  - 보호 경계: `/api/run`은 관리자 세션 인증 + same-origin 검증을 필수로 요구, 실행 ref는 `main`으로 고정
  - `scan` 실행 입력 정책: `provider=pykrx`는 `universe=KR`에서만 지원
  - `scan`에서 `provider=pykrx`를 사용할 때는 `watchlist.txt`(또는 `WATCHLIST_FILE`/`files.watchlist`)가 비어 있지 않아야 함
  - `scan`에서 `provider=pykrx` + `universe=US|both` 조합은 입력 검증 단계에서 실패하도록 설계
  - 기본 하드닝: 로컬 요청 검사는 기본 활성(`Host` + `x-forwarded-host` 일관성, unsafe 메서드는 `origin/referer` 로컬성 또는 `sec-fetch-site=same-origin` 요구), `SAB_ENFORCE_LOCAL_REQUEST=0`에서만 비활성화 (`/api/auth/`*, `/api/holdings*`, `/api/reports*`, `/api/run`)
  - 시작 가드: direct bind가 loopback 밖으로 열려 있고 동시에 `SAB_ENFORCE_LOCAL_REQUEST=0`이면 서버는 시작하지 않습니다.
  - 운영 가정: 당분간 웹은 `localhost/127.0.0.1` 단일 사용자 노출만 지원하며, local-request 가드는 원격 노출의 완전한 보안 경계로 간주하지 않습니다.

## CLI 서브커맨드

`python -m sab` CLI는 아래 서브커맨드를 제공합니다.

| 실행 예 | 설명 |
| --- | --- |
| `UV_CACHE_DIR=.uv-cache uv run -m sab scan` | 후보 수집/평가 후 JSON 리포트 생성 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab sell` | 보유 종목을 매도/점검 규칙으로 평가 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab entry` | buy 리포트 후보를 다음 세션 진입 관점으로 평가 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report <path>` | entry 리포트의 `ENTER` 후보를 로컬 AI brief로 요약 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report <path> --model-provider openai --model-name <model>` | OpenAI Responses API로 로컬 AI brief 생성 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report <path> --source-provider local-json --source-report <path>` | 로컬 JSON source context를 포함해 AI brief 생성 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab ai-brief --entry-report <path> --source-provider http-json --source-api-url <url>` | 외부 JSON source API context를 포함해 AI brief 생성 |
| `UV_CACHE_DIR=.uv-cache uv run python scripts/collect_ai_brief_sources.py --feed-catalog <path>` | RSS/Atom/RDF 캡처 feed를 AI Brief source payload로 변환 |
| `UV_CACHE_DIR=.uv-cache uv run python scripts/eval_ai_brief_sources.py --entry-report <path> --source-report <path>` | 캡처한 AI Brief source payload 품질 평가 |

## 작업 자동화 (just + direnv)

- 기본 레시피 목록: `just --list`
- 대표 명령:
  - `just scan`
  - `just sell`
  - `just entry`
  - `just ai-brief-source-collect --feed-catalog feeds.json --output captured.sources.json`
  - `just ai-brief-source-eval --entry-report reports/YYYY-MM-DD.entry.json --source-report captured.sources.json`
  - `just quality` (ruff + format-check + mypy + pytest)
  - `just check` (`just quality` 별칭 호환)
  - `just precommit-all`
  - `just ci-python`
  - `just ci-web` (web install + lint + format-check + typecheck + test:coverage + build, 비밀 없는 고정 CI placeholder env 사용)
- 레시피에 CLI 인자 전달:
  - 예시: `just scan --universe both --screener-limit 20`
- direnv 사용 시:
  - `.envrc`는 비시크릿 기본값/도구 캐시 변수만 관리
  - 시크릿/개인 오버라이드는 `.envrc.local`(git ignore)로 분리
  - `.envrc` 변경 시 `direnv allow .`를 다시 실행

## 파일/폴더 구조

- `sab/` - Python 애플리케이션 코드
  - `__main__.py` - CLI 엔트리(`sab scan` / `sab sell` / `sab entry` / `sab ai-brief`)
  - `data/` - KIS/PyKRX 커넥터, 캐시
  - `signals/` - EMA/RSI/ATR 계산
  - `report/` - 리포트 아티팩트(JSON) 생성
- `web/` - Next.js 로컬 대시보드(App Router + Route Handler)
- `reports/` - 생성된 JSON 리포트 아티팩트 출력 폴더
- `scripts/` - 개발/운영 보조 스크립트(`collect_ai_brief_sources.py`, `eval_ai_brief_sources.py`)
- `data/` - 캐시/상태(현재 JSON, 추후 SQLite 고려)
- `docs/README.md` - 문서 인덱스(진입점)
  - `docs/adr/README.md` - ADR 인덱스
  - `docs/reviews/README.md` - 리뷰 인덱스
- `supabase/` - Supabase 마이그레이션/설정
- `holdings.yaml` - 선택 백업 파일(import/export 용도, 웹 UI에서 내보내기/가져오기 가능)

## 전략(요약)

- 상세 계약/모드별 규칙: `docs/STRATEGY.md`
- 코어: EMA20/50 골든크로스 + RSI14 30 상향 재돌파(+ RSI<70)
- 장기 필터(옵션): 가격/EMA20/EMA50 모두 SMA200 위
- 갭 필터: ATR 기반(|갭| <= ATR×배수 / 전일종가), 기본 배수 1.0 권장
- 품질: 최소 거래대금(최근 20일 평균), 신규상장/저유동 제외, ETF/ETN/레버리지 제외 옵션
- 품질 보강: EMA20/50 기울기>0, 신호일 종가가 두 EMA 위
- 리스크: ATR14 기반 손절/타깃(~1:2)
- 점수화: 추세/기울기/모멘텀/유동성/변동성 가중 합산으로 후보 정렬

### 리더(선도주) 중심 보완

- 스크리너 단계에서 거래대금 상위 N + 최소 가격(MIN_PRICE) 필터 권장
- 상대강도(RS) 도입 시 지수 대비 상위 분위만 통과(선택)
- 20/60일 수익률·회전율·과도갭 빈도 등을 보조 점수로 활용(선택)

## 보유/매도 평가(개요)

- (권장) 보유 목록은 Supabase `holdings`를 단일 소스로 사용합니다(웹 UI에서 CRUD).
- 웹 Holdings 화면에서 `Export YAML`로 전체 holdings snapshot을 `holdings.yaml`로 내보낼 수 있습니다.
- 같은 화면의 import 패널은 `holdings.yaml`을 dry-run으로 먼저 검증하고, 확인 후 **Replace All** 방식으로 현재 DB를 파일 내용으로 교체합니다.
- export는 `quantity=0` 비활성 row까지 포함하며, 로컬 `sab sell`은 그중 `quantity > 0` row만 평가 대상으로 사용합니다.
- 로컬에서 `sab sell`을 직접 실행할 때는 `holdings.yaml`(백업 파일) 또는 `--holdings <path>`로 지정한 파일을 입력으로 사용합니다.
- `--holdings <path>` 또는 `files.holdings`가 지정된 경우, 파일이 존재하지 않으면 즉시 실패합니다.
- 스키마와 예시는 `docs/holdings-schema.md` 및 `holdings.example.yaml`을 참고하세요.

## 장 오픈 진입 체크(현재 제공)

- 기본 Entry 평가는 이미 `sab entry`로 제공되며, `reports/YYYY-MM-DD(-n).entry.json` 아티팩트를 생성합니다.
- Entry 리포트를 웹에서 보려면 Supabase 업로드가 필요하며, `SAB_UPLOAD_REPORTS=true` 또는 `sab entry --upload` 경로를 사용합니다.
- 웹 `Run` 탭과 GitHub Actions workflow는 아직 `entry` 실행을 직접 트리거하지 않습니다.

## 데이터 수집(히스토리 누적)

- KIS 일봉 API는 호출당 최대 100봉을 반환합니다. `MIN_HISTORY_BARS`(권장 200) 이상을 확보하기 위해 날짜 창을 이동하며 여러 번 호출해 누적 수집합니다.
- 첫 실행은 2~3회 호출로 충분한 길이를 확보하고, 이후 실행은 최근 구간만 증분 갱신합니다.
- 레이트리밋(EGW00201) 대응을 위해 요청 간 최소 간격(`KIS_MIN_INTERVAL_MS`)과 백오프 재시도를 적용합니다.

## US 시장 참고

- 해외 스크리너 모드
  - `kis`: KIS 해외 랭킹 API(거래량/시가총액/거래대금 순위) 사용
  - `defaults`: 설정의 기본 유니버스(`screener.us_defaults`)에서 상위 N 선택
  - `screener.us_defaults`는 명시 거래소 suffix 티커만 허용(`AAPL.NAS`, `MSFT.NAS` 등). bare/KR/`.US`/미지원 suffix는 설정 로드 단계에서 즉시 실패
  - `screener.us_mode=kis`는 fail-closed로 동작하며 `screener.us_defaults` 자동 폴백을 사용하지 않습니다.
  - `--universe screener`에서 US KIS 스크리너가 실패/빈 결과면 즉시 실패합니다.
  - `--universe both`에서 US KIS 스크리너가 실패/빈 결과면 watchlist는 유지하고 US 스크리너만 건너뜁니다.
  - `--screener-limit`을 명시하면 KR/US 모두 해당 값이 우선 적용됩니다.
  - `--screener-limit` 미지정 시 KR은 `screener.limit`, US는 `screener.us_limit`을 사용합니다.
- 미국 시장 시간대는 EST/EDT 기준(09:30-16:00)이며, 스크리너 메타데이터에 시장 상태(open/closed)를 표기합니다.
- 환율/통화 병기: `FX_MODE=kis`로 두면 KIS 해외 현재가상세에서 실시간 환율(`t_rate`)을 읽어 자동 적용합니다. `USD_KRW_RATE`는 manual 모드나 폴백으로 사용됩니다.
- `FX_MODE` 상세
  - `kis` (권장): `/uapi/overseas-price/v1/quotations/price-detail` 호출로 `t_rate`(당일환율)를 조회하고 `FX_CACHE_TTL` 분 동안 캐시합니다. `FX_KIS_SYMBOL`로 환율 조회용 심볼을 지정하거나, 자동으로 첫 USD 후보를 사용합니다.
  - `manual`: `USD_KRW_RATE` 또는 `config.yaml`의 `fx.usdkrw` 값을 그대로 사용
  - `off`: 환율을 무시하고 USD 금액만 출력합니다.
  - 어떤 모드든 KIS 호출 실패 시 `USD_KRW_RATE` 값이 있으면 폴백하며, 값이 없으면 리포트 Appendix에 경고가 추가됩니다.
- 휴장일: KIS 해외 휴일 API(`countries-holiday`)를 조회해 휴일/조기폐장 여부를 메타데이터에 표시합니다.
  - `data/holidays_us.json`이 없거나 12시간 TTL을 넘긴 경우에만 재호출하며, 한 번 갱신할 때는 기본 10일 구간만 조회합니다.

### Per-market 임계치(권장)

- `config.yaml`의 `screener.min_price`/`min_dollar_volume`는 KR 기준(원화)
- `screener.us.min_price`/`min_dollar_volume`는 US 기준(달러)로 별도 지정해 정확도를 높일 수 있습니다.

### KIS 토큰 캐시

- KIS 토큰은 1일 1회 발급 원칙입니다. 본 프로젝트는 토큰을 `data/`에 캐시해 같은 날 재발급을 피합니다.

## 개발 운영(1인 사이드 프로젝트)

- 이 저장소는 1인 개발 기준으로 운영합니다.
- 기본 흐름은 `main`에 직접 push + CI 자동 검증입니다.
- 필요할 때만 feature 브랜치/PR을 사용하고, PR을 쓸 때도 동일한 CI 검증을 적용합니다.
- 로컬 품질 점검 권장 명령:
  - `UV_CACHE_DIR=.uv-cache uv run ruff check .`
  - `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
  - `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
  - `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

## EOD Replay Harness

- `tests/fixtures/replay_eod/scan/*`는 fixture 기반 `scan` replay baseline입니다. 전략 변경이 buy artifact를 어떻게 바꾸는지 CI에서 고정 비교합니다.
- 실행 예시: `just test tests/test_replay_eod_scan.py -q`
- 새 replay case를 추가할 때는 각 case 디렉터리에 `config.yaml`, `watchlist.txt`, `adjusted_market_data.json`, `raw_market_data.json`, `expected.buy.json` 다섯 파일만 포함해야 합니다.

## Audit 자동화 (GitHub Actions)

- 보안/워크플로 감사 전용 파이프라인은 `.github/workflows/audit.yml`로 운영합니다.
- 트리거:
  - `pull_request`
  - `workflow_dispatch`
  - `schedule: "0 11 * * 1"` (매주 월요일 11:00 UTC)
- 감사 정책:
  - 엔진: Trivy(`vuln,secret`)
  - 차단 심각도: `HIGH,CRITICAL`
  - 미패치 취약점: `ignore-unfixed=true`
  - 결과물: `trivy-results.json` 아티팩트 업로드(성공/실패 모두)
- 로컬 수동 점검:
  - 빠른 점검: `trivy fs .`
  - CI 동일 정책 점검:
    - `trivy fs --scanners vuln,secret --severity HIGH,CRITICAL --ignore-unfixed --format json --output trivy-results.json .`
- 취약점 예외는 `.trivyignore`에서 관리합니다.
  - 임시 예외만 허용
  - 각 항목에 만료일/사유 주석 필수
  - 만료 시 즉시 삭제
- PR 차단(브랜치 보호) 필수 체크:
  - `CI / Ruff + Mypy + Pytest (Python 3.14)`
  - `CI / Next.js Web (Lint + Typecheck + Test + Build)`
  - `workflow_audit`
  - `security_audit`

## 의존성 업데이트 자동화 (Renovate)

- 의존성 업데이트는 GitHub Actions 커스텀 워크플로 대신 Renovate GitHub App으로 운영합니다.
- 스케줄: 매주 월요일 09:00 UTC
- 자동 머지 정책:
  - `patch`: CI 통과 시 자동 머지
  - `minor`/`major`: 수동 검토 후 머지
- 관리 범위:
  - Python: `pyproject.toml`, `uv.lock`
  - Web: `web/package.json`, `web/pnpm-lock.yaml`
  - CI/런타임: `.github/workflows/*.yml`, `docker-compose.yml`, `web/Dockerfile`, `web/Dockerfile.dev`
- 안정성 우선 정책:
  - `.pre-commit-config.yaml`은 Renovate 업데이트 대상에서 제외
  - 잠금 파일 유지보수 PR(lock file maintenance)은 자동 머지를 비활성화
  - 메이저 업데이트 PR에는 `major` 라벨을 추가

설정 파일은 `renovate.json`을 참고하세요.

## 문서 상태

### 현재 제공

- Buy/Sell/Entry 파이프라인과 로컬 AI Brief 생성은 로컬 JSON 리포트 생성까지 동작합니다.
- 웹 콘솔은 Reports(`buy`/`sell`/`entry`/`ai-brief`), Holdings CRUD, Add Buy, YAML import/export, Metrics, `scan`/`sell` Run 트리거를 제공합니다.
- GitHub Actions `scan.yml`/`sell.yml`은 `schedule` + `workflow_dispatch`와 자동 실행 알림을 지원합니다.
- GitHub Actions `ai-brief.yml`은 수동 `workflow_dispatch`와 KR/US 장전 schedule로 단일 시장 scan → entry → ai-brief를 실행하고 JSON/preview artifact를 업로드하며, 수동 opt-in 또는 scheduled 기본값으로 Telegram/Slack 알림을 발송할 수 있습니다. `source_provider=http-json`을 선택하거나 scheduled 실행에서 `AI_BRIEF_SOURCE_API_URL` 변수를 설정하면 외부 source API context도 함께 주입합니다. `AI_BRIEF_SOURCE_API_TOKEN` secret은 실행 URL이 설정된 `AI_BRIEF_SOURCE_API_URL` 변수와 일치할 때만 전달합니다.
- RSS/Atom/RDF 캡처 feed는 `scripts/collect_ai_brief_sources.py`로 `sources[]` payload를 만들고, 기존 `ai-brief-source-eval`로 freshness/coverage/cap 품질을 확인할 수 있습니다.

### 실험

- 별도 실험 전용 사용자 기능은 현재 운영 기준에 포함하지 않습니다.
- 전략/파라미터 실험은 `tests/fixtures/replay_eod`와 설정 오버라이드로 검증합니다.

### 백로그

- 웹 `Run` 탭과 GitHub Actions workflow에 `entry` 실행 경로 추가
- 장 오픈 진입 가이드(ORH/첫 눌림 재상승 등) 텍스트 보강
- live 벤더별 news/API adapter 운영화와 source 품질 eval suite 고도화

### 폐기 후보

- `watchlist.yaml` 같은 추가 입력 포맷 확장은 현재 근거가 부족해 채택 후보로 올리지 않습니다.
- 긴 작업 분리 설계 없이 웹을 원격/Vercel에 직접 노출하는 방향은 재추진하지 않습니다.

## 라이선스

- 본 리포지토리의 소스코드는 MIT License를 따릅니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.
