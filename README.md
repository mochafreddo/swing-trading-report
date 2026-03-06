# Swing Trading Report (KR, On‑Demand)

간단한 스윙 스크리닝을 원할 때만 실행하고, 결과를 **JSON 리포트**로 저장한 뒤 **로컬 웹(Next.js)** 에서 열람하는 개인용 프로젝트입니다. 데이터 소스는 기본적으로 한국투자증권 KIS Developers(Open API)를 사용하며, 국내(KR) 기본 + (선택) 해외(US)까지 확장 가능합니다. 프로젝트/의존성 관리는 uv를 사용합니다.

권장 구성(개인용):

- 로컬 UI: Next.js(로컬 Docker)
- 데이터: Supabase(Postgres/Storage) — 보유 목록/리포트/실행 이력
- 자동 실행: GitHub Actions `schedule` (자동 실행일 때만 알림 전송)
  - 텔레그램: 리포트 본문(매수 후보/매도·점검 후보) 전송
  - 슬랙: 기존 요약 포맷 유지

상세 문서 인덱스는 `docs/README.md`, 배경/요구사항은 `docs/PRD.md`를 참고하세요.

## Requirements

- Python 3.14+
- uv
- (선택) just (`justfile` 레시피 실행)
- (선택) direnv (프로젝트 진입 시 로컬 환경변수 자동 적용)
- (선택: 웹 UI를 호스트에서 직접 실행할 때) Node.js + pnpm (버전 기준: `web/Dockerfile`, `web/package.json`)
  - 권장: `mise` 설치 후 `mise install` (`mise.toml`/`mise.lock` 기준)
  - 권장: 셸 활성화(`eval "$(mise activate zsh)"`) 또는 명령 실행 시 `mise x -- <cmd>` 사용
- (로컬 배포) Docker Desktop

## Quickstart (uv 기반)

- uv 설치(macOS)
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - 확인: `uv --version`

- 의존성/프로젝트 준비
  - 기본(슬림) 프로파일: `UV_CACHE_DIR=.uv-cache uv sync`
  - 개발 의존성 포함: `UV_CACHE_DIR=.uv-cache uv sync --all-groups`
  - (선택) 반복 실행은 `justfile` 사용: `just --list`
  - 도구체인(Node/pnpm) 동기화: `mise install` (`mise.lock`이 함께 커밋되어 있어야 재현성 보장)
  - lockfile 갱신(도구 버전 변경 시): `mise lock --platform linux-x64,macos-arm64 && mise install`
  - `.env` 자동 로딩은 기본 내장 파서로 동작(추가 의존성 불필요)
  - (선택) direnv 사용 시:
    - zsh 훅 추가: `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc`
    - 프로젝트 최초 1회: `direnv allow .`
    - 기본값은 `.envrc`에서 관리(`UV_CACHE_DIR`, `PRE_COMMIT_HOME`), 머신별 오버라이드는 `.envrc.local` 사용(`.envrc.local.example` 참고)
    - `.env`는 direnv가 아니라 애플리케이션(`sab`)이 로드합니다.
  - (선택) `python-dotenv` 고급 파싱 사용: `UV_CACHE_DIR=.uv-cache uv sync --extra dotenv`
  - (선택) 거래소 휴장일 자동 캘린더: `UV_CACHE_DIR=.uv-cache uv sync --extra calendar`
  - (선택) PyKRX 데이터 제공자/폴백: `UV_CACHE_DIR=.uv-cache uv sync --extra pykrx`
  - (선택) 전체 기능: `UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups`
  - 잠금 갱신이 필요하면: `UV_CACHE_DIR=.uv-cache uv lock` (업그레이드: `UV_CACHE_DIR=.uv-cache uv lock --upgrade`)

