# 전략/로직 설계 — Swing Core Logic (v1.1)

상태: Draft (2026-02-25)  
대상: `sab scan`/`sab sell`의 **신호 평가 및 리스크 가이드 산출 로직**  
비목표: 자동 주문/체결, 포지션 사이징, 멀티타임프레임(분봉) 매매 로직

## 1. 목적

이 문서는 “실전 운용에서 재현 가능한” 관점으로, 현재 코드베이스의 스윙 핵심 로직을 **계약(Contract)** 형태로 고정합니다.

- 입력(캔들/보유/설정) → 출력(후보/액션/가이드) 변환 규칙을 명시합니다.
- 실행 시점(장중/장후)에 따른 “평가 기준 캔들”을 명확히 합니다.
- 모드(`strategy_mode`, `sell_mode`)별 규칙 차이를 분리해 기술합니다.

## 2. 핵심 개념(용어)

- **Candle(일봉)**: `{"date","open","high","low","close","volume"}` 형태의 레코드.
- **평가 캔들(Eval candle)**: 신호/룰 계산에 사용하는 마지막 완성 일봉.
- **Eval index**: 평가 캔들의 배열 인덱스(`choose_eval_index()` 결과).
- **system 이슈**: 데이터 부족/비정상 캔들/예외 등 “시그널 이전”의 시스템/데이터 문제.
- **signal 탈락**: 규칙(필터/조건) 불충족으로 후보에서 제외되는 경우.
- **candidate**: buy 리포트에 들어가는 종목 단위 결과(dict).
- **sell action**: `HOLD|REVIEW|SELL`.
- **entry_state**(hybrid buy 전용): `WATCH|READY`(대기 vs 종가 기반 확인 신호).

## 3. 입력 데이터 계약

### 3.1 Candle 스키마/정렬

- 캔들은 **날짜 오름차순**(old → new)으로 정렬되어야 합니다.
  - KIS 클라이언트는 날짜 기준으로 정렬 후 반환합니다(`sab/data/kis/quote.py`).
- `date`는 `YYYYMMDD` 형태의 문자열이어야 합니다.
- OHLC는 **finite float**(NaN/inf 불가)이어야 합니다.
- volume은 모드별로 처리 정책이 다릅니다(3.3 참고).

### 3.2 시장 구분(통화 기반)

- 기본 규칙:
  - `currency == "USD"` → US market
  - 그 외 → KR market
- scan에서는 ticker suffix로 통화를 추론합니다(예: `.NAS/.NYS/.AMS`, `.NASDAQ/.NYSE/.AMEX` 등).

### 3.3 Volume(거래량) 처리 정책

근거 코드: `sab/signals/evaluator.py`, `sab/signals/hybrid_buy.py`

- `strategy_mode=ema_cross`
  - 유동성 필터에서 volume은 **필수 데이터**입니다.
  - volume이 non-finite(파싱 불가/NaN/inf)이면 **system 이슈**로 처리하고 평가에서 제외합니다.
- `strategy_mode=sma_ema_hybrid`
  - volume이 `null`/빈 문자열이면 `0`으로 간주(유효)합니다.
  - 다만 “값이 있는데 파싱이 불가능한” volume은 **system 이슈**로 처리하고 평가에서 제외합니다.
  - `min_dollar_volume=0`이면, volume 누락(=0) 종목이 유동성 필터를 통과할 수 있으므로 운영에서는 최소 거래대금 임계치를 양수로 두는 것을 권장합니다.
- Sell(`sell_mode=generic|sma_ema_hybrid`)
  - 현재 sell 평가 로직은 volume을 직접 사용하지 않습니다.

### 3.4 가격 조정(adjusted) 정책

근거 코드: `sab/market_data_service.py`, `sab/market_data_pipeline.py`

- scan(`sab scan`)
  - 캔들 수집은 기본 `adjusted=true`로 동작합니다.
  - 의도: 분할/배당 등 corporate action이 가격 시계열에 반영된(조정된) 데이터로 지표를 계산해, 신호가 “가격 스케일 변화”에 과민하게 흔들리지 않도록 합니다.
