# 📄 PRD — Swing Trading Report (Multi‑Market: KR/US, Local + Scheduled)

## 1. 목적

- 문제: 차트를 계속 보지 않고도 스윙 신호를 간단히 파악하고 싶다.
- 목표: 국내(KRX/KOSDAQ)와 미국(US) 등 여러 시장 종목을 수집/평가하여 결과를 마크다운 파일로 생성한다.
- 실행 방식: 기본은 로컬 수동 실행(온디맨드). 이후 자동 실행(스케줄러)로 구동하고 요약본을 텔레그램/슬랙 등으로 받아본다.

---

## 2. 범위

- In-Scope
  - 시장: 한국 주식(KRX, KOSDAQ) + 미국 주식(US) (필요 시 추가 시장 확장).
  - 데이터: 한국투자증권 KIS Developers(Open API) 기본(국내/해외). (옵션) PyKRX 폴백은 국내(KR)만.
  - 전략: EMA(20/50) 크로스, RSI(14) 시그널, ATR 기반 리스크 가이드, 갭 필터 등 기본 스윙 규칙.
  - 출력: 마크다운 리포트(요약 + 후보종목 목록 + 근거/지표) 파일 생성 + (선택) 메시징 채널로 요약 발송.
  - 실행: 사용자가 원할 때 명령 1회로 수행(기본) + (선택) 스케줄러 기반 자동 실행.

- Out-of-Scope
  - 자동 매매.

---

## 3. 사용자

- 단일 사용자(작성자). 요구사항:
  - 워치리스트 또는 간단 스크리너로 소수 종목만 빠르게 점검.
  - 실행 즉시 결과를 읽기 쉬운 마크다운으로 확인.

---

## 4. 요구사항

### 기능 요구사항

1) 데이터 수집

- 기본: KIS Developers REST API로 일봉(국내/해외) 최소 200개 이상 조회(지표 계산용).
- 입력 대상: 수동 워치리스트 파일(예: `watchlist.txt`) + 선택적 자동 스크리너 상위 N개(기본 20~30개, 설정 가능).
- API 호출 제한 고려해 간단 캐시(로컬 JSON/SQLite) 지원.
- 히스토리 누적 수집: KIS 일봉 API(국내/해외)는 호출당 최대 100봉 제한이 있으므로, 날짜 구간을 나눠 여러 번 호출하여 `min_history_bars`(권장 200) 이상을 확보한다. 첫 호출은 최근 구간, 이후 가장 오래된 일자 이전으로 창을 이동하며 누적. 이후 실행에서는 증분(최근 구간)만 갱신.
- 토큰 발급/갱신: KIS OAuth/인증 흐름 적용, 만료 시 자동 재발급 시도 및 실패 내역 리포트 표기.
- 대체: KIS 호출 실패 시(네트워크/인증/임시 장애) PyKRX로 폴백 옵션 제공(정합성 경고 문구 포함).

2) 시그널 엔진(개선 반영)

- 진입 코어: EMA(20/50) 골든크로스 + RSI(14) 30 상향 재돌파(+ RSI<70 유지)
- 장기 추세 필터: 가격·EMA20·EMA50 모두 SMA200 위(옵션)
- 갭 필터: 고정 ±3% 대신 ATR 기반 임계값(예: |갭| ≤ 1×ATR/전일종가)
- 품질 필터: 최소 거래대금(최근 20일 평균), 저유동/신규상장 제외(최근 N봉 미만 제외), ETF/ETN/레버리지/인버스 제외 옵션
- 크로스 품질: EMA20·EMA50 기울기>0, 신호일 종가가 두 EMA 위(옵션)
- 리스크 가이드: ATR(14) 기반 스톱/타깃(~1:2) 산출
- 점수화: 추세(SMA200), 기울기, 모멘텀(RSI50 상향), 유동성, 변동성 적정 등 가중 합산으로 후보 정렬
- 판단 시점: 각 시장의 거래일/시간대 기준 최신 확정 일봉(종가) 기준

