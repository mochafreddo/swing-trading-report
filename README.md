# Swing Trading Report (KR, On‑Demand)

간단한 스윙 스크리닝을 원할 때만 실행하고, 결과를 **JSON 리포트**로 저장한 뒤 **로컬 웹(Next.js)** 에서 열람하는 개인용 프로젝트입니다. 데이터 소스는 기본적으로 한국투자증권 KIS Developers(Open API)를 사용하며, 국내(KR) 기본 + (선택) 해외(US)까지 확장 가능합니다. 프로젝트/의존성 관리는 uv를 사용합니다.

권장 구성(개인용):

- 로컬 UI: Next.js(로컬 Docker)
- 데이터: Supabase(Postgres/Storage) — 보유 목록/리포트/실행 이력
- 자동 실행: GitHub Actions `schedule` (자동 실행일 때만 알림 전송)

상세 배경과 요구사항은 `docs/PRD.md` 참고.

## Requirements

- Python 3.13+
- uv
- (선택: 웹 UI를 호스트에서 직접 실행할 때) Node.js (버전 기준: `web/Dockerfile`)
- (로컬 배포) Docker Desktop

## Quickstart (uv 기반)

- uv 설치(macOS)
  - `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - 확인: `uv --version`

- 의존성/프로젝트 준비
  - 기존 저장소라면 `pyproject.toml` 추가 후 의존성 동기화
  - 기본(슬림) 프로파일: `uv sync`
  - 개발 의존성 포함: `uv sync --all-groups`
  - `.env` 자동 로딩은 기본 내장 파서로 동작(추가 의존성 불필요)
  - (선택) `python-dotenv` 고급 파싱 사용: `uv sync --extra dotenv`
  - (선택) 거래소 휴장일 자동 캘린더: `uv sync --extra calendar`
  - (선택) PyKRX 데이터 제공자/폴백: `uv sync --extra pykrx`
  - (선택) 전체 기능: `uv sync --all-extras --all-groups`
  - 잠금 갱신이 필요하면: `uv lock`

- .env 설정(예시)
  - 원칙:
    - `.env`는 **시크릿/환경별 값만** 둡니다(커밋 금지).
    - 비시크릿 설정은 `config.yaml`로 관리합니다(샘플: `config.example.yaml`).
    - `config.yaml`과 `.env`에 **동일 키를 중복 정의하지 않습니다**(충돌 시 실패).
  - 최소 예시(필수):
    - `KIS_APP_KEY=...`
    - `KIS_APP_SECRET=...`
  - 선택(로컬 운영 편의):
    - `LOG_LEVEL=INFO`

- 실행 예시
  - 기본 실행: `UV_CACHE_DIR=.uv-cache uv run -m sab scan`
  - 평가 상한 지정: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --limit 30`
  - 스크리너 상위 N 조정: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --screener-limit 15`
  - 유니버스 선택: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe watchlist` (옵션: `watchlist`, `screener`, `both`)
  - 워치리스트 지정: `UV_CACHE_DIR=.uv-cache uv run -m sab scan --watchlist watchlist.txt`
  - (선택) KIS 장애 시 PyKRX 폴백을 원하면 `uv sync --extra pykrx`
  - 보유 평가: `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
  - 웹 UI(Next.js): `docker compose up -d web` 후 `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
  - (예정) 익일 시초 체크: `uv run -m sab entry`