- sell(`sab sell`)
  - 캔들 수집은 기본 `adjusted=false`로 동작합니다.
  - 의도: 보유(진입단가/손절/타깃) 판단을 **원시 가격 기준**으로 해석하고, corporate action은 “자동 결론”이 아닌 `REVIEW`로 올려 수동 확인을 유도합니다(6장 참고).
- 운영 유의:
  - 같은 티커라도 scan vs sell에서 adjusted 정책이 다르므로, 지표/가격 레벨의 절대값이 일치하지 않을 수 있습니다.
  - adjusted/raw 캔들은 캐시 키가 분리되어 서로 섞이지 않습니다(ADR-0011).
  - 분할/권리락/특이 이벤트가 의심되면 sell 리포트의 corporate action 사유를 최우선으로 확인합니다.

### 3.5 데이터 제공자(provider) 및 폴백 정책(요약)

근거 코드: `sab/market_data_service.py`, `sab/market_data_pipeline.py`

- `provider=kis`
  - KR/US 모두 지원합니다(US는 ticker suffix → exchange 매핑 사용).
  - KIS 실패 시 **KR 종목에 한해** PyKRX 폴백이 동작할 수 있습니다(US는 폴백 없음).
- `provider=pykrx`
  - scan에서 **KR 종목만** 지원합니다(US는 데이터 제공 불가).
  - 데이터는 EOD 성격이며, 장중/장전 실행에서는 최신 세션 데이터가 즉시 반영되지 않을 수 있습니다(설계 상 허용).

### 3.6 데이터 신선도(캐시) 정책(요약)

근거 코드: `sab/market_data_pipeline.py`, `sab/config.py`

- 캔들은 `data/`의 JSON 캐시를 우선 사용합니다.
- 캐시 키는 `adjusted` 여부를 포함해 분리됩니다(예: `candles_adj_005930` vs `candles_raw_005930`).
- 캐시는 “완성 세션 기준”으로만 저장/재사용합니다.
  - 장중/장전에는 “당일 미완성 일봉”을 제거한 상태로만 캐시를 사용/저장합니다(ADR-0011).
- 캐시 사용 여부는 “최신 완성 세션 대비 누락된 거래 세션 수(stale_sessions)”로 판단합니다.
  - KR/US 각각 `market_cache_stale_sessions_kr/us`가 허용 최대치입니다.
- `stale_sessions == 0`이면 **캐시를 사용**하고 provider 재수집을 생략합니다.
- `stale_sessions > 0`이면 provider 재수집을 **우선 시도**합니다.
  - 재수집 성공: 최신 캔들을 저장하고 사용합니다.
  - 재수집 실패: `stale_sessions <= max`이면 캐시로 폴백합니다(=fail-soft).
  - `stale_sessions > max`이면 폴백하지 않고 실패합니다(=fail-closed).
- 운영 가이드:
  - `max=0`은 “최신 데이터 아니면 캐시 미사용(=fail-closed 성향)”입니다.
  - `max>0`은 “일시적 API 장애 시 약간 stale한 데이터로도 리포트를 생성(=fail-soft 성향)”입니다.

### 3.7 티커 정규화/검증 계약(fail-closed)

- KR 티커:
  - 6자리 숫자 코드만 허용합니다(예: `005930`).
- US 티커:
  - 거래소 suffix가 명시된 형식만 허용합니다(예: `.NAS/.NYS/.AMS`와 동의어).
  - `.US` suffix는 모호성 방지를 위해 허용하지 않습니다.
- US 클래스 티커:
  - 내부 캐노니컬 표기는 `BASE.CLASS.EXCH`입니다(예: `BRK.B.NYS`).
  - `BRK/B.NYS` 입력은 허용하되 내부 저장/평가/메타데이터 키에서는 `BRK.B.NYS`로 정규화합니다.
  - KIS 호출 경계에서는 `invalid symbol(msg_cd=SYMB0001)`일 때에만 `BASE.CLASS`와 `BASE/CLASS` 대체 표기를 1회 시도하고, 성공한 provider 표기를 런타임 동안 재사용합니다.
  - 레이트리밋/토큰/서버 오류에서는 class 표기 대체를 시도하지 않고 즉시 실패합니다(호출 폭증 방지).
