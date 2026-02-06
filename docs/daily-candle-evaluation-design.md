# 일봉 평가 설계 (KIS + 하이브리드 전략)

## 1. 배경과 문제

프로젝트는 KIS(및 PyKRX)에서 일봉 OHLCV를 받아 스윙 트레이딩 로직(매수/매도, 하이브리드 전략, 리포트)을 실행합니다.

실무에서 다음 두 가지 문제가 발생합니다.

- KIS 일봉 API는 **장이 진행 중이어도 “오늘”을 나타내는 마지막 캔들**(장중 스냅샷)을 반환할 수 있습니다.
- 현재 구현은 암묵적으로 **`candles`의 마지막 원소 = 완전히 종료된 일봉**이라고 가정하고 `candles[-1]`을 기준으로 평가합니다.

EOD(종가) 기반 스윙 전략에서는 다음이 필요합니다.

- 시장이 열려 있을 때는 *어제 종가*처럼 **완료된 일봉만 기준으로 평가**해야 합니다.
- 미완성 장중 캔들이 EMA/RSI/ATR 조건이나 하이브리드 패턴 탐지에 섞이지 않도록 해야 합니다.

이 문서는 해당 동작을 개선하는 방법을 정의합니다.

## 2. KIS 일봉 동작(요약)

KIS 예제(MCP 경유)와 실제 관측 데이터를 기준으로 정리하면 다음과 같습니다.

