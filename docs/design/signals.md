# 설계 — 시그널(매수 & 매도)

본 문서는 매수 후보 평가와 매도/보류 규칙, 그리고 조정 가능한 임계치를 정의합니다.

## 매수(Buy) 평가

입력: 티커별 최소 `MIN_HISTORY_BARS` 봉(기본 200).

공통 지표:

- EMA, SMA, RSI(14), ATR(14)
- 거래대금/거래량(스크리너 및 유동성 필터용)

전략은 **여러 모드**로 확장 가능하며, 현재 설계는 다음 두 가지를 기본으로 합니다.

### 1) 기본 EMA 크로스 전략(현 구현)

- 지표: EMA(20/50), RSI(14), ATR(14), SMA(200)

필터(별도 표기 없으면 모두 통과 필요)

- EMA 크로스: 당일 EMA20 > EMA50 이고, 전일 EMA20 ≤ EMA50
- RSI 리바운드: RSI14가 30 위로 재돌파하되 70 미만 유지
- ATR‑갭: |시가−전일종가|/전일종가 ≤ `GAP_ATR_MULTIPLIER × ATR / 전일종가`(폴백: 고정 3%)
- SMA200 컨텍스트(옵션): 가격/EMA20/EMA50 모두 SMA200 상방
- EMA 기울기(옵션): EMA20/EMA50이 전일 대비 상승
- 유동성 하한: 최근 20봉 평균(가격×거래량) ≥ `MIN_DOLLAR_VOLUME`
- ETF/ETN/레버리지/인버스 제외(옵션, 명칭 휴리스틱)

스코어링: 교차/RSI/SMA200/기울기/갭/유동성/RS 여부를 가산. RS(상대강도)는 N일 수익률을 벤치마크와 비교(지수 시리즈 연동 전까지 설정값 사용)

Config keys (selection):

- `strategy.min_history_bars`, `strategy.gap_atr_multiplier`
- `strategy.use_sma200_filter`, `strategy.require_slope_up`, `strategy.exclude_etf_etn`
- `screener.min_dollar_volume`, `screener.min_price`
- `strategy.rs_lookback_days`, `strategy.rs_benchmark_return`

### 2) SMA+EMA 하이브리드 전략(계획)

전략 개요는 `docs/swing-trading-manual.md`를 따르며, 핵심은 다음과 같습니다.

- 지표: SMA20(중기 추세), EMA10/EMA21(단·중기 모멘텀), RSI(14), 거래량/거래대금
- 패턴:
  - 추세 지속 + 눌림 반등(Trend continuation + pullback bounce)
  - 스윙 하이 돌파(Swing high breakout)
  - RSI 과매도 반등(RSI oversold reversal)
- 공통 필터:
  - 가격 > SMA20 (필수)
  - EMA10 ≥ EMA21 (모멘텀 유지) — 일부 패턴에서 필수
  - RSI 45–60(스윙 존) 또는 30–40 → 40 상향(과매도 반등)
  - 과도한 매도 거래량/갭 필터(ATR 또는 고정 %)

Config 예시(계획):

- `strategy.mode` = `ema_cross` \| `sma_ema_hybrid`
- `strategy.hybrid.sma_trend_period` (기본 20)
- `strategy.hybrid.ema_short_period` (기본 10)
- `strategy.hybrid.ema_mid_period` (기본 21)
- `strategy.hybrid.rsi_zone_low`, `strategy.hybrid.rsi_zone_high`
- `strategy.hybrid.pullback_max_bars` 등

## 매도/보류 규칙

입력: 보유 목록(`holdings.yaml`). 지표: EMA(20/50), RSI(14), ATR(14), SMA(200)

규칙(강한 신호 우선)
- SELL
  - ATR 트레일 스톱 충족: `close ≤ close − k×ATR` (k=`SELL_ATR_MULTIPLIER`)
  - RSI 급락: RSI < `SELL_RSI_FLOOR_ALT`(예: 30)
  - EMA 데드크로스: EMA20이 EMA50 하향 돌파
- REVIEW
  - 가격이 두 EMA 아래(SELL이 아닐 때)
  - RSI < `SELL_RSI_FLOOR`(예: 50)
  - SMA200 하방 컨텍스트(`SELL_REQUIRE_SMA200`가 true일 때)
  - 시간 스톱: `entry_date`로부터 경과일 ≥ `SELL_TIME_STOP_DAYS`
- 수동 오버라이드: `stop_override`, `target_override`는 리포트에 반영

Config keys:
- `SELL_ATR_MULTIPLIER`, `SELL_TIME_STOP_DAYS`, `SELL_REQUIRE_SMA200`
- `SELL_EMA_SHORT`, `SELL_EMA_LONG`, `SELL_RSI_PERIOD`
- `SELL_RSI_FLOOR`, `SELL_RSI_FLOOR_ALT`, `SELL_MIN_BARS`

출력: 상태/사유/스톱·타깃 가이드/P&L%를 포함한 표, 요약 테이블과 종목별 상세 섹션