- 웹 UI 로컬 실행(Next.js + Docker)
  - 기본 운영 기준: 컨테이너 실행을 권장하며 Node 버전 단일소스는 `web/Dockerfile`입니다.
  - 전환 직후 1회 정리: `docker compose down --remove-orphans && docker compose up -d --build web`
  - 일반 재기동: `docker compose up -d --build web`
  - 강제 재생성(문제 시): `docker compose stop web && docker compose rm -f web && docker compose up -d --build web`
  - 로그: `docker compose logs -f web`
  - 중지: `docker compose stop web`
  - 접속: `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
  - 포트 변경: `.env`에 `WEB_HOST_PORT=55444` 설정 후 `docker compose up -d --build web`
  - 직접 실행(선택): `cd web && pnpm install && pnpm run dev`
  - 직접 실행 시 Node 버전은 `web/Dockerfile`의 `FROM node:<version>`과 동일하게 맞춥니다.
  - 웹 패키지 매니저: `pnpm` (고정)
  - 기능:
    - `Reports`: 리포트 목록/상세/타입 필터/ticker substring 검색
      - 검색 범위 정책: 서버 환경변수 `REPORT_SEARCH_WINDOW` (기본 100, 최소 10, 최대 1000)
      - 응답의 `truncated=true`는 "정책상 검색 대상이 잘려 더 오래된 리포트는 미검색"을 의미
      - 로컬 전용 API: `/api/reports` 및 `/api/reports/detail`은 `localhost`/`127.0.0.1`/`::1` 요청만 허용
    - `Holdings`: Supabase `holdings` CRUD
      - 로컬 전용 API: `/api/holdings` 및 `/api/holdings/[ticker]`는 `localhost`/`127.0.0.1`/`::1` 요청만 허용
      - 목록 조회: cursor 기반 페이지네이션(`limit`, `cursor`) + UI `Load more`
    - `Run`: `scan.yml`/`sell.yml` `workflow_dispatch` 트리거
      - 로컬 전용 API: `/api/run`은 `localhost`/`127.0.0.1`/`::1` 요청만 허용, 실행 ref는 `main`으로 고정
      - `scan` 실행 입력 정책: `provider=pykrx`는 `universe=KR`에서만 지원
      - `scan`에서 `provider=pykrx`를 사용할 때는 `watchlist.txt`(또는 `WATCHLIST_FILE`/`files.watchlist`)가 비어 있지 않아야 함
      - `scan`에서 `provider=pykrx` + `universe=US|both` 조합은 입력 검증 단계에서 실패하도록 설계

- 결과(리포트 분리 설계)
  - Buy: `reports/YYYY-MM-DD.buy.json`
  - Sell/Review: `reports/YYYY-MM-DD.sell.json`
  - Entry: `reports/YYYY-MM-DD.entry.json` — 예정
  - 웹 대시보드는 `reports/`의 JSON을 렌더링합니다.

## 개발 운영(1인 사이드 프로젝트)

- 이 저장소는 1인 개발 기준으로 운영합니다.
- 기본 흐름은 `main`에 직접 push + CI 자동 검증입니다.
- 필요할 때만 feature 브랜치/PR을 사용하고, PR을 쓸 때도 동일한 CI 검증을 적용합니다.
- 로컬 품질 점검 권장 명령:
  - `UV_CACHE_DIR=.uv-cache uv run ruff check .`
  - `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
  - `UV_CACHE_DIR=.uv-cache uv run mypy sab`
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
  - `CI / Ruff + Mypy + Pytest (Python 3.13)`
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
  - CI/런타임: `.github/workflows/*.yml`, `docker-compose.yml`, `web/Dockerfile`
- 안정성 우선 정책:
  - `.pre-commit-config.yaml`은 Renovate 업데이트 대상에서 제외
  - 잠금 파일 유지보수 PR(lock file maintenance)은 자동 머지를 비활성화
  - 메이저 업데이트 PR에는 `major` 라벨을 추가

설정 파일은 `renovate.json`을 참고하세요.

참고(US 시장)

- 해외 스크리너 모드
  - `kis`: KIS 해외 랭킹 API(거래량/시가총액/거래대금 순위) 사용
  - `defaults`: 설정의 기본 유니버스(`screener.us_defaults`)에서 상위 N 선택
