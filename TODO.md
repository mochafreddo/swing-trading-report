# TODO — Execution Plan (Aligned with PRD/README/ROADMAP)

작업은 v1(MVP) → v1.1(스크리너/설정 고도화) → v1.2(시각화/분석) 순으로 진행합니다.

## v1 (MVP) — 기능 완성 + 기본 품질

- 환경/문서
  - [x] uv 설치/프로젝트 구성(`pyproject.toml`, `uv.lock`)
  - [x] 문서 정리(PRD, README, docs/kis-setup.md, docs/report-spec.md)

- 코드 스캐폴딩/CLI
  - [x] `sab/` 패키지 및 CLI 엔트리(`sab/__main__.py` → `sab scan`)
  - [x] 설정 로더(`sab/config.py`) + `.env` 반영(포트 자동 보정, DATA_DIR)
  - [x] 보고서 출력(`sab/report/markdown.py`)

- 데이터 계층
  - [x] KIS 클라이언트(`sab/data/kis_client.py`)
  - [x] 토큰 발급/캐시(1일 1회 정책 준수, `data/kis_token_<env>.json`)
  - [x] 일봉 조회(`/uapi/.../inquire-daily-itemchartprice`, TR_ID 설정)
  - [x] 캔들 캐시(`data/candles_<ticker>.json`) + 폴백 사용
  - [x] 레이트리밋/재시도(간단 backoff)
  - [x] 히스토리 누적 수집: 날짜 창 이동으로 200+ 봉 확보(최소 `MIN_HISTORY_BARS` 충족), 증분 갱신, EGW00201 대비

- 평가/리포트
  - [x] 지표 계산(EMA20/50, RSI14, ATR14, 갭)
  - [x] 후보 선별(골든크로스 + RSI 30 재돌파 + 갭 ±3%)
  - [x] Buy 리포트 생성(헤더/테이블/상세/Appendix, cache 상태 노출)
  - [x] Buy 리포트 파일명 `.buy.md` 적용(코드 반영)
  - [x] 전략 개선 적용(문서 반영됨):
    - [x] SMA200 필터(옵션) + EMA 기울기 필터
    - [x] 갭 임계 ATR 기반 전환(GAP_ATR_MULTIPLIER)
    - [x] 유동성 필터(최근 20일 평균 거래대금 MIN_DOLLAR_VOLUME)
    - [x] ETF/ETN/레버리지/인버스 제외 옵션
    - [x] 점수화 및 정렬 개선(구성 요소별 점수 포함)

- CLI/UX 품질
  - [x] 옵션: `--limit`, `--watchlist`, `--provider`
  - [x] 종료 코드/에러 메시지 정리(사용자 가독성 향상)
  - [x] 기본 로깅 레벨/형식 정리(정보/경고 구분)

## v1.1 — 스크리너/설정 고도화/폴백 정식화

- 스크리너
  - [x] 지표/필터 결정: 최근 20일 평균 거래대금/거래량, 가격 하한 등
  - [x] KIS 순위/시세 API 검토 및 선택(MCP 활용)
    - 예: 국내주식 순위분석 카테고리(거래대금/거래량/등락률 상위)
  - [x] 구현: `sab/screener/kis_screener.py` (랭킹 조회 → 정규화 → 상위 N)
  - [x] 캐시/쿨다운(일중 과도 호출 방지)
    - [x] 일정 시간(예: 5분) 내 재실행 시 스크리너 결과 캐시 사용
    - [x] 장중 재호출 시 최소 간격/쿨다운 로그 안내
  - [x] 워치리스트 병합 전략: 보유/워치 항상 포함 + 스크리너 상위 N
  - [x] CLI: `--screener-limit N`, `--universe watchlist|screener|both`
  - [x] 리더 보완: RS(지수 대비) 점수 도입, MIN_PRICE(.env → 스크리너) 연동

- 설정 고도화
  - [x] `config.yaml` 지원(.env 병행), 기본값/임계치 설정화
  - [x] 전략 임계치 전부 설정화(.env → config.yaml 마이그레이션 가이드)

- 데이터 소스 폴백(선택)
  - [x] PyKRX 커넥터(`sab/data/pykrx_client.py`) 정식화 + 리포트 경고 표기

- 보유/매도 평가(초안)
  - [x] 보유 목록 스키마 설계(`holdings.yaml`): ticker, 수량, 진입가, 메모, 태그 등
  - [x] 로더 구현(`sab/config.py` 또는 별도 모듈)
  - [x] 매도/보류 규칙 정의 및 구현(`sab/signals/sell_rules.py`)
    - 무효화: EMA20/50 되크로스, 종가 EMA50/EMA20 하향 이탈, RSI50/30 재하락
    - 리스크: ATR 기반 트레일링 스탑(예: 1×ATR), 시간 스탑(N거래일 경과)
    - 예외: 갭다운 과도 시 방어 로직(부분청산/전량청산 기준)
  - [x] `sab sell` 서브커맨드 구현 → `reports/YYYY-MM-DD.sell.md`

## v1.2 — 전략/리포트/시각화/품질 강화

- 전략/리포트 고도화(SMA+EMA 하이브리드)
  - [x] SMA+EMA 하이브리드 매뉴얼 정리(`docs/swing-trading-manual.md`)
  - [x] 아키텍처/시그널/리포트 설계 문서 업데이트(`docs/ARCHITECTURE.md`, `docs/design/signals.md`, `docs/design/reports.md`)
  - [x] 전략 모드 설정 설계(`strategy.mode` + 하이브리드 설정 키 정의)
  - [x] 하이브리드 Buy 평가 모듈 설계/구현(추세 지속 눌림, 스윙 하이 돌파, RSI 과매도 반등)
  - [x] 하이브리드 Sell 규칙 설계/구현(이익 실현, 추세 붕괴, 실패한 돌파, 3–5% 스톱)
  - [x] Buy/Sell 리포트에 하이브리드 전용 필드/체크리스트 반영