- US 스크리너(`screener.us_mode=kis`):
  - 기본값 리스트(`screener.us_defaults`) 자동 폴백을 사용하지 않습니다.
  - `--universe screener`에서 검증 실패/빈 결과가 발생하면 즉시 실패합니다.
  - `--universe both`에서는 watchlist는 유지하고 US 스크리너만 건너뜁니다.
- watchlist 경계:
  - `--universe watchlist|both`에서 watchlist 파일이 누락되면 즉시 실패합니다.
  - `--universe screener`에서는 watchlist를 로드/검증하지 않습니다.

## 4. 평가 기준 시점(완성 캔들) 계약

### 4.1 `choose_eval_index()` 정책

모든 buy/sell 평가는 `sab/signals/eval_index.py`의 `choose_eval_index()` 정책을 따릅니다.

- “마지막 캔들 날짜 < 현재 세션 날짜”이면, 최신 캔들은 이미 완성(EOD feed)된 것으로 간주하고 그대로 평가합니다.
- 장 시작 전/장중(`PRE_OPEN|INTRADAY`)에 “마지막 캔들 날짜 == 세션 날짜”이면 **당일 미완성 캔들을 제외**하고 전일 캔들로 평가합니다.
- US의 경우:
  - 휴일/조기마감(early close)을 반영해 세션 상태를 보정합니다.
  - 데이터 디렉터리의 캘린더(`holidays_us.json`) 및 내장 캘린더를 함께 사용합니다.

이 정책으로 인해, 같은 날이라도 **실행 시각**(장중 vs 장후)에 따라 평가 기준 캔들이 달라질 수 있습니다.

### 4.2 실전 운용 해석: “신호일(EOD)”과 “실행(다음 거래일)”의 분리

이 코드베이스의 buy/sell 평가는 기본적으로 **완성 일봉(EOD) 기반 의사결정 지원**입니다.

- `sab scan`의 candidate는 “내일 시초/장중 진입”을 자동으로 보장하는 entry 시그널이 아니라,
  - 오늘(평가 캔들)까지의 데이터로 “관찰/준비할 후보”를 정리한 결과입니다.
- 따라서 다음 거래일의 시초 갭/장중 체결 가능성/슬리피지 리스크는,
  - 별도의 `entry` 단계(`sab entry`)에서 계약으로 다루는 것을 전제로 합니다.

## 5. Buy(Scan) 로직 설계

Scan은 “후보 발굴 + 리스크 가이드” 목적이며, **매수 주문을 자동화하지 않습니다**.

### 5.1 공통 파이프라인(요약)

1. 티커 소스(워치리스트 + 스크리너)를 결합하고, 시장 필터 후 중복 제거합니다.
2. 캔들 데이터를 수집합니다(캐시 우선 + provider 조회).
3. 각 티커별로 **완성 캔들 기준**으로 평가합니다.
4. 후보(candidate)를 정렬하고(점수/RS/유동성 등), 통화 표시/미국장 상태를 장식합니다.
5. buy 리포트(JSON)를 생성합니다.

### 5.2 `strategy_mode=ema_cross` (EMA/RSI/ATR 기반)

근거 코드: `sab/signals/evaluator.py`

#### 5.2.1 필수 전제

- `min_history_bars` 이상(기본 120)의 완성 캔들이 있어야 합니다.
- `use_sma200_filter=true`를 사용하려면, **평가 시점 기준 200봉 이상**이 필요합니다.
  - scan은 기본적으로 `max(min_history_bars, 200)`봉을 수집하려고 시도합니다.
  - 신규상장/데이터 부족으로 200봉이 확보되지 않으면 SMA200이 NaN이 되어 필터가 사실상 통과하지 않습니다.

#### 5.2.2 계산 지표

- EMA(20), EMA(50)
- RSI(14)
- ATR(14)
- SMA(200)

#### 5.2.3 신호/필터 계약(요약)

- 가격 바닥:
  - `min_price`(KRW) 또는 `us_min_price`(USD) 미만이면 탈락.
- 핵심 신호:
  - EMA20/50 골든크로스(교차 발생) + RSI 30 상향 재돌파(+ RSI<70).
- (옵션) 추세 필터:
  - SMA200 위(가격/EMA들이 SMA200 위).