- 미국 시장 시간대는 EST/EDT 기준(09:30–16:00)이며, 스크리너 메타데이터에 시장 상태(open/closed)를 표기합니다.
- 환율/통화 병기: `FX_MODE=kis`로 두면 KIS 해외 현재가상세에서 실시간 환율(`t_rate`)을 읽어 자동 적용합니다. `USD_KRW_RATE`는 manual 모드나 폴백으로 사용됩니다.
- `FX_MODE` 상세
  - `kis` (권장): `/uapi/overseas-price/v1/quotations/price-detail` 호출로 `t_rate`(당일환율)를 조회하고 `FX_CACHE_TTL` 분 동안 캐시합니다. `FX_KIS_SYMBOL`로 환율 조회용 심볼을 지정하거나, 자동으로 첫 USD 후보를 사용합니다.
  - `manual`: `USD_KRW_RATE` 또는 `config.yaml`의 `fx.usdkrw` 값을 그대로 사용.
  - `off`: 환율을 무시하고 USD 금액만 출력합니다.
  - 어떤 모드든 KIS 호출 실패 시 `USD_KRW_RATE` 값이 있으면 폴백하며, 값이 없으면 리포트 Appendix에 경고가 추가됩니다.
- 휴장일: KIS 해외 휴일 API(`countries-holiday`)를 조회해 휴일/조기폐장 여부를 메타데이터에 표시합니다.

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
- `data/` … 캐시/상태(JSON 또는 SQLite)
- `docs/kis-setup.md` … KIS 설정 가이드
- `docs/PRD.md` … 제품 요구사항 문서
- `supabase/` … Supabase 마이그레이션/설정
- `holdings.yaml` … 선택 백업 파일(import/export 용도)

## 스크립트화 권장

반복 명령은 스크립트/Makefile로 캡슐화하면 편합니다.

- `bin/scan`
  - `uv run -m sab scan "$@"`
- `Makefile`
  - `scan`, `scan-limit`, `scan-watchlist`, `lock`, `sync` 등 타깃 정의

## 상태

- Buy 파이프라인 및 Sell 서브커맨드 동작. Entry 서브커맨드는 순차 구현 예정.

## 라이선스

- 본 리포지토리의 소스코드는 MIT License를 따릅니다. 자세한 내용은 `LICENSE` 파일을 참조하세요.
- `open-trading-api/` 디렉터리는 한국투자증권 KIS Developers 공개 샘플로, 해당 프로젝트의 라이선스/약관을 따릅니다(해당 폴더의 README/라이선스 참고).

## 전략(요약)

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

- holdings.yaml에 보유 종목을 기록하고, 무효화(EMA 되크로스/RSI 붕괴), 리스크(ATR 트레일), 시간 스탑 규칙으로 Sell/Review 섹션을 생성합니다.
- 스키마와 예시는 `docs/holdings-schema.md` 및 `holdings.example.yaml`을 참고하세요.

## 장 오픈 진입 체크(개요)

- 전일 리포트의 매수 후보를 기준으로, 다음 날 시초가 갭을 ATR 규칙으로 확인 후 5–15분 재확인(ORH 돌파/첫 눌림 재상승) 가이드 텍스트를 생성합니다.

## 데이터 수집(히스토리 누적)

- KIS 일봉 API는 호출당 최대 100봉을 반환합니다. `MIN_HISTORY_BARS`(권장 200) 이상을 확보하기 위해 날짜 창을 이동하며 여러 번 호출해 누적 수집합니다.
- 첫 실행은 2~3회 호출로 충분한 길이를 확보하고, 이후 실행은 최근 구간만 증분 갱신합니다.
- 레이트리밋(EGW00201) 대응을 위해 요청 간 최소 간격(`KIS_MIN_INTERVAL_MS`)과 백오프 재시도를 적용합니다.
- config.yaml 활용(선택)
  - 비시크릿 기본값/임계치는 `config.yaml`에서 관리합니다(샘플: `config.example.yaml`).
  - 시크릿(`KIS_APP_KEY`, `KIS_APP_SECRET`)은 `.env`/환경변수로만 관리합니다.
  - `config.yaml`과 `.env`에 **동일 키를 중복 정의하지 않습니다**(충돌 시 실패).
  - 로컬 전용 설정이 필요하면 `config.local.yaml`을 만들고 `SAB_CONFIG=config.local.yaml`로 지정하세요(파일은 커밋하지 않기).