- 시각화/분석
  - [ ] 차트 이미지 생성 후 리포트 삽입(옵션)
  - [ ] 간단 백테스트 스냅샷(최근 n건 신호 성공/실패 요약)
- 테스트/품질
  - [ ] 테스트 추가(지표/평가/리포트 단위 테스트, 특히 하이브리드 전략)
  - [x] 린터/포맷터 도입(ruff 기반)
    - [x] dev 의존성 추가: `uv add --group dev ruff`
    - [x] `pyproject.toml`에 `tool.ruff`/`tool.ruff.lint`/`tool.ruff.format` 설정 추가
    - [x] `uv run ruff check --fix` + `uv run ruff format`으로 1회 전체 코드 정리
    - [x] 커밋 전에 `uv run ruff check`가 항상 실행되도록 설정
      - IDE/에디터에서 on-save 포맷(`ruff format`) 및 on-type lint 활성화
      - [x] `.pre-commit-config.yaml`로 `ruff`/`ruff format` 훅 정의
      - [x] `uv run pre-commit install`로 Git 훅 설치
- 성능/리팩터링
  - [ ] 성능/리팩터링(로깅/병렬화/구조 개선, 전략 모듈 분리 포함)
- 해외 주식(US) 지원(초판)
  - [x] 해외 일봉 조회 + 누적 수집
  - [x] 해외 스크리너(간단) + 시간대/휴장일 처리
  - [x] 환율/통화 표시(선택, KIS price-detail 기반 자동 환율 + 캐시)
  - [x] 시장별 임계치 분리(US: USD 기준 min_price/min_dollar_volume)
  - [x] KIS 휴장일 API 연동 및 메타데이터 반영(휴일/조기폐장 표기)
- 장 오픈 진입 체크 기능
  - [ ] `sab entry` 서브커맨드 설계/구현(전일 Buy Report + 시초가/장초 데이터)
  - [ ] 갭-ATR 규칙(OK/Wait/Avoid) 및 5–15분 재확인 로직
  - [ ] Entry 리포트(`YYYY-MM-DD.entry.md`) 생성
  - [ ] launchd/cron 예시 추가

## 테스트 계획(네트워크/비네트워크)

- 비네트워크 단위 테스트(우선)
  - [ ] `sab/data/kis_client._request` 재시도/백오프: `requests.Session.request`를 monkeypatch하여 `ReadTimeout`/429/EGW00201 시나리오를 시뮬레이션
  - [ ] `sab/screener/kis_screener.py` 스크리너 타임아웃/오류 처리: KIS 호출 실패 시 예외 전파/로그/리포트 반영 검증(현재 설계 점검: 필요 시 try/except로 경고+빈 결과로 전환)
  - [x] 휴장일 캐시 병합: `sab/data/holiday_cache.merge_holidays` 입력 레코드 스키마 변형에 대한 견고성 테스트(필드 누락/이름 차이)
  - [ ] FX 리졸버: `sab/fx.resolve_fx_rate`의 KIS/캐시/수동 폴백 분기 검증
  - [ ] 평가기: 시장별 임계치 적용(USD vs KRW)과 메시지 정확성(가격/거래대금 미달 사유), 환율 병기 포맷
  - [ ] 리포트 빌더: `market_status`/환율 병기 라인, 오류/경고 Appendix 표기

- 네트워크 통합 테스트(옵션, 오프라인 기본)
  - [ ] KIS KR 스크리너(`volume-rank`) 호출 성공/지연/타임아웃 케이스 수동 점검(테스트 플래그/프록시로 타임아웃 유도)
  - [ ] KIS 해외 일봉/휴장일 API 호출 성공/지연/타임아웃 케이스 점검(캐시 폴백 확인)
  - [ ] E2E 스캔(워치리스트만/스크리너만/둘 다) 스모크 테스트: 리포트가 항상 생성되고 실패는 Appendix에 반영되는지 확인

- 개선 작업(테스트 기반)
  - [ ] KIS HTTP 타임아웃 설정화(`kis.http_timeout` 또는 `.env: KIS_HTTP_TIMEOUT`) → `_request(timeout=…)` 전달
  - [ ] 스크리너 예외 처리 정책 확정: KIS 실패 시 경고 후 다른 소스(워치/US defaults)로 진행하고 리포트는 경고로 완료
  - [ ] 로깅 메시지 정규화(실패/경고/정보) 및 재시도 횟수/백오프 표시

## 개발 편의(선택)

- [ ] `bin/scan` 스크립트, Makefile 타깃(`scan`, `scan-limit`, `sync`, `lock`)
- [ ] 샘플 데이터/샘플 리포트 추가

## 참고(레퍼런스)

- MCP(KIS Code Assistant)로 엔드포인트 탐색
  - 인증: `search_auth_api` (subcategory="인증", function_name="auth_token")
  - 국내주식 기간별 시세: `search_domestic_stock_api` (subcategory="기본시세", function_name="inquire_daily_itemchartprice")
- KIS Base URL 포트(실전 :9443, 모의 :29443)는 코드에서 자동 보정
- 토큰은 `data/kis_token_<env>.json`에 캐시 → 같은 날 재발급 방지