- .env 설정(예시)
  - 원칙:
    - `.env`는 **시크릿/환경별 값만** 둡니다(커밋 금지).
    - 비시크릿 설정은 `config.yaml`로 관리합니다(샘플: `config.example.yaml`).
    - `config.yaml`과 `.env`에 **동일 키를 중복 정의하지 않습니다**(충돌 시 실패).
  - 최소 예시(필수):
    - `KIS_APP_KEY=...`
    - `KIS_APP_SECRET=...`
  - 웹 UI 추가(필수):
    - `SUPABASE_URL=...`
    - `SUPABASE_SECRET_KEY=...` (또는 `SUPABASE_SERVICE_ROLE_KEY=...`)
    - `SAB_BASIC_AUTH_USER=...`, `SAB_BASIC_AUTH_PASS=...`, `SAB_SESSION_SECRET=...`
  - 선택(로컬 운영 편의):
    - `LOG_LEVEL=INFO`
  - 전체 키 목록/설명은 `.env.example`을 참고하세요.

- 실행 예시
  - 기본 실행: `UV_CACHE_DIR=.uv-cache uv run -m sab scan`
  - 평가 상한 지정(워치리스트+스크리너 병합 후 최종 cap): `UV_CACHE_DIR=.uv-cache uv run -m sab scan --limit 30`
  - 스크리너 상위 N 조정(KR/US 공통): `UV_CACHE_DIR=.uv-cache uv run -m sab scan --screener-limit 15`
  - 유니버스 선택: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe watchlist` (옵션: `watchlist`, `screener`, `both`)
  - 워치리스트 지정: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --watchlist watchlist.txt`
  - 워치리스트 티커 정책(fail-closed):
    - KR은 6자리 숫자 코드만 허용(예: `005930`)
    - US는 명시 거래소 suffix 필수(예: `AAPL.NAS`, `IBM.NYS`, `SPY.AMS`)
    - US 클래스 티커는 `BASE.CLASS.EXCH`를 캐노니컬로 사용(예: `BRK.B.NYS`), `BRK/B.NYS` 입력은 허용하되 내부에서 `BRK.B.NYS`로 정규화
    - `AAPL`(bare), `.US`(모호 suffix), 미지원 suffix(`AAPL.XNAS`)는 즉시 실패
    - Supabase `holdings`도 동일 계약을 강제하며, 기존 `.US` row가 있으면 관련 migration은 수동 정리 전까지 실패
  - 유니버스별 watchlist 로드 정책:
    - `--universe screener`: watchlist 파일을 로드/검증하지 않음
    - `--universe watchlist|both`: watchlist를 로드하며, 파일 누락/티커 검증 실패 시 즉시 실패
  - (선택) KIS 장애 시 PyKRX 폴백을 원하면 `UV_CACHE_DIR=.uv-cache uv sync --extra pykrx`
  - 보유 평가: `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
  - 진입 평가(Entry): `UV_CACHE_DIR=.uv-cache uv run -m sab entry`
    - mixed KR/US buy 리포트도 시장별로 나눠 한 번에 평가합니다.
    - 특정 시장만 평가하려면 `UV_CACHE_DIR=.uv-cache uv run -m sab entry --market US`처럼 지정합니다.
    - 치명 열화 임계치(선택): `ENTRY_FATAL_MISSING_PRICE_RATIO` (기본 `1.0`)
      - `entry_price`가 비어 있는 행 비율이 임계치 이상이면 `sab entry`는 `exit 1`로 종료
      - `0.0`은 “누락이 1건이라도 있으면 실패” 정책으로 해석
  - 웹 UI(Next.js): `.env`에 Supabase/로그인 설정 후 `docker compose up -d --build web` → `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
  - 로컬 CLI 실행 결과도 웹에서 보고 싶다면: `.env`에 `SAB_UPLOAD_REPORTS=true` (Supabase 설정 필요)

