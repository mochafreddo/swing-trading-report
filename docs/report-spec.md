# 리포트 스펙 (Markdown)

생성 위치: `reports/YYYY-MM-DD.md` (중복 시 `-1`, `-2` suffix 부여)

## 1) 헤더 요약

- 실행 시각(KST)
- 총 평가 종목 수 / 후보 수
- 데이터 제공자(kis/pykrx), 캐시 사용 여부(`cache: hit/refresh/expired`)
- 오류/경고 요약(있을 경우)

예시

```
# Swing Screening — 2025-01-02
- Run at: 2025-01-02 15:38 KST
- Provider: kis (cache: hit)
- Universe: 28 tickers, Candidates: 6
- Notes: 2 tickers failed (see Appendix)
```

## 2) 후보 요약 테이블(선택)

- 컬럼: Ticker | Name | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap | Score
- Score: 추세(SMA200), 기울기, 모멘텀(RSI50 상향), 유동성, 변동성 적정 등의 간단 가중 합

예시

```
| Ticker | Name  | Price | EMA20 | EMA50 | RSI14 | ATR14 | Gap  | Score |
|--------|-------|------:|------:|------:|------:|------:|-----:|------:|
| 005930 | 삼성전자 | 75,000 | 74,500 | 73,800 | 52.1  | 1,230 | +0.8% | 6.2   |
```

## 3) 후보 상세 섹션

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

## 4) 보유/관심 섹션(선택)

- 워치리스트/보유 종목의 현 상태 요약(시그널 없어도)

## 5) 실패/보류(Appendix)

- 데이터 조회 실패, 계산 오류 등 발생 종목을 나열하여 투명성 확보
  - 필터 사유 표기 예: "신규상장(<N bars)", "SMA200 하회", "ETF 제외", "거래대금 미달" 등

예시

```
### Appendix — Failures
- 373220: KIS rate limit (retry later)
- 091990: Missing OHLCV for recent day
```

## 6) 포맷 규칙

- 숫자 포맷: 천단위 구분기호, 소수 1~2자리(지표)
- 날짜/시간: KST, ISO-like `YYYY-MM-DD HH:mm`
- 구분선/헤더 레벨 일관성 유지
