# 리포트 스펙 (Markdown)

리포트는 목적별로 분리됩니다. 각 파일은 동일 날짜에 여러 번 생성될 수 있으므로 필요 시 `-1`, `-2` suffix가 붙습니다.

- Buy Report: `reports/YYYY-MM-DD.buy.md`
- Sell/Review Report: `reports/YYYY-MM-DD.sell.md`
- Entry Check Report: `reports/YYYY-MM-DD.entry.md`

## A) Buy Report — 스윙 후보 평가

### 1) 헤더 요약

- 실행 시각(로컬 타임존 라벨)
- 총 평가 종목 수 / 후보 수
- 데이터 제공자(kis/pykrx), 캐시 사용 여부(`cache: hit/refresh/expired`), 마켓(`KR`/`US`)
- 오류/경고 요약(있을 경우)

예시

```
# Swing Screening — 2025-01-02
- Run at: 2025-01-02 15:38 KST
- Provider: kis (cache: hit)
- Universe: 28 tickers, Candidates: 6
- Notes: 2 tickers failed (see Appendix)
```

### 2) 후보 요약 테이블(선택)

- 컬럼: Ticker | Name | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap | Score
- Score: 추세(SMA200), 기울기, 모멘텀(RSI50 상향), 유동성, 변동성 적정 등의 간단 가중 합

예시

```
| Ticker | Name  | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap  | Score |
|--------|-------|------:|------:|------:|------:|------:|-----:|------:|
| 005930 | 삼성전자 | 75,000 | 74,500 | 73,800 | 52.1  | 1,230 | +0.8% | 6.2   |
```

### 3) 후보 상세 섹션

- 섹션 제목: `## [매수 후보] {TICKER} — {NAME}`
- 필드
  - 가격 스냅샷: 종가, 전일 대비, 고가/저가
  - 추세: EMA20/EMA50 관계, SMA200 상방 여부
  - 모멘텀: RSI(14) 위치/재돌파 여부
  - 변동성: ATR(14)
  - 갭: 전일 종가 대비 %, 갭 임계(ATR×배수) 통과 여부
- 리스크 가이드(선택): ATR 기반 스톱/타겟 예시
- 점수: 구성 요소별 점수 요약(추세/기울기/모멘텀/유동성/변동성)
- 코멘트: 간단 메모

예시

```
## [매수 후보] 005930 — 삼성전자
- Price: 75,000 (+0.8% d/d) H: 75,800 L: 74,200
- Trend: EMA20(74,500) crossed > EMA50(73,800)
- Momentum: RSI14=52.1 (↑ above 50)
- Volatility: ATR14=1,230
- Gap: +0.8% vs prev close
- Risk guide: Stop 73,800 / Target 78,500 (~1:2)
```

### 4) 보유/관심 섹션(선택)

- 워치리스트/보유 종목의 현 상태 요약(시그널 없어도)

## B) Sell/Review Report — 보유 종목 상태

### 1) 헤더 요약

- 실행 시각(로컬 타임존 라벨)
- 평가 대상 보유 종목 수
- 규칙/임계치 요약(ATR, RSI, 시간 스탑 등)

### 2) 보유 평가 표(요약)

- 컬럼: Ticker | Entry | Last | P/L% | State(HOLD/REVIEW/SELL) | Reason | Notes
- Reason 예: Invalidation(EMA20<EMA50, Close<EMA50, RSI<50/30), Risk(ATR trail hit), Time(N bars elapsed)

### 3) 종목별 상세

- 최근 OHLC 스냅샷, EMA20/EMA50/SMA200, RSI14, ATR14
- 규칙 평가 결과와 우선 사유
- 리스크 가이드: ATR 기반 스톱/부분청산/전량 기준 예시

### 4) Appendix — 조회 실패/보류

- 데이터 부족/호출 실패/계산 오류 종목을 나열

## C) Entry Check Report — 익일 시초 체크

### 1) 헤더 요약

- 실행 시각(로컬 타임존 라벨)
- 참조한 Buy Report 경로/생성 시각
- 체크 규칙 요약(갭 ATR 배수, ORH 기준 등)

### 2) 후보별 결과 요약

- 컬럼: Ticker | Prev Close | Open | Gap% | ATR | Decision(OK/Wait/Avoid) | Rationale
- 규칙 예:
  - Avoid: |Gap| > ATR×배수(과도 갭)
  - OK: ORH 돌파(전일 고가 상향 돌파) 또는 첫 눌림 후 재상승 확인
  - Wait: 첫 5–15분 대기 후 재확인 필요

### 3) 상세 섹션(선택)

- 장초 1/3/5/15분 스냅샷 요약, 코멘트

### 4) Appendix — 실패/보류

- 실시간/지연데이터 부재, 휴장/조기폐장, 데이터 오류 등

예시(Appendix 포맷 예)

```
### Appendix — Failures
- 373220: KIS rate limit (retry later)
- 091990: Missing OHLCV for recent day
```

## 공통 포맷 규칙

- 숫자 포맷: 천단위 구분기호, 소수 1~2자리(지표)
- 날짜/시간: 로컬 타임존 라벨, ISO-like `YYYY-MM-DD HH:mm z`
- 구분선/헤더 레벨 일관성 유지

## 7) 장 오픈 진입 체크(옵션)

- 입력: 전일 리포트 후보 + 다음 날 시초가/장초 5–15분 요약
- 표기: `Next-day Entry: OK / Wait (ORH break) / Avoid (Excessive gap)` 등 간단 지침