2-1) 매도/보유 평가(보유 종목)

- 입력: `holdings.yaml`(또는 `.json`), 필드 예: `ticker, quantity, entry_price, notes`
- 무효화 기준(예): EMA20/50 되크로스, 종가 EMA20/EMA50 하향 이탈, RSI50/30 재하락
- 리스크 기준(예): ATR(14) 트레일링 스탑(예: 1×ATR), 시간 스탑(N거래일 경과)
- 결과: 리포트에 Sell/Review 섹션으로 표기(사유/근거/가이드)

3) 리포트 생성(마크다운, 분리 설계)

- Buy Report (장 마감 후)
  - 파일: `reports/YYYY-MM-DD.buy.md`
  - 항목: 실행 요약, 매수 후보(티커/핵심 근거/지표 스냅샷/리스크 가이드), 점수/정렬
- Sell/Review Report (장 시작 시)
  - 파일: `reports/YYYY-MM-DD.sell.md`
  - 항목: 보유 종목 상태(HOLD/REVIEW/SELL), 사유(무효화/리스크/시간), ATR 트레일/커스텀 스톱/타깃, 노트
- Entry Check Report (옵션, 장초 재확인)
  - 파일: `reports/YYYY-MM-DD.entry.md`
  - 입력: 전일 Buy Report + 당일 시초가/장초 5–15분 요약
  - 표기: Next‑day Entry = OK / Wait (ORH break) / Avoid (Excessive gap)

4) 구성/입력

- 원칙: 기본값/임계치/비시크릿은 `config.yaml`에 두고, 로컬 오버라이드와 시크릿은 `.env`(또는 환경변수)로 관리한다.
  - 우선순위: `config.yaml` → `.env` → CLI (CLI가 최우선)
  - 동일 키가 여러 곳에 정의되면 우선순위가 높은 값으로 덮어쓴다(로컬 실험/환경 차이 흡수 목적).
  - 보안 정책: KIS 시크릿(`KIS_APP_KEY`, `KIS_APP_SECRET`)은 `.env`/환경변수로만 허용하며, YAML에 저장하는 것은 금지한다(감지 시 실행 실패).
- `.env` 권장 키(예시, 시크릿)
  - `KIS_APP_KEY=...`
  - `KIS_APP_SECRET=...`
  - (선택) `SLACK_WEBHOOK_URL=...` 또는 `SLACK_BOT_TOKEN=...`
  - (선택) `TELEGRAM_BOT_TOKEN=...`
- `config.yaml` 권장 항목(예시, 비시크릿)
  - 시장/유니버스: `markets: [KR, US]`
  - 데이터 제공자: `data_provider: kis` (또는 `pykrx` — KR 한정 폴백)
  - 저장소: `report_dir: reports`, `data_dir: data`
  - 수집/호출: `min_history_bars: 200`, `kis_min_interval_ms: 500`
  - 스크리너: `screener: { enabled: true, limit: 30, only: false }`
  - 전략/필터: `strategy: { use_sma200_filter: true, gap_atr_multiplier: 1.0, min_dollar_volume: 5000000000, exclude_etf_etn: true, require_slope_up: true, min_price: 1000 }`
  - 리포트 옵션: `entry_check_enabled: false`
  - 알림(선택): `notifications: { enabled: false, telegram: { enabled: false, chat_id: "..." }, slack: { enabled: false } }`
- 워치리스트: `watchlist.txt`(줄당 1티커) 또는 `watchlist.yaml`(메모 포함) 지원.

5) 자동 실행/알림(요약 전송)