- (옵션) 기울기 필터:
  - EMA20/EMA50이 전일 대비 상승.
- 갭 필터:
  - 평가 캔들의 `open`과 전일 `close`로 갭을 계산하고(= **신호일 당일 갭**),
  - `gap_atr_multiplier > 0`이면 `|gap| ≤ (gap_atr_multiplier × ATR(t-1) / 전일종가)`를 만족해야 합니다(기본 multiplier 1.0).
  - 여기서 `ATR(t-1)`은 신호봉을 제외한 직전 완성봉 기준 ATR입니다(신호봉 갭으로 ATR 임계가 자기완화되는 문제 방지).
  - `gap_atr_multiplier > 0`인데 `ATR(t-1)`/전일종가 입력이 유효하지 않으면 **system 이슈(fail-closed)** 로 처리합니다.
  - `gap_atr_multiplier = 0`이면 갭 필터를 비활성화합니다.
  - 다음 거래일 시초 갭을 직접 제어하는 규칙은 아닙니다(4.2 참고).
- 유동성(거래대금) 필터:
  - 최근 20봉 평균 거래대금이 `min_dollar_volume`(KRW) 또는 `us_min_dollar_volume`(USD) 이상이어야 합니다.
  - volume이 non-finite면 **system 이슈**로 처리합니다(탈락 사유가 아니라 데이터 오류).
- ETF/ETN 제외(옵션):
  - `exclude_etf_etn=true`일 때 휴리스틱으로 제외합니다.

#### 5.2.4 점수/정렬 계약

- 점수는 “조건 통과 여부” 기반 가산점(정수형)에 가깝습니다.
  - 예: ema_cross, rsi, gap, liquidity, (선택) rs 등.
  - `sma200`/`slope` 점수 항목은 각각 옵션(`use_sma200_filter`, `require_slope_up`)이 켜진 경우에만 반영됩니다.
- 최종 후보 정렬은 다음 키를 우선합니다.
  - `score_value` desc → `rs_diff_value` desc → `avg_dollar_volume_value` desc → `pct_change_value` desc → ticker.

### 5.3 `strategy_mode=sma_ema_hybrid` (패턴 + 상태 머신)

근거 코드: `sab/signals/hybrid_buy.py`

#### 5.3.1 공통 필터

- 최소 히스토리(`min_history_bars`)
- 최소 가격(`min_price`/`us_min_price`)
- 최소 거래대금(`min_dollar_volume`/`us_min_dollar_volume`)
- 갭 필터(퍼센트): `|gap_pct| ≤ HYBRID_MAX_GAP_PCT`
- (옵션) SMA60 필터: 종가가 SMA60 위
- ETF/ETN 제외(옵션)

#### 5.3.2 패턴 탐지(우선순위)

1. Trend pullback bounce
2. Swing high breakout
3. RSI oversold reversal

패턴이 하나도 성립하지 않으면 후보에서 제외됩니다.

- Swing high breakout의 박스권(consolidation) 폭 계산은 **돌파 신호봉을 제외한 직전 구간**으로 평가합니다.
  - 의도: 돌파 당일 변동폭이 큰 정상 breakout이 “박스권 과대”로 오탐지되어 탈락하는 것을 방지합니다.
- Swing high breakout의 볼륨 확인은 **돌파 신호봉을 제외한 직전 N일 평균 거래량** 대비로 평가합니다.
  - 의도: `volume > Nd avg` 해석을 신호봉 포함 평균과 분리해 룰 의미를 고정합니다.

#### 5.3.3 `entry_state` 계약(READY vs WATCH)

hybrid buy는 candidate에 `entry_state`를 포함합니다.

- `WATCH`: 초기 셋업(대기)
- `READY`: 종가 기반으로 확인된 신호(다음 단계(예: entry 체크)에 바로 사용 가능)

`READY` 판단은 패턴별로 다르며, “종가가 EMA 위인지”, “RSI 확인(예: RSI>50)”, “볼륨 확인” 등을 조합합니다.

#### 5.3.4 gap guard(ATR 기반) 계약