- 웹 UI 로컬 실행(Next.js + Docker)
  - 기본 운영 기준: `web` 서비스는 이미지 빌드 시 `pnpm run build`를 수행하고, 런타임 엔트리는 `pnpm run start`만 실행합니다.
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
  - 직접 실행(선택): `cd web && pnpm install && pnpm run dev`
  - 직접 실행 기본 바인딩: `WEB_BIND_HOST` 미지정 시 `127.0.0.1`
  - 직접 실행에서 `SAB_ENFORCE_LOCAL_REQUEST=0`와 non-loopback bind(`0.0.0.0`, 사설 IP 등)를 함께 쓰면 시작 단계에서 차단됩니다.
  - Docker Compose는 컨테이너 내부 `0.0.0.0` bind를 쓰더라도 호스트 publish가 `127.0.0.1:${WEB_HOST_PORT}:3000`이면 지원 경로입니다.
  - 직접 실행 시 Node 버전은 `web/Dockerfile`/`web/Dockerfile.dev`의 `FROM node:<version>`과 동일하게 맞춥니다.
  - 웹 패키지 매니저: `pnpm` (고정)
  - 기능:
    - `Reports`: 리포트 목록/상세/타입 필터/ticker substring 검색
      - 검색 범위 정책: 서버 환경변수 `REPORT_SEARCH_WINDOW` (기본 100, 최소 10, 최대 1000)
      - 런타임 상태 저장소: `SAB_RUNTIME_STATE_STORE` (`supabase`/`memory`, 기본은 테스트 외 `supabase`)
      - 로그인 스로틀 장애 정책: `SAB_LOGIN_THROTTLE_FAIL_MODE` (`degrade`/`strict`, 기본 `degrade`)
      - 응답의 `truncated=true`는 "정책상 검색 대상이 잘려 더 오래된 리포트는 미검색"을 의미
      - 보호 경계: `/api/reports` 및 `/api/reports/detail`은 관리자 세션 인증(`requireAdminAuth`) + same-origin 검증을 필수로 요구
    - `Holdings`: Supabase `holdings` CRUD
      - 보호 경계: `/api/holdings` 및 `/api/holdings/[ticker]`는 관리자 세션 인증 + same-origin 검증을 필수로 요구
      - 목록 조회: cursor 기반 페이지네이션(`limit`, `cursor`) + UI `Load more`
      - 추가매수(`POST /api/holdings/[ticker]/add-buy`): `Idempotency-Key`(UUID) 헤더 필수, 동일 키 재시도 시 기존 결과 반환, 동일 키-다른 payload는 `409` 충돌 처리
      - `sell` 평가는 `quantity > 0` 활성 보유분만 대상으로 처리
    - `Run`: `scan.yml`/`sell.yml` `workflow_dispatch` 트리거
      - 기능 플래그: `RUN_DISPATCH_ENABLED=1`에서 활성화(하위 호환: 플래그 미설정 + `GITHUB_OWNER/GITHUB_REPO/GITHUB_PAT` 모두 설정 시 자동 활성)
      - 보호 경계: `/api/run`은 관리자 세션 인증 + same-origin 검증을 필수로 요구, 실행 ref는 `main`으로 고정
      - `scan` 실행 입력 정책: `provider=pykrx`는 `universe=KR`에서만 지원
      - `scan`에서 `provider=pykrx`를 사용할 때는 `watchlist.txt`(또는 `WATCHLIST_FILE`/`files.watchlist`)가 비어 있지 않아야 함
      - `scan`에서 `provider=pykrx` + `universe=US|both` 조합은 입력 검증 단계에서 실패하도록 설계
      - 기본 하드닝: 로컬 요청 검사는 기본 활성(`Host` + `x-forwarded-host` 일관성, unsafe 메서드는 `origin/referer` 로컬성 또는 `sec-fetch-site=same-origin` 요구), `SAB_ENFORCE_LOCAL_REQUEST=0`에서만 비활성화 (`/api/auth/*`, `/api/holdings*`, `/api/reports*`, `/api/run`)
      - 시작 가드: direct bind가 loopback 밖으로 열려 있고 동시에 `SAB_ENFORCE_LOCAL_REQUEST=0`이면 서버는 시작하지 않습니다.
      - 운영 가정: 당분간 웹은 `localhost/127.0.0.1` 단일 사용자 노출만 지원하며, local-request 가드는 원격 노출의 완전한 보안 경계로 간주하지 않습니다.

- 결과(리포트 분리 설계)
  - Buy: `reports/YYYY-MM-DD(-n).buy.json`
  - Sell/Review: `reports/YYYY-MM-DD(-n).sell.json`
  - Entry: `reports/YYYY-MM-DD(-n).entry.json`
  - 웹 대시보드는 Supabase Storage(`SUPABASE_REPORTS_BUCKET`, 기본값 `reports`)의 JSON을 렌더링합니다.
    - 업로드는 GitHub Actions에서 기본 수행, 로컬에서는 `SAB_UPLOAD_REPORTS=true`일 때만 수행합니다.