- 자동 실행: 외부 스케줄러(cron/launchd/GitHub Actions 등)로 CLI를 비대화형 실행할 수 있어야 한다.
- 요약 생성: 실행 결과를 짧은 텍스트로 요약한다(예: 날짜/시장, 상위 N개 후보, 보유 종목의 SELL/REVIEW 요약, 생성된 리포트 파일 경로).
- 전송 채널(옵션): 텔레그램/슬랙을 우선 지원하고, 채널은 확장 가능하게 설계한다.
- 실패 처리: 알림 전송 실패가 리포트 생성을 막지 않으며, 실패 원인은 로그 또는 리포트에 명시한다.
- 시크릿/설정:
  - 시크릿(예: 텔레그램 봇 토큰, 슬랙 웹훅/봇 토큰)은 `.env`에만 둔다.
  - 비시크릿(예: 텔레그램 chat_id, 알림 활성화 토글)은 `config.yaml`에 둔다.

### 비기능 요구사항

- 성능: 20~30개 종목 기준 1~2분 내 완료.
- 비용: 0원(로컬) + API 무료 한도 내.
- 보안: 시크릿은 `.env`에 저장(버전관리 제외). 필요 시 macOS Keychain 연동 옵션.
- 유지보수성: 단순한 파이썬 스크립트/모듈로 구성.

---

## 5. 성공 지표

- 리포트 가독성: 리포트만으로 5분 내 의사결정 가능.
- 안정성: API 실패 시 부분 결과라도 리포트 생성(실패 내역 명시).

---

## 6. 리스크와 대응

- KIS 인증/토큰 만료: 만료/권한 오류 시 자동 재발급 시도, 실패 시 폴백(PyKRX) 또는 실패 내역을 리포트에 표시.
- API 제한/변경: 호출 간 지연/재시도, 캐시 활용, 커넥터 추상화로 교체 용이. 초당 거래건수 제한(EGW00201) 발생 시 요청 간격(`kis_min_interval_ms`)과 백오프 재시도를 적용.
- 종목/티커 표준화: KRX/KOSDAQ 코드체계 차이를 맵핑 테이블로 보정.
- 공휴일/조기폐장: 당일 시세 불가 시 전일 기준으로 동작, 리포트에 표시.
- 해외시장: 시간대/휴장일 상이 → 미국 장 정보(KIS 해외주식) 기준으로 스케줄/시차 적용

---

## 7. 아키텍처(로컬)

- 구성요소
  - CLI 스크립트: `scan`(Buy), `sell`(보유 평가), `entry`(익일 시초 체크; 옵션)
  - 데이터 계층: KIS 클라이언트(토큰 발급/일봉 조회) + 간단 캐시(JSON/SQLite, `./data/`).
  - 대체 경로(옵션): PyKRX 클라이언트.
  - 리포트 출력: `./reports/` 폴더에 마크다운 저장.
- (선택) 자동화/알림
  - 스케줄러: cron/launchd/GitHub Actions 등 외부 스케줄러로 CLI를 비대화형 실행
  - 알림 채널: 텔레그램/슬랙 등으로 리포트 요약 전송(확장 가능)
- 설정
  - `.env`: 시크릿/환경별 값(예: `KIS_APP_KEY`, `KIS_APP_SECRET`, (선택) `SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`)
  - `config.yaml`: 비시크릿 설정(시장/전략/필터/입출력/알림 토글 등)
- 개발도구/의존성 관리
  - uv 기반 프로젝트/의존성/가상환경 관리(`pyproject.toml`, `uv.lock`, `.venv/`).
  - 실행은 `uv run -m sab scan` 형태로 통일.

---

## 8. 로드맵

- v1 (MVP)
  - KIS 연동: 앱키/시크릿 기반 인증, 일봉 조회 구현. 토큰은 로컬 파일 캐시로 1일 1회 발급 원칙 준수.
  - CLI `scan` 구현: 워치리스트 입력 → 지표 계산 → 마크다운 리포트 저장.
  - 간단 스크리너(선택): 거래대금/유동성 기준 상위 N.
  - 캐시: 일봉 로컬 저장(유효기간 1일).
  - uv 도입: `pyproject.toml`/`uv.lock` 생성, `uv run` 표준화.