- hybrid buy candidate는 ATR 기반 `gap_guard_pct`와 상/하단 가격을 함께 산출합니다.
- gap guard는 **신호봉 종가 시점의 ATR(t)** 를 사용해 다음 세션 entry 판단에 필요한 최신 변동성 가이드를 제공합니다.
- 이는 “다음 거래일 시초 갭” 해석을 위한 **가드 값**이며, `sab entry` 단계에서 `ENTER|REVIEW|SKIP` 판정에 사용됩니다.

### 5.4 Buy candidate 근거 필드 계약(`reasons[]`)

buy candidate는 기존 문자열 필드(`score_notes`, `pattern_reasons`, `entry_state_reason`)를 유지하면서,
UI/소비자가 안정적으로 해석할 수 있는 구조화 근거 필드 `reasons[]`를 함께 포함합니다.

- 스키마(요약):
  - `id`: 근거 식별자(예: `ema_cross`, `entry_state_ready`, `gap_within_limit`)
  - `label`: 사용자 표시용 텍스트
  - `kind`: `signal | filter | pattern | state | trigger | risk`
  - `status`: `pass | warn` (기본 `pass`)
  - `points`(선택): 점수 기여도
  - `value`/`threshold`(선택): 근거 수치/임계치
- `strategy_mode=ema_cross` 예:
  - `ema_cross`, `rsi_rebound`, `gap_within_limit`, `liquidity`
  - 옵션 사용 시 `sma200_trend_filter`, `ema_slope_up`
  - RS 약세 시 `rs_below_benchmark`(`status=warn`)
- `strategy_mode=sma_ema_hybrid` 예:
  - `pattern_*`, `entry_state_*`
  - 패턴 트리거(`trigger_*`)
  - 리스크 가드(`gap_guard_atr`, 필요 시 `breakout_extended`)

운영/호환성 원칙:

- 구조화 필드를 우선 사용하고, 없는 경우 기존 문자열 필드로 폴백합니다.
- 기존 자동화/스크립트와의 호환을 위해 레거시 문자열 필드는 제거하지 않습니다.

## 6. Sell 로직 설계

Sell은 보유 종목을 `HOLD|REVIEW|SELL`로 분류하고, stop/target 가이드를 제공합니다.

- 평가 대상은 `quantity > 0`인 활성 보유분으로 한정합니다(`quantity <= 0`은 평가에서 제외).

### 6.1 `sell_mode=generic` (EMA/RSI/ATR 트레일 중심)

근거 코드: `sab/signals/sell_rules.py`

#### 6.1.1 주요 규칙(요약)

- (옵션) SMA200 컨텍스트 이탈 시 `REVIEW`
- EMA 되크로스(Short EMA가 Long EMA 아래로 교차) 시 `SELL`
- 종가가 두 EMA 아래면 `REVIEW`
- RSI 붕괴:
  - `rsi_floor` 미만 → `REVIEW`
  - `rsi_floor_alt` 미만 → `SELL`
- ATR 트레일:
  - 진입 이후 구간에서 `peak_close - (atr_trail_multiplier × ATR)`을 계산해 stop을 제안합니다.
  - stop은 “내려가지 않도록” 단조 강화되며(= 과거에 계산된 stop보다 완화되지 않음), 따라서 변동성(ATR) 급증이 있어도 stop이 후퇴하지 않습니다.
  - `stop_override`가 있으면 이를 우선합니다.
- 타임 스탑:
  - `time_stop_days`는 달력일이 아닌 **trading sessions** 기준으로 계산합니다.
  - `time_stop_days` 경과 시 `REVIEW`(단, 이미 `SELL`이면 유지)
- corporate action 의심(분할 유사 급변) 감지 시 `flags=["CORPORATE_ACTION_SUSPECT"]`를 추가합니다.
  - corporate action 플래그는 action을 덮어쓰지 않습니다(`SELL` 유지).

### 6.2 `sell_mode=sma_ema_hybrid` (이익실현 티어 + 하드스탑)

근거 코드: `sab/signals/hybrid_sell.py`

#### 6.2.1 주요 규칙(요약)

- 이익실현 티어:
  - partial/target zone 도달 시 `REVIEW`, high target 도달 시 `SELL`
- 추세 붕괴:
  - EMA/SMA 이탈, EMA short<EMA mid 교차, RSI<50/40 등으로 `REVIEW/SELL`
