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

- 평가/리포트
  - [x] 지표 계산(EMA20/50, RSI14, ATR14, 갭)
  - [x] 후보 선별(골든크로스 + RSI 30 재돌파 + 갭 ±3%)
  - [x] 리포트 생성(헤더/테이블/상세/Appendix, cache 상태 노출)
  - [ ] 전략 개선 적용(문서 반영됨):
    - [ ] SMA200 필터(옵션) + EMA 기울기 필터
    - [ ] 갭 임계 ATR 기반 전환(GAP_ATR_MULTIPLIER)
    - [ ] 유동성 필터(최근 20일 평균 거래대금 MIN_DOLLAR_VOLUME)
    - [ ] ETF/ETN/레버리지/인버스 제외 옵션
    - [ ] 점수화 및 정렬 개선(구성 요소별 점수 포함)

- CLI/UX 품질
  - [x] 옵션: `--limit`, `--watchlist`, `--provider`
  - [x] 종료 코드/에러 메시지 정리(사용자 가독성 향상)
  - [x] 기본 로깅 레벨/형식 정리(정보/경고 구분)

## v1.1 — 스크리너/설정 고도화/폴백 정식화

- 스크리너
  - [ ] 지표/필터 결정: 최근 20일 평균 거래대금/거래량, 가격 하한 등
  - [ ] KIS 순위/시세 API 검토 및 선택(MCP 활용)
    - 예: 국내주식 순위분석 카테고리(거래대금/거래량/등락률 상위)
  - [x] 구현: `sab/screener/kis_screener.py` (랭킹 조회 → 정규화 → 상위 N)
  - [ ] 캐시/쿨다운(일중 과도 호출 방지)
  - [ ] 워치리스트 병합 전략: 보유/워치 항상 포함 + 스크리너 상위 N
  - [ ] CLI: `--screener N` 또는 `--universe screener|watchlist|both`

- 설정 고도화
  - [ ] `config.yaml` 지원(.env 병행), 기본값/임계치 설정화
  - [ ] 전략 임계치 전부 설정화(.env → config.yaml 마이그레이션 가이드)

- 데이터 소스 폴백(선택)
  - [ ] PyKRX 커넥터(`sab/data/pykrx_client.py`) 정식화 + 리포트 경고 표기

## v1.2 — 시각화/분석/품질 강화

- [ ] 차트 이미지 생성 후 리포트 삽입(옵션)
- [ ] 간단 백테스트 스냅샷(최근 n건 신호 성공/실패 요약)
- [ ] 테스트 추가(지표/평가/리포트 단위 테스트)
- [ ] 린터/포맷터(예: `uv add ruff`) 도입
- [ ] 성능/리팩터링(로깅/병렬화/구조 개선)

## 개발 편의(선택)

- [ ] `bin/scan` 스크립트, Makefile 타깃(`scan`, `scan-limit`, `sync`, `lock`)
- [ ] 샘플 데이터/샘플 리포트 추가

## 참고(레퍼런스)

- MCP(KIS Code Assistant)로 엔드포인트 탐색
  - 인증: `search_auth_api` (subcategory="인증", function_name="auth_token")
  - 국내주식 기간별 시세: `search_domestic_stock_api` (subcategory="기본시세", function_name="inquire_daily_itemchartprice")
- KIS Base URL 포트(실전 :9443, 모의 :29443)는 코드에서 자동 보정
- 토큰은 `data/kis_token_<env>.json`에 캐시 → 같은 날 재발급 방지