## CLI 서브커맨드

`python -m sab` CLI는 아래 서브커맨드를 제공합니다.

<!-- CLI_SUBCOMMANDS_START -->
| 실행 예 | 설명 |
|---|---|
| `UV_CACHE_DIR=.uv-cache uv run -m sab scan` | 후보 수집/평가 후 JSON 리포트 생성 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab sell` | 보유 종목을 매도/점검 규칙으로 평가 |
| `UV_CACHE_DIR=.uv-cache uv run -m sab entry` | buy 리포트 후보를 다음 세션 진입 관점으로 평가 |
<!-- CLI_SUBCOMMANDS_END -->

문서-구현 동기화 검증: `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q tests/test_readme_cli_commands_sync.py`

## 개발 운영(1인 사이드 프로젝트)

- 이 저장소는 1인 개발 기준으로 운영합니다.
- 기본 흐름은 `main`에 직접 push + CI 자동 검증입니다.
- 필요할 때만 feature 브랜치/PR을 사용하고, PR을 쓸 때도 동일한 CI 검증을 적용합니다.
- 로컬 품질 점검 권장 명령:
  - `UV_CACHE_DIR=.uv-cache uv run ruff check .`
  - `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
  - `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
  - `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

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

참고(US 시장)

- 해외 스크리너 모드
  - `kis`: KIS 해외 랭킹 API(거래량/시가총액/거래대금 순위) 사용
  - `defaults`: 설정의 기본 유니버스(`screener.us_defaults`)에서 상위 N 선택
  - `screener.us_defaults`는 명시 거래소 suffix 티커만 허용(`AAPL.NAS`, `MSFT.NAS` 등). bare/KR/`.US`/미지원 suffix는 설정 로드 단계에서 즉시 실패
  - `screener.us_mode=kis`는 fail-closed로 동작하며 `screener.us_defaults` 자동 폴백을 사용하지 않습니다.
  - `--universe screener`에서 US KIS 스크리너가 실패/빈 결과면 즉시 실패합니다.
  - `--universe both`에서 US KIS 스크리너가 실패/빈 결과면 watchlist는 유지하고 US 스크리너만 건너뜁니다.
  - `--screener-limit`을 명시하면 KR/US 모두 해당 값이 우선 적용됩니다.
  - `--screener-limit` 미지정 시 KR은 `screener.limit`, US는 `screener.us_limit`을 사용합니다.
- 미국 시장 시간대는 EST/EDT 기준(09:30–16:00)이며, 스크리너 메타데이터에 시장 상태(open/closed)를 표기합니다.
- 환율/통화 병기: `FX_MODE=kis`로 두면 KIS 해외 현재가상세에서 실시간 환율(`t_rate`)을 읽어 자동 적용합니다. `USD_KRW_RATE`는 manual 모드나 폴백으로 사용됩니다.
- `FX_MODE` 상세
  - `kis` (권장): `/uapi/overseas-price/v1/quotations/price-detail` 호출로 `t_rate`(당일환율)를 조회하고 `FX_CACHE_TTL` 분 동안 캐시합니다. `FX_KIS_SYMBOL`로 환율 조회용 심볼을 지정하거나, 자동으로 첫 USD 후보를 사용합니다.
  - `manual`: `USD_KRW_RATE` 또는 `config.yaml`의 `fx.usdkrw` 값을 그대로 사용.
  - `off`: 환율을 무시하고 USD 금액만 출력합니다.
  - 어떤 모드든 KIS 호출 실패 시 `USD_KRW_RATE` 값이 있으면 폴백하며, 값이 없으면 리포트 Appendix에 경고가 추가됩니다.
- 휴장일: KIS 해외 휴일 API(`countries-holiday`)를 조회해 휴일/조기폐장 여부를 메타데이터에 표시합니다.
  - `data/holidays_us.json`이 없거나 12시간 TTL을 넘긴 경우에만 재호출하며, 한 번 갱신할 때는 기본 10일 구간만 조회합니다.

Per‑market 임계치(권장)