- failed breakout:
  - holdings의 `strategy` 태그에 `breakout`이 포함된 경우 손실 임계로 `SELL`
- 하드 스탑 밴드(기본 3–5%):
  - 손실이 밴드 내면 `REVIEW`, 최대치 이상이면 `SELL`
- (옵션) extended time stop:
  - grace 이후에도 수익/추세 조건이 약하면 `SELL`
- corporate action 의심 감지 시 `flags=["CORPORATE_ACTION_SUSPECT"]`를 추가합니다(action 유지).

### 6.3 corporate action(분할/역분할 등) 감지 계약

근거 코드: `sab/signals/sell_rules.py`, `sab/signals/hybrid_sell.py`

- 최근 N봉(기본 5) 내에 **전일 대비 비정상 급변(기본 ±45% 이상)** 이 발생했고,
  - 그 비율이 split-like ratio(2:1, 3:1, 1:2 등)로 보이면 corporate action 가능성을 기록합니다.
- 이 경우 action은 변경하지 않고 `CORPORATE_ACTION_SUSPECT` 플래그로 기록해,
  - “단가/수량/데이터 조정 여부”를 먼저 확인하도록 합니다.

### 6.4 sell의 히스토리 길이(target_bars) 정책(요약)

근거 코드: `sab/sell.py`

- sell은 “보유 기간(최초 진입일)”을 기준으로, 평가에 필요한 히스토리 길이(target bars)를 동적으로 늘릴 수 있습니다.
  - 기본값: `max(min_history_bars, 200)`
  - 보유 기간이 길면: 달력 일수를 trading sessions로 근사해 추가 버퍼를 더하고(상한 4000), 가능한 한 entry 이후 구간을 포함하도록 합니다.
- 의도: ATR 트레일 등 “entry 이후 구간 기반” 룰이 충분한 히스토리에서 동작하도록 보장합니다.

## 7. 출력(리포트) 계약(요약)

### 7.1 Buy report (candidate)

- 공통적으로 ticker, price, 지표/메트릭, 점수, 통화, 데이터 소스 등을 포함합니다.
- `strategy_mode`: 각 candidate는 평가에 사용된 전략 모드(`ema_cross` 또는 `sma_ema_hybrid`)를 포함합니다.
- `sab entry`는 candidate의 `strategy_mode`를 우선 사용하며, 레거시 리포트처럼 candidate 필드가 없는 경우 buy report top-level `strategy_mode`(또는 `config_snapshot.strategy_mode`)를 폴백으로 사용합니다.
- `eval_date`(YYYYMMDD): 해당 candidate가 실제로 평가된 완성 일봉 날짜를 포함합니다(`choose_eval_index()` 결과 기준).
- hybrid buy는 추가로 pattern/entry_state/gap_guard 관련 필드를 포함합니다.
- `sab entry`의 `signal_eval_date`는 buy report의 top-level 값이 없을 때 candidate들의 `eval_date`를 우선 사용해 결정합니다.
- candidate들의 `eval_date`가 혼재하면, `sab entry` 리포트의 `system_issues`에 혼재 경고를 기록합니다.

### 7.2 Sell report (row)

- `action`은 `HOLD|REVIEW|SELL` 중 하나입니다.
- `stop_price`, `target_price`는 “가이드”이며, override가 있으면 override가 우선합니다.

## 8. 운영/재현성 권장 사항

- 같은 날짜 리포트라도 “실행 시각(장중/장후)”에 따라 평가 캔들이 달라질 수 있으므로,
  - 운영 스케줄을 장마감 이후로 고정하는 것을 권장합니다.
- 리포트에 `system_issues/failures`가 있으면 신호 해석보다 **데이터 정합성 확인**을 우선합니다.
- 데이터 제공자 경고(예: PyKRX 폴백/지연)는 결과 해석 전에 반드시 확인합니다(3.5 참고).

## 9. Open decisions / Backlog

- RS(상대강도) 벤치마크를 “상수”가 아닌 시장별 지수 시계열로 정의
- volume 누락/0 처리 정책의 일관화(특히 hybrid buy)
- 다음 구현 스펙: `docs/spec-v1.3.md`
