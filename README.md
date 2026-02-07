# Swing Trading Report (KR, On‑Demand)

간단한 스윙 스크리닝을 원할 때만 실행하고, 결과를 마크다운 리포트로 저장하는 개인용 로컬 프로젝트입니다. 데이터 소스는 기본적으로 한국투자증권 KIS Developers(Open API)를 사용하며, 국내(KR) 기본 + (선택) 해외(US)까지 확장 가능합니다. 프로젝트/의존성 관리는 uv를 사용합니다.

상세 배경과 요구사항은 `docs/PRD.md` 참고.

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
  - `DATA_PROVIDER=kis`
  - `KIS_APP_KEY=...`
  - `KIS_APP_SECRET=...`
  - `KIS_BASE_URL=...`  # 모의/실전 (포트 생략 가능: 자동으로 9443/29443 보정)
  - 보안 정책: `kis.app_key`/`kis.app_secret`의 YAML 저장은 금지되며, 감지 시 실행이 실패합니다.
  - (선택) 로깅
    - `LOG_LEVEL=INFO` (또는 `DEBUG`)
    - `LOG_TZ=local` (기본) 또는 `utc`
    - `LOG_FORMAT=...` (기본: `%(asctime)s %(levelname)s %(name)s - %(message)s`)
    - `LOG_DATEFMT=...` (strftime 포맷, 미지정 시 ISO 8601 + ms + TZ)
  - `SCREEN_LIMIT=30`
  - `REPORT_DIR=reports`
  - `DATA_DIR=data`
  - `HOLDINGS_FILE=holdings.yaml`
  - `WATCHLIST_FILE=watchlist.txt`
  - `SCREENER_ENABLED=true` (옵션, KIS 상위 종목 스크리너 활성화)
  - `SCREENER_LIMIT=30` (옵션, 스크리너 상위 N)
  - `SCREENER_ONLY=false` (옵션, true이면 스크리너 결과만 사용)
  - `SCREENER_CACHE_TTL=5` (스크리너 캐시 유지 시간, 분)
  - `MIN_HISTORY_BARS=200` (다중 구간 호출로 목표 히스토리 길이 확보)
  - `KIS_MIN_INTERVAL_MS=500` (요청 간 최소 간격, 데모 500ms 권장)
  - `UNIVERSE_MARKETS=KR,US` (선택: 해외(US) 포함)
  - (선택) 해외 스크리너(KIS 연동 또는 기본목록)
    - `US_SCREENER_LIMIT=20`
    - `config.yaml`의 `screener.us_mode` = `kis` 또는 `defaults`
    - `screener.us_metric` = `volume|market_cap|value`
  - `ENTRY_CHECK_ENABLED=false` (선택: 장 오픈 진입 체크 기능)
  - `MIN_PRICE=1000` (스크리너 최소 가격 필터)
  - `RS_LOOKBACK_DAYS=60` (상대강도 계산 기간)
  - `RS_BENCHMARK_RETURN=0.0` (비교 기준 수익률, 소수로 입력 ex 0.05)
  - `FX_MODE=kis` (선택: 환율 소스 `kis|manual|off`, 기본 manual)
  - `FX_CACHE_TTL=10` (선택: KIS 환율 캐시 TTL 분 단위)
  - `FX_KIS_SYMBOL=AAPL.NAS` (선택: 환율 조회용 대표 USD 종목)
  - `USD_KRW_RATE=1320` (선택: manual 모드나 폴백용 고정 환율)
  - (선택) Sell 규칙 커스터마이즈:
    - `SELL_ATR_MULTIPLIER=1.0`
    - `SELL_TIME_STOP_DAYS=10`
    - `SELL_REQUIRE_SMA200=true`
    - `SELL_EMA_SHORT=20`, `SELL_EMA_LONG=50`
    - `SELL_RSI_PERIOD=14`, `SELL_RSI_FLOOR=50`, `SELL_RSI_FLOOR_ALT=30`
    - `SELL_MIN_BARS=20`

- 실행 예시
  - 기본 실행: `uv run -m sab scan`
  - 평가 상한 지정: `uv run -m sab scan --limit 30`
  - 스크리너 상위 N 조정: `uv run -m sab scan --screener-limit 15`
  - 유니버스 선택: `uv run -m sab scan --universe watchlist` (옵션: `watchlist`, `screener`, `both`)
  - 워치리스트 지정: `uv run -m sab scan --watchlist watchlist.txt`
  - (선택) KIS 장애 시 PyKRX 폴백을 원하면 `uv sync --extra pykrx`
  - 보유 평가: `uv run -m sab sell`
  - (예정) 익일 시초 체크: `uv run -m sab entry`

- 결과(리포트 분리 설계)
  - Buy: `reports/YYYY-MM-DD.buy.md` (장 마감 후 후보·근거)
  - Sell/Review: `reports/YYYY-MM-DD.sell.md` (보유 종목 평가)
  - Entry: `reports/YYYY-MM-DD.entry.md` (익일 시초 체크) — 예정
  - 상세 포맷은 `docs/report-spec.md` 참고

## 개발 운영(1인 사이드 프로젝트)

- 이 저장소는 1인 개발 기준으로 운영합니다.
- 기본 흐름은 `main`에 직접 push + CI 자동 검증입니다.
- 필요할 때만 feature 브랜치/PR을 사용하고, PR을 쓸 때도 동일한 CI 검증을 적용합니다.
- 로컬 품질 점검 권장 명령:
  - `UV_CACHE_DIR=.uv-cache uv run ruff check .`
  - `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
  - `UV_CACHE_DIR=.uv-cache uv run mypy sab`
  - `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

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

## 파일/폴더 구조(예정)

- `sab/` … 애플리케이션 코드
  - `__main__.py` … CLI 엔트리(`sab scan` / `sab sell` / `sab entry`)
  - `data/` … KIS/PyKRX 커넥터, 캐시
  - `signals/` … EMA/RSI/ATR 계산
  - `report/` … 마크다운 템플릿 렌더링(각 리포트별)
- `reports/` … 생성된 마크다운 리포트 출력 폴더
- `data/` … 캐시/상태(JSON 또는 SQLite)
- `docs/kis-setup.md` … KIS 설정 가이드
- `docs/report-spec.md` … 리포트 스펙
- `docs/ARCHITECTURE.md` … 아키텍처 문서
- `docs/PRD.md` … 제품 요구사항 문서
- `holdings.yaml` … 보유 목록(매도/보류 평가용)

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
  - 기본값/임계치를 한 곳에서 관리하려면 `config.yaml` 생성 후 `.env`보다 먼저 적용됩니다.
  - 시크릿(`KIS_APP_KEY`, `KIS_APP_SECRET`)은 `.env`/환경변수로만 관리합니다.
  - 예시는 repo 루트의 `config.example.yaml`을 참고하세요. 환경변수는 여전히 우선순위가 더 높습니다.
  - 로컬 전용 설정 파일은 `config.local.yaml` 패턴을 권장하며, 기본 `.gitignore`에 포함되어 있습니다.
  - `SAB_CONFIG=/path/to/config.yaml` 환경변수로 다른 경로의 설정 파일을 지정할 수 있습니다. 사용 시 `pyyaml` 패키지가 필요합니다.
  - `.env`에서 `config.yaml`로 옮기는 방법은 `docs/config-migration.md`를 참고하세요.
