# 설계 — 미국 보유 종목 매도 로직

목표

- `holdings.yaml`에 있는 기존 미국 주식 포지션(`SYMBOL.EXCH` 형식, 예: `AAPL.NASD`, `JNJ.NYSE`)에 대해 `SELL`, `REVIEW`, `HOLD`를 판정합니다.

데이터 소스

- KIS Developers 해외 일봉 API: `/uapi/overseas-price/v1/quotations/dailyprice` (TR `HHDFS76240000`)
- 티커 파싱: `SYMBOL.SUFFIX` → 접미사를 KIS `EXCD` 코드로 매핑
  - `US|NASDAQ|NASD|NAS` → `NAS`
  - `NYSE|NYS` → `NYS`
  - `AMEX|AMS` → `AMS`
- 캐시 키: 국내 티커와 충돌을 피하기 위해 `candles_overseas_{EXCD}_{SYMBOL}` 사용
- 폴백: PyKRX는 국내 전용이므로 해외 심볼에는 폴백하지 않습니다.

규칙(기존 공통 매도 로직 재사용)

- 지표: 일봉 기준 EMA(20/50), RSI(14), ATR(14), SMA(200)
- SELL
  - ATR 트레일링 스탑: `trail = 진입 이후 최고 종가 − k × ATR`, `close <= trail`이면 SELL (`k = sell.atr_trail_multiplier`)
    - `진입 이후 최고 종가`는 `holdings.yaml`의 `entry_date`를 기준으로 계산하며, 누락/오류 시 최근 구간 기반 폴백 사용
  - RSI 붕괴: `RSI < sell.rsi_floor_alt` (기본 30)
  - EMA 데드크로스: EMA20이 EMA50 아래로 하향 교차
- REVIEW
  - (이미 SELL이 아닌 경우) 가격이 두 EMA 아래
  - `RSI < sell.rsi_floor` (기본 50)
  - `sell.require_sma200 = true`일 때 SMA200 컨텍스트 이탈
  - 시간 스탑: `days_since_entry >= sell.time_stop_days`
- 종목별 오버라이드는 존중됩니다: `stop_override`, `target_override`

설정

- 공통 키(US에도 동일 적용)
  - `sell.atr_trail_multiplier`, `sell.time_stop_days`, `sell.require_sma200`
  - `sell.ema_short`, `sell.ema_long`, `sell.rsi_period`
  - `sell.rsi_floor`, `sell.rsi_floor_alt`, `sell.min_bars`
- 시장별(US) 스크리닝 임계치는 이미 `config.yaml`의 `screener.us.*`에 존재하며, 초기에는 별도 매도 전용 오버라이드가 필요하지 않습니다.

환율 처리

- `uv run -m sab sell`은 `uv run -m sab scan`과 동일하게 `sab.fx.resolve_fx_rate`를 재사용하며 `FX_MODE`/`USD_KRW_RATE`를 따릅니다.
- `FX_MODE=kis`이고 `KISClient`를 사용할 수 있으면, `overseas-price/v1/quotations/price-detail`에서 USD/KRW를 자동 조회하고 캐시합니다.
- Sell 리포트 헤더에는 현재 환율 소스를 출력하며, USD 표시 가격은 요약 표와 상세 섹션 모두에서 `$X (₩Y)` 형태로 표기됩니다.

리포트 출력

- 국내와 동일한 마크다운 구조: 요약 표 + 보유 종목별 상세
- 통화는 `holdings.yaml`의 `entry_currency`를 사용합니다. USD 보유 종목은 환율이 있을 때 USD와 환산 KRW를 함께 표시합니다.

엣지 케이스 / 복원력

- 데이터 부족: 사유를 남기고 `REVIEW`로 표시
- API 오류: 가능하면 캐시 일봉을 사용하고, 이슈를 Appendix에 기록
- 해외 폴백 없음: `EXCD`가 있는 심볼은 PyKRX 폴백을 건너뜀

향후 개선

- 리포트 헤더에 미국장 장중/장마감 상태(오픈/클로즈) 인식 추가
- 필요 시 시장별 매도 오버라이드 추가(예: US 전용 ATR 배수)
