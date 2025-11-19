# Roadmap — Swing Trading Report (KR, On‑Demand)

목표: 필요할 때 실행하여 국내 주식 일봉 데이터를 수집·평가하고, 마크다운 리포트를 생성하는 로컬 CLI.
데이터 소스는 기본 KIS Developers, 옵션으로 PyKRX 폴백.

## v1 (MVP)

- 데이터
  - KIS 인증/토큰 발급 및 자동 갱신
  - 일봉(최소 200개) 조회 + 간단 캐시(JSON/SQLite)
- 신호/평가
  - EMA(20/50), RSI(14), ATR(14), 갭 필터
- 리포트
- Buy Report: `reports/YYYY-MM-DD.buy.md` 생성
- 헤더 요약 + 후보 상세(근거/지표/리스크 가이드)
- 사용성/설정
  - `.env` 기반 설정(KIS 키, REPORT_DIR, SCREEN_LIMIT 등)
  - CLI: `uv run -m sab scan [--limit N] [--watchlist PATH]`
- 개발환경
  - uv 프로젝트(`pyproject.toml`, `uv.lock`) 정리
  - README, docs/kis-setup.md, docs/report-spec.md 반영

수용 기준(요약)

- `uv run -m sab scan` 실행 시 오류 없이 리포트가 생성된다.
- KIS로 워치리스트 종목의 일봉을 조회한다(모의/실전 택1).
- 기본 30개 이하 종목 평가를 2분 내 완료한다(캐시 활용 시).

## v1.1

- 스크리너/정렬
  - 거래대금/유동성 기준 상위 N 자동 선택(옵션)
  - 간단 점수화 및 요약 테이블 추가
- 리더(선도주) 보완
  - 최소 가격(MIN_PRICE) 적용, ETF/ETN/레버리지 제외 기본화
  - (선택) 상대강도(RS: 종목/지수, 20~60일) 점수 도입 및 상위 분위 통과
- 설정 고도화
  - `config.yaml` 도입(.env 병행)
  - 캐시 TTL/폴더 경로 설정화
- 신뢰성
  - KIS 실패 시 PyKRX 폴백(리포트 경고 표기)
  - 실패/보류 Appendix 섹션 자동 생성
- 보유/매도 평가(초판)
- 보유 목록 입력(예: `holdings.yaml`) 설계 및 로딩
- 매도/보류 신호 규칙(무효화: EMA 되크로스/RSI 붕괴/ATR 스탑/시간 스탑) 정의
- `sab sell` 서브커맨드 구현 → `reports/YYYY-MM-DD.sell.md` 생성

## v1.2

- 전략/리포트 고도화
  - SMA+EMA 하이브리드 스윙 전략 정식 도입(문서: `docs/swing-trading-manual.md`, 설계: `docs/design/signals.md`)
  - 전략 모드 설정(`strategy.mode`: 기본 EMA 크로스 vs 하이브리드) 설계 및 구현
  - Buy/Sell 리포트에 하이브리드 패턴/체크리스트 필드 추가
- 시각화/분석
  - 차트 이미지(옵션) 생성 후 리포트에 첨부/링크
  - 간단 백테스트 스냅샷(최근 n건 신호 요약)
- 품질/성능
  - 로깅/진행률 표시, 병렬화(레이트리밋 준수)
  - 코드 구조 리팩터링(커넥터/도메인/리포트/전략 모듈화 강화)
- 해외 주식(US) 지원(초판)
  - 일봉 조회 + 스크리너(간단) + 시간대/심볼/휴장일 처리
- 장 오픈 진입 체크(리포트 연계)
- `sab entry` 서브커맨드 구현 → `reports/YYYY-MM-DD.entry.md`
- 전일 Buy Report 입력 → 다음 날 시초가/장초 5–15분 확인 로직 → 가이드 생성

## v2 (선택)

- 간단 GUI 또는 메뉴바 토글
- 다계정/다유저화 전제 설계(범위 외)

## 마일스톤

- M1: KIS 인증 + 일봉 조회 + 캐시
- M2: 지표 계산 + 후보 선별 + Buy 리포트 기본 서식
- M3: CLI 옵션·워치리스트 지원 + 문서 정리
- M4: 스크리너/정렬 + Appendix + 설정 고도화
- M5: 보유/매도 평가(`sell`) + 시각화/백테스트 + 성능/리팩터링
- M6: 해외 주식(US) 지원 + 장 오픈 진입 체크(`entry`)