- **국내 주식**
  - API:
    - `inquire_daily_price` (`/uapi/domestic-stock/v1/quotations/inquire-daily-price`)
    - `inquire_daily_itemchartprice` (`/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, `FID_PERIOD_DIV_CODE = D`)
  - 문서는 일/주/월 OHLC 시계열을 설명하지만, **“오늘 봉은 장 종료 후에만 포함된다”**는 보장을 명시하지 않습니다.
  - 실무상 국내 일봉 API가 EOD처럼 동작하는 경우가 많지만, 이를 절대 보장으로 의존할 수는 없습니다.

- **해외 주식**
  - API: `dailyprice` (`/uapi/overseas-price/v1/quotations/dailyprice`)
  - 관측상(예: TMO NAS/NYSE 데이터), 미국 정규장 진행 중 KIS는 **당일 봉**을 반환합니다.
    - 날짜 == 오늘
    - 최근 대비 매우 작은 거래량
    - 고가/저가/종가가 장중에 계속 변동
  - 이 봉은 EOD 관점에서 **완료된 일봉이 아닙니다.**

- **PyKRX**
  - 국내 EOD 소스이며, 반환되는 캔들은 **완료된 일봉**입니다.

결론:

- **`candles[-1]`이 항상 완전 종료 봉이라고 가정할 수 없습니다.**
- 다음 조건을 바탕으로 `candles[-1]` 또는 `candles[-2]`(필요 시 그 이전)를 선택해야 합니다.
  - 거래소 장 상태(장중 vs 장마감 후)
  - 마지막 봉 거래량 특성
  - 데이터 소스(KIS vs PyKRX)

## 3. 설계 목표

1. **완료된 일봉만 사용**
   - 정규장 중에는 전략 평가를 **전일 종가** 기준으로 수행
   - 장마감 이후(다음 장 시작 전)에는 가장 최신 완료봉(마지막 원소) 사용

2. **장중 아티팩트 격리**
   - 얇은 거래량의 부분 당일 봉을 EMA/RSI/ATR 및 하이브리드 패턴의 완전 EOD 봉으로 취급하지 않음

3. **소스 인지형 동작**
   - PyKRX(EOD)는 항상 마지막 봉 사용 가능
   - KIS 일봉 API는 장중 가능성을 전제로 추가 검증 적용

4. **작고 국소적인 변경**
   - `indicators.py` 재설계는 하지 않음
   - 재사용 가능한 작은 헬퍼로 동작을 구현하고 의사결정 레벨 함수만 조정

5. **명시적이며 테스트 가능**
   - KR/US, KIS/PyKRX, 장중/장마감 후 시나리오를 검증할 수 있는 단위/통합 테스트 케이스 제공

## 4. 핵심 개념: Evaluation Index + Option B 슬라이싱

### 4.1 평가 인덱스(`idx_eval`)

**평가 인덱스** 개념을 도입합니다.

- `idx_eval`은 전략 평가 시점에서 **유효한 최신 완료봉**의 인덱스입니다.
- 예시:
  - 2025-11-19 미국 장중:
    - `candles[-1]`은 당일(2025-11-19)로 아직 변동 중
    - `idx_eval`은 `len(candles) - 2`(2025-11-18)여야 함
  - 미국 장마감 후:
    - `candles[-1]`이 2025-11-19 완료봉
    - `idx_eval`은 `len(candles) - 1`

### 4.2 Option B: `idx_eval`까지 데이터 슬라이싱

“Option B” 패턴을 따릅니다.

- 패턴 함수 내부를 인덱스 인자로 변경하는 대신:
  - `idx_eval`을 한 번 계산
  - 모든 시퀀스를 **`idx_eval`까지만 포함**하도록 슬라이싱
    - `candles_eval = candles[: idx_eval + 1]`
    - `closes_eval = closes[: idx_eval + 1]`
    - `sma_eval = sma_trend[: idx_eval + 1]` 등
  - 패턴/매도 함수에는 `*_eval` 시퀀스만 전달
- 패턴/매도 함수 내부의 기존 로직은 그대로 유효
  - `idx = len(closes) - 1`
  - `today = candles[-1]`
  - `yest = candles[-2]`
  - 이제 이 값들은 원본의 마지막이 아니라 **선택된 평가 봉**을 의미

이 방식은 코드 변경 범위를 최소화하고 off-by-one 오류 위험을 줄입니다.

## 5. 헬퍼: `choose_eval_index`

장중/종가 결정 로직을 헬퍼로 중앙화합니다.

```python
def choose_eval_index(
    candles: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
    provider: str = "kis",
    now: datetime | None = None,
    lookback_for_volume: int = 5,
) -> int:
    ...
```

### 5.1 입력

- `candles`: 날짜 오름차순 OHLCV dict 리스트
- `meta`:
  - 종목별 메타데이터(선택)
    - `currency`: `"KRW" | "USD" | ...`
    - `exchange`: `"KRX" | "NAS" | "NYS" | ...`
    - `data_source` / `provider`: `"kis" | "pykrx" | ...` (EOD 전용 피드면 장중 로직 생략)
    - 향후 필드: `country`, `market`
- `provider`:
  - `"kis"` | `"pykrx"` | 기타
- `now`:
  - 단위 테스트/통제 평가를 위한 타임존 인지 현재 시각(선택)
- `lookback_for_volume`:
  - 거래량 휴리스틱 평균 계산에 사용하는 과거 일수

### 5.2 기본 규칙

1. **자명한 길이 처리**
   - `n = len(candles)`
   - `n == 0` → `-1` 반환(호출자가 처리)
   - `n == 1` → `0` 반환(하나뿐이므로 사용)

2. **소스 인지형 지름길**
   - `provider == "pykrx"`이면:
     - PyKRX는 EOD이므로 항상 마지막 봉 사용
       - `return n - 1`

3. **기본(KIS)**
   - 시작값 `idx_eval = n - 1`
   - 이후 거래소 장 상태 + 거래량 휴리스틱으로 조정

## 6. 거래소 세션 모델

KRX와 미국 주요 거래소의 정규장을 모델링합니다.

### 6.1 타임존

- 한국 주식:
  - `Asia/Seoul`
- 미국 주식(NYSE/NASDAQ 등):
  - `America/New_York`
  - **DST(서머타임) 인지 필수**

### 6.2 세션 상태

거래소별 현재 시각을 거친 상태로 분류합니다.

- **KRX(국내 주식)**
  - 정규장: 09:00–15:30(서울)
  - 상태:
    - `INTRADAY`: 09:00 <= now < 15:30
    - `AFTER_CLOSE`: 15:30 <= now < 다음날 09:00

- **미국(NYSE/NASDAQ)**
  - 정규장: 09:30–16:00(뉴욕)
  - 상태:
    - `PRE_OPEN`: 00:00 <= now < 09:30
    - `INTRADAY`: 09:30 <= now < 16:00
    - `AFTER_CLOSE`: 16:00 <= now < 24:00
  - `data/holidays_us.json`(`SAB_DATA_DIR` 경로) 사용 가능 시, 일반 장중 시간대라도 미국 휴일이면 `STATE_CLOSED`로 취급

미국 시장의 경우 `sab/scan.py`의 `refresh_us_holidays`와 연계해, 당일이 휴일이면 시계상 장중 구간이어도 시장 종료로 처리합니다.

## 7. 거래량 기반 휴리스틱

시간 정보만으로는 다음을 완전히 구분하기 어렵습니다.

- “원래 거래가 얇은 정상 일자”
- “오늘 장중의 미완성 부분 봉”

마지막 봉에 대해 보수적인 거래량 휴리스틱을 추가합니다.

### 7.1 계산

`candles`, `lookback_for_volume`이 주어졌을 때:

- `last = candles[-1]`
- `prev_window = candles[-(lookback_for_volume + 1):-1]`
- `v_last = float(last.get("volume") or 0.0)`
- `avg_vol = mean(volume(c) for c in prev_window)` (`prev_window`가 비어 있지 않은 경우)

정의:

```python
very_thin_today = (
    avg_vol > VOL_FLOOR and
    v_last < avg_vol * THIN_RATIO
)
```

설정값:

- `VOL_FLOOR`:
  - 절대 최소 임계(예: 1,000주). 본래 비유동 종목에서 과민 반응을 줄이기 위함
- `THIN_RATIO`:
  - 비율 임계값(예: `0.2`, 최근 평균의 20%). 필요 시 설정/환경변수로 노출

### 7.2 사용 방식

- **미국 + KIS**:
  - `INTRADAY`이면 일반적으로 당일을 제외하고 전일 사용(`idx_eval = n - 2`)
  - `PRE_OPEN`/`AFTER_CLOSE`에서도 조기 생성된 부분 봉을 피하기 위해 `very_thin_today`를 추가 판단에 사용 가능

- **국내 + KIS**:
  - 국내 일봉이 EOD 성향이 강하더라도 견고성을 위해,
    - 다음 조건을 모두 만족할 때만 마지막 봉 제외
      - 세션 상태가 `INTRADAY`
      - `very_thin_today == true`

## 8. 최종 의사결정 로직

종합 로직:

1. `n = len(candles)`
2. 자명한 길이 처리 및 `provider == "pykrx"` 처리(항상 `n - 1`)
3. 거래소/시장 판별
   - `meta["currency"]`, `meta["exchange"]` 또는 간단 매핑(예: `.US` 접미사 → US)
4. `state = get_exchange_state(market, now)` 계산
   - `INTRADAY`, `PRE_OPEN`, `AFTER_CLOSE`
   - US는 당일 휴일이면 `INTRADAY`를 무시
5. 위 정의대로 `very_thin_today` 계산
6. `idx_eval` 결정

   - **US + KIS**
     - `state == INTRADAY`:
       - `idx_eval = n - 2`
     - `state in {PRE_OPEN, AFTER_CLOSE}` 이고 `very_thin_today`:
       - `idx_eval = n - 2`
     - 그 외:
       - `idx_eval = n - 1`

   - **KR + KIS**
     - `state == INTRADAY` 이고 `very_thin_today`:
       - `idx_eval = n - 2`
     - 그 외:
       - `idx_eval = n - 1`

7. 언더플로 보호

   - `idx_eval < 0`이면 `idx_eval = 0`

8. `idx_eval` 반환

의도:

- 시장이 열려 있거나 당일 봉이 부분봉으로 명확할 때는 전일 봉 사용
- 장이 닫히고 거래량이 정상 범위이면 최신 봉 사용
- PyKRX/EOD 피드는 항상 마지막 봉 사용

## 9. 코드베이스 통합 지점

현재 “마지막 캔들 = 평가 캔들”을 가정하는 **의사결정 레벨 함수**에 헬퍼와 Option B 슬라이싱을 적용합니다.

### 9.1 매수(Buy)

- `sab/signals/hybrid_buy.py`
  - `evaluate_ticker_hybrid`:
    - 현재:
      - `candles[-1]`, `candles[-2]`, `sma_trend[-1]`, `ema_short[-1]`, `rsi_vals[-1]` 등 사용
    - 변경:
      - KIS/PyKRX + meta 기반 `idx_eval = choose_eval_index(...)` 계산
      - 슬라이싱:
        - `candles_eval = candles[: idx_eval + 1]`
        - `closes_eval`, `sma_eval`, `ema_short_eval`, `ema_mid_eval`, `rsi_eval`
      - 패턴 함수에 `*_eval` 전달:
        - `_detect_trend_pullback_bounce(closes_eval, sma_eval, ema_short_eval, ema_mid_eval, rsi_eval, candles_eval, settings)`
        - `_detect_swing_high_breakout(...)`
        - `_detect_rsi_oversold_reversal(...)`
      - 최종 후보 생성 시 `latest = candles[idx_eval]`, `prev = candles[idx_eval - 1]` 사용(가격, 등락률, 고저, 지표)

- `sab/signals/evaluator.py`
  - `evaluate_ticker`(EMA20/50 전략):
    - 동일 패턴 적용
      - `idx_eval` 계산
      - `latest = candles[idx_eval]`, `previous = candles[idx_eval - 1]`
      - 지표 인덱스 참조:
        - `ema20[idx_eval]`, `ema20[idx_eval - 1]`, `rsi14[idx_eval]`, `atr14[idx_eval]`, `sma200[idx_eval]`
      - 유동성 윈도우는 `idx_eval`까지의 데이터만 사용(`candles_eval[-20:]`)

### 9.2 매도(Sell)

- `sab/signals/hybrid_sell.py`
  - `evaluate_sell_signals_hybrid`:
    - `idx_eval` 기반으로
      - `latest = candles[idx_eval]`, `last_close = latest["close"]`
      - EMA/SMA/RSI는 `idx_eval` 인덱스 사용
      - “3연속 음봉” 계산:
        - `start = max(0, idx_eval - 2)`
        - `last_three = candles[start: idx_eval + 1]`

- `sab/signals/sell_rules.py`
  - `evaluate_sell_signals`:
    - `idx_eval` 기반으로
      - `latest = candles[idx_eval]`, `close_today = latest["close"]`
      - `atr_today = atr_values[idx_eval]`
      - EMA/SMA/RSI는 `idx_eval`과 `idx_eval - 1` 사용

이 변경으로 지표 계산 로직은 유지하면서 “어느 날짜를 평가할지”를 단일 테스트 가능한 헬퍼로 고립할 수 있습니다.

### 9.3 리포팅 정합성

- `SellEvaluation` / `HybridSellEvaluation`에 `eval_price`, `eval_index`, `eval_date`를 포함
- `sab/sell.py`는 해당 값을 `SellReportRow` 생성에 사용하여, 마크다운 리포트의 “Last / P&L”가 실제 의사결정에 사용된 봉과 일치하도록 함
- `reports/*.sell.md`는 가능하면 “Last close”에 평가 날짜를 함께 표시해, 장중 실행인지 장마감 후 실행인지 명확하게 함

## 10. 엣지 케이스 및 특수 고려사항

- **조기 폐장/부분 세션(예: 미국 휴일)**
  - 가능하면 세션 상태 함수가 휴일 캘린더와 조기 폐장 일정을 고려해야 함
  - 우선은 사용 가능한 미국 휴일 데이터로 휴일을 장중으로 오판하지 않도록 처리

- **저유동 종목**
  - 본래 거래량이 매우 작은 종목은 평균 거래량 자체가 낮음
  - `VOL_FLOOR`로 극소 거래량에 대한 과민 반응을 방지
  - 필요 시 “휴리스틱 적용 전 최소 60~90일 히스토리 필요” 같은 보호 장치를 추가 가능

- **데이터 결측**
  - 날짜 간 큰 공백은 데이터 품질 이슈일 수 있음
  - 선택적으로 날짜 갭을 탐지해 마지막 봉을 신뢰하지 않고 `REVIEW` 처리 가능

- **EOD/장중 혼합(KIS vs PyKRX 폴백)**
  - KIS 실패 후 PyKRX 폴백 시 마지막 봉의 의미가 달라짐
  - meta에 `source = "pykrx"`를 표기해 `choose_eval_index`가 EOD로 처리하도록 함

- **타임존 & DST**
  - 미국 시장은 `America/New_York` DST 규칙을 반영한 timezone-aware `datetime` 사용 필수
  - DST 경계에서 1시간 오차(off-by-one-hour)가 나지 않도록 모든 세션 계산을 해당 거래소 타임존에서 수행

## 11. 테스트 전략

헬퍼와 평가 함수 두 레이어에서 검증합니다.

### 11.1 단위 테스트: `choose_eval_index`

대상: API 호출 없이 검증 가능한 작고 순수한 함수(또는 모듈)

핵심 케이스:

1. **US, 장중, KIS 일봉**
   - 구성:
     - `provider = "kis"`, `meta.exchange = "NAS"`, `currency = "USD"`
     - `candles` 길이 >= 7, 마지막 봉 날짜 = 오늘
     - 마지막 봉 거래량 << 최근 5일 평균
     - `now` = 11:00 America/New_York(`INTRADAY`)
   - 기대:
     - `idx_eval == len(candles) - 2`

2. **US, 장마감 후, 정상 거래량**
   - `now` = 17:00 America/New_York(`AFTER_CLOSE`)
   - 마지막 봉 거래량이 최근 평균과 유사
   - 기대:
     - `idx_eval == len(candles) - 1`

3. **US, 장전/장후 + 극단적 저거래량 마지막 봉**
   - `now` = 08:00 또는 19:00 America/New_York
   - 마지막 봉 거래량 << 평균, `very_thin_today = true`
   - 기대:
     - `idx_eval == len(candles) - 2`

4. **KR, 장중, 거래량 얇음 vs 정상**
   - `provider = "kis"`, `meta.currency = "KRW"`
   - `now` = 10:00 Asia/Seoul(`INTRADAY`)
   - Case A: 마지막 봉 거래량 정상 → `idx_eval == len(candles) - 1`
   - Case B: 마지막 봉 거래량 매우 낮음 → `idx_eval == len(candles) - 2`

5. **PyKRX 데이터**
   - `provider = "pykrx"`
   - `now` 무관
   - 기대:
     - `idx_eval == len(candles) - 1`

6. **자명한 길이**
   - `len(candles) == 0` → `idx_eval == -1`
   - `len(candles) == 1` → `idx_eval == 0`

7. **미국 휴일**
   - 시계상으론 `INTRADAY` 시간대지만 당일이 미국 휴일
   - 시장 종료로 간주하여 마지막 완료봉 사용
     - `idx_eval == len(candles) - 1`

### 11.2 통합 테스트: 평가 함수

매수/매도 평가가 올바른 봉과 지표를 사용하는지 검증합니다.

1. **하이브리드 매수, US, 장중**
   - 합성 캔들 시퀀스:
     - N-1일이 하이브리드 패턴 조건 충족
     - N일은 거래량이 얇은 부분 봉
   - `now` = 미국 장중
   - 기대:
     - `evaluate_ticker_hybrid`가 가격/RSI/EMA/패턴 탐지에 N-1 데이터를 사용
     - 후보의 `price`, `rsi14`, `sma20`이 N이 아닌 N-1과 일치

2. **하이브리드 매수, US, 장마감 후**
   - 동일 시퀀스, `now` = 장마감 후, 마지막 봉 거래량 정상
   - 기대:
     - 평가가 N 봉을 최신 봉으로 사용

3. **EMA20/50 매수(국내), 장중 vs 장마감 후**
   - KR 티커에서 EMA 크로스 + RSI 반등이 특정 일자에 발생하도록 구성
   - 테스트:
     - 장중(서울 10:00), 마지막 봉 거래량 얇음:
       - N-1 봉으로 신호 평가
     - 장마감 후:
       - N(최신) 봉으로 평가

4. **매도 규칙(일반 + 하이브리드), 장중 vs 장마감 후**
   - 보유 종목/캔들 이력에서 특정 봉에 매도 트리거(RSI < 50, EMA 크로스, 3연속 음봉 등)가 발생하도록 구성
   - 기대:
     - 장중에는 부분 당일 봉에 **조기 반응하지 않음**
     - 장마감 후에는 해당 봉 완성 시 트리거를 정상 인식

5. **실데이터 픽스처 회귀(예: TMO)**
   - `data/candles_overseas_NYS_TMO.json`을 픽스처로 사용
   - `now`를 다음 두 시점으로 고정:
     - 파일 마지막 날짜의 미국 장중 시각
     - 같은 날짜의 장마감 후 시각
   - 검증:
     - 장중: 평가는 전일 봉 사용
     - 장마감 후: 평가는 마지막 봉 사용

## 12. 향후 작업 / 로드맵(요약)

- `sab/signals/session.py`(가칭) 모듈 추가
  - 거래소 타임존/세션 상태 로직 캡슐화
  - 재사용 헬퍼 제공: `get_exchange_state(meta, now)`, `is_us_holiday(date)` 등
- `VOL_FLOOR`, `THIN_RATIO`를 config/env로 노출
- 후보 결과에 **평가 기준일**(`eval_date`)을 명시 기록해, 리포트에서 어제 기준인지 오늘 기준인지 명확히 표시
- 일봉 기반 확장 자산(ETF, 선물 등)에도 동일 프레임 적용