- v1.1
  - 리포트 서식 개선(요약 표, 섹션 앵커, 간단 점수화).
  - 설정 파일 `config.yaml` 지원(비시크릿) + `.env` 로컬 오버라이드/시크릿 지원. 우선순위는 `config.yaml → .env → CLI`로 통일.
  - 리더 보완(최소 가격, (선택) RS 점수) 및 보유/매도 평가(초판)
  - 해외주식(미국) 일봉/스크리너(간단) 지원(시간대/심볼 규칙 반영)

- v1.2
  - 자동 실행 가이드/템플릿 제공(cron/launchd/GitHub Actions 등)
  - 리포트 요약본 알림(텔레그램/슬랙) 전송(옵션)

---

## 9. 사용 방법(초안, uv + KIS)

- 의존성: uv(패키지/프로젝트 매니저). Python은 uv가 자동 관리 가능.
  - 설치(macOS): `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - 버전 확인: `uv --version`
- 초기화(최초 1회)
  - 프로젝트 생성/전환: 리포지토리 루트에서 실행
  - 프로젝트 설정 생성: `uv init` (기존 repo면 `pyproject.toml`만 수동 추가 예정)
  - 필요한 라이브러리 추가 예: `uv add pandas numpy requests python-dotenv`
  - 잠금파일/동기화: `uv lock && uv sync`
- 환경설정:
  - `.env`에 시크릿 입력(예: `KIS_APP_KEY`, `KIS_APP_SECRET`, (선택) `SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`)
  - `config.yaml`에 비시크릿 설정 입력(예: `markets: [KR, US]`, `data_provider: kis`, 스크리너/전략/출력 경로, 알림 토글 등)
- 실행 예시(uv run)
  - 기본 실행: `uv run -m sab scan`
  - 스크리너 크기: `uv run -m sab scan --limit 30`
  - 워치리스트 지정: `uv run -m sab scan --watchlist watchlist.txt`
  - 프로젝트 의존성 없이 단독 스크립트 실행(옵션): `uv run --no-project path/to/script.py`
- 결과: Buy 리포트 `reports/YYYY-MM-DD.buy.md` 생성.

---

## 10. 수용 기준(AC)

- AC1: `uv run -m sab scan` 실행 시 오류 없이 Buy 리포트(`YYYY-MM-DD.buy.md`)를 생성한다.
- AC2: KIS로 워치리스트 종목의 일봉을 성공적으로 조회한다(모의/실전 중 택1 환경).
- AC3: 기본 30개 이하 종목 평가를 2분 내 완료한다(캐시 활용 시).
- AC4: Buy 리포트에 각 후보의 근거(EMA/RSI/ATR/갭) 요약이 포함된다.
- AC5: `uv run -m sab sell` 실행 시 보유 평가 리포트(`YYYY-MM-DD.sell.md`)를 생성한다.
- (예정) AC6: `uv run -m sab entry` 실행 시 익일 시초 체크 리포트(`YYYY-MM-DD.entry.md`)를 생성한다.
- AC7: 설정 파일만으로 대상 시장(KR/US), 대상 종목 수, 출력 경로, 데이터 제공자(kis/pykrx)를 변경할 수 있다.
- (예정) AC8: 스케줄러로 비대화형 실행해도 동일하게 리포트를 생성한다.
- (예정) AC9: 알림을 활성화하면 리포트 요약본이 텔레그램/슬랙으로 전송된다.

---

## 11. 메모/오픈 결정 사항

- KIS 등록/환경: 계정/앱 등록, 앱키·시크릿 발급, 모의/실전 도메인 확인(문서 기준), IP/리다이렉트 설정 필요 시 반영.
- 비용: 개인 개발·모의투자 데이터 조회는 무료(정책 변동 가능, KIS 문서 확인). 실거래/실시간은 별도 제약 가능.
- 티커 포맷(숫자코드 vs 종목명) 표준 결정 및 맵핑.
- 캐시 저장 포맷(JSON vs SQLite) 선택.
- uv 설정: `pyproject.toml`의 최소 Python 버전(예: `>=3.13`), 프로젝트 스크립트 엔트리 정의 여부.
