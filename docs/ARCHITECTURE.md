# 아키텍처 — Swing Trading Report

이 문서는 KIS(옵션: PyKRX)를 기반으로 로컬 캐시, 간단 스크리너, 설정 가능한 전략을 활용해 CLI가 Buy/Sell/Entry 리포트를 생성하는 방식을 설명합니다.

## 목표와 범위

- 필요할 때만 실행하는 로컬 CLI: 일봉(EOD) 수집 → 규칙 평가 → 마크다운 작성
- 기본 시장: 한국(KIS). 선택적으로 KIS 해외 엔드포인트 또는 기본 목록을 통해 미국(US) 지원
- 상시 서버/푸시 알림 없음. 결과는 어떤 에디터로도 열람 가능

## 명령과 흐름

- `uv run -m sab scan` → Buy 리포트
  1) 설정 로드(config.yaml → .env → CLI) 2) 유니버스 구성(워치리스트 ± 스크리너) 3) 캐시/백오프를 고려해 캔들 수집 4) Buy 규칙 평가 5) `reports/YYYY-MM-DD.buy.md` 저장

- `uv run -m sab sell` → Sell/Review 리포트
  1) 보유 목록(`holdings.yaml`) 로드 2) 캔들 수집 3) Sell/Review 규칙(ATR 트레일, RSI, EMA 컨텍스트) 평가 4) `reports/YYYY-MM-DD.sell.md` 저장

- `uv run -m sab entry`(계획) → Entry 리포트
  - 전일 Buy 리포트를 파싱해 당일 시초/장초를 확인하고 OK/Wait/Avoid 가이드를 생성

## 모듈 맵

- `sab/config.py` … 설정 우선순위, 환경변수, 경로 보정, 보유 로드, 전략/시장별 임계치
- `sab/config_loader.py` … YAML 로더(옵션 `pyyaml`)
- `sab/data/kis_client.py` … KIS HTTP 클라이언트: 토큰 캐시, 스로틀, 백오프, 국내/해외 캔들, KR 랭크
- `sab/data/pykrx_client.py` … PyKRX를 통한 EOD OHLCV(폴백/프로바이더)
- `sab/screener/kis_screener.py` … KR 거래량 랭킹(캐시 TTL)
- `sab/screener/kis_overseas_screener.py` … US 랭크(거래량/시가총액/거래대금) — 환경에 따라 조정 필요
- `sab/screener/overseas_screener.py` … US 기본 목록(해외 랭크 실패 시 대체)
- `sab/signals/indicators.py` … EMA/RSI/ATR/SMA 등 지표 계산
- `sab/signals/evaluator.py` … 기본 Buy 평가/스코어링(EMA20/50 + RSI30 재돌파)
- `sab/signals/sell_rules.py` … Sell/Review 규칙(EMA20/50 + ATR 트레일)
- (계획) `sab/signals/hybrid_*` … SMA20 + EMA10/21 기반 하이브리드 전략 모듈
- `sab/report/markdown.py` … Buy 리포트 작성기
- `sab/report/sell_report.py` … Sell/Review 리포트 작성기
- `sab/utils/market_time.py` … 미국 시장 개/폐장(ET) 헬퍼
- `sab/scan.py`, `sab/sell.py`, `sab/__main__.py` … 오케스트레이션/CLI

## 데이터 플로우(Scan)

1) 설정 → 유니버스 구성
- 워치리스트(파일) 및/또는 스크리너(KR KIS 랭크; US KIS 랭크 또는 기본 목록)
2) 시세 수집
- 티커별 JSON 캐시 읽기 → KIS(국내/해외) 호출 → 다중 기간 윈도우로 누적(≥ `MIN_HISTORY_BARS`) → 캐시 저장
- KIS 실패 시 KR 티커에 한해 PyKRX 폴백 시도 → 리포트 Appendix에 경고 기록
3) 평가
- (현재) EMA20/50 크로스, RSI 리바운드, ATR 기반 갭 임계, SMA200/기울기/유동성/ETF 필터 → 후보 스코어링/정렬
- (계획) SMA20 + EMA10/21 하이브리드 패턴(추세 지속 눌림, 스윙 하이 돌파, RSI 과매도 반등)을 선택 가능한 전략 모드로 제공
4) 리포트
- 헤더 메타데이터(프로바이더, 캐시 힌트, 개수), 후보 테이블/상세, 실패/주의 Appendix, 파일명 `YYYY‑MM‑DD.buy.md`

## 신뢰성

- 토큰 캐시: `data/kis_token_<env>.json`(만료 5분 전 갱신), 24시간 발급 정책 준수
- 레이트리밋: `EGW00201` 수신 시 지수형 백오프 + 요청 간 최소 간격(데모 기본 500ms)
- 캐시: KR `data/candles_<ticker>.json`, US `data/candles_overseas_<EXCD>_<SYMBOL>.json` 보관. 읽고 난 뒤 저장하는 패턴
- 부분 성공: 실패가 있어도 Appendix에 기록하며 리포트를 생성

## 설정 우선순위

1) `config.yaml`(프로젝트 기본) → 2) `.env`(로컬 오버라이드) → 3) CLI 플래그(최우선). 키 매핑은 docs/config-migration.md 참고

## 확장성

- 스크리너 확장(예: 밸류/RS 필터) — 설정 플래그로 제어
- RS 벤치마크: 지수 시리즈(KR: KOSPI/KOSDAQ, US: SPY/QQQ) 연동
- Entry 체크: 시장별 시초/1–15분 스냅샷 연동