- `config.yaml`의 `screener.min_price`/`min_dollar_volume`는 KR 기준(원화)
- `screener.us.min_price`/`min_dollar_volume`는 US 기준(달러)로 별도 지정해 정확도를 높일 수 있습니다.

참고: KIS 토큰은 1일 1회 발급 원칙입니다. 본 프로젝트는 토큰을 `data/`에 캐시해 같은 날 재발급을 피합니다.

## 파일/폴더 구조

- `sab/` … Python 애플리케이션 코드
  - `__main__.py` … CLI 엔트리(`sab scan` / `sab sell` / `sab entry`)
  - `data/` … KIS/PyKRX 커넥터, 캐시
  - `signals/` … EMA/RSI/ATR 계산
  - `report/` … 리포트 아티팩트(JSON) 생성
- `web/` … Next.js 로컬 대시보드(App Router + Route Handler)
- `reports/` … 생성된 JSON 리포트 아티팩트 출력 폴더
- `data/` … 캐시/상태(현재 JSON, 추후 SQLite 고려)
- `docs/README.md` … 문서 인덱스(진입점)
  - `docs/adr/README.md` … ADR 인덱스
  - `docs/reviews/README.md` … 리뷰 인덱스
- `supabase/` … Supabase 마이그레이션/설정
- `holdings.yaml` … 선택 백업 파일(import/export 용도)

## 작업 자동화 (just + direnv)

- 기본 레시피 목록: `just --list`
- 대표 명령:
  - `just scan`
  - `just sell`
  - `just entry`
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

## 상태

- Buy/Sell/Entry 파이프라인이 로컬 JSON 리포트 생성까지 동작.

## 라이선스

- 본 리포지토리의 소스코드는 MIT License를 따릅니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.

## 전략(요약)

- 상세 계약/모드별 규칙: `docs/STRATEGY.md`
- 코어: EMA20/50 골든크로스 + RSI14 30 상향 재돌파(+ RSI<70)
- 장기 필터(옵션): 가격/EMA20/EMA50 모두 SMA200 위
- 갭 필터: ATR 기반(|갭| ≤ ATR×배수 / 전일종가), 기본 배수 1.0 권장
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
- 로컬에서 `sab sell`을 직접 실행할 때는 `holdings.yaml`(백업 파일) 또는 `--holdings <path>`로 지정한 파일을 입력으로 사용합니다.
- `--holdings <path>` 또는 `files.holdings`가 지정된 경우, 파일이 존재하지 않으면 즉시 실패합니다.
- 스키마와 예시는 `docs/holdings-schema.md` 및 `holdings.example.yaml`을 참고하세요.

## 장 오픈 진입 체크(개요, 확장 예정)

- 기본 Entry 평가는 이미 `sab entry`로 제공되며, `reports/YYYY-MM-DD(-n).entry.json` 아티팩트를 생성합니다.
- 향후 확장으로 전일 buy 후보 기준의 "시초 갭 + 5–15분 재확인(ORH 돌파/첫 눌림 재상승)" 가이드 텍스트를 추가할 계획입니다.

## 데이터 수집(히스토리 누적)

- KIS 일봉 API는 호출당 최대 100봉을 반환합니다. `MIN_HISTORY_BARS`(권장 200) 이상을 확보하기 위해 날짜 창을 이동하며 여러 번 호출해 누적 수집합니다.
- 첫 실행은 2~3회 호출로 충분한 길이를 확보하고, 이후 실행은 최근 구간만 증분 갱신합니다.
- 레이트리밋(EGW00201) 대응을 위해 요청 간 최소 간격(`KIS_MIN_INTERVAL_MS`)과 백오프 재시도를 적용합니다.
- config.yaml 활용(선택)
  - 비시크릿 기본값/임계치는 `config.yaml`에서 관리합니다(샘플: `config.example.yaml`).
  - 시크릿(`KIS_APP_KEY`, `KIS_APP_SECRET`)은 `.env`/환경변수로만 관리합니다.
  - `config.yaml`과 `.env`에 **동일 키를 중복 정의하지 않습니다**(충돌 시 실패).
  - 로컬 전용 설정이 필요하면 `config.local.yaml`을 만들고 `SAB_CONFIG=config.local.yaml`로 지정하세요(파일은 커밋하지 않기).
