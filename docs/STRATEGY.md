# 전략/로직 설계 — Swing Core Logic (v1.1)

상태: Accepted (2026-03-28)  
대상: `sab scan`/`sab sell`의 **신호 평가 및 리스크 가이드 산출 로직**  
비목표: 자동 주문/체결, 포지션 사이징, 멀티타임프레임(분봉) 매매 로직

## 문서 상태

### 현재 제공

- `ema_cross`/`sma_ema_hybrid` buy, `generic`/`sma_ema_hybrid` sell, `sab entry`, 로컬 `sab ai-brief`, trading sessions 기반 time stop은 현재 구현과 테스트가 따르는 계약입니다.
- corporate action 의심 시 현재 구현은 `flags=["CORPORATE_ACTION_SUSPECT"]`를 남기고 최종 action을 `REVIEW`로 보정합니다.

### 실험

- 별도 experimental 전략 계약은 두지 않습니다. 파라미터 튜닝은 설정과 replay fixture에서 검증합니다.

### 백로그

- hybrid buy의 volume 누락/0 처리 일관화
- corporate action을 `flags`만 승격하고 자동 `REVIEW` 강등을 제거하는 계약은 [Spec v1.3](spec-v1.3.md)의 backlog로 남아 있습니다.

### 폐기 후보

- adjusted/raw 캐시를 다시 혼합하거나 `.US` 같은 모호한 티커 규칙을 되돌리는 방향은 채택하지 않습니다.

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
  - buy candidate에는 `signal_price_basis=adjusted`, `signal_close_adjusted_value`, `entry_reference_close_raw_value`, `entry_reference_eval_date`를 함께 기록합니다.
  - `entry_reference_close_raw_value`는 시그널 평가 후 후보 티커만 raw 캔들을 배치 warmup한 다음, 동일 `eval_date`의 raw 종가를 후처리로 붙여 이후 entry 판단이 adjusted/raw 혼용 없이 raw 기준으로만 비교되도록 합니다.
- sell(`sab sell`)
  - 캔들 수집은 기본 `adjusted=false`로 동작합니다.
  - 의도: 보유(진입단가/손절/타깃) 판단을 **원시 가격 기준**으로 해석하고, corporate action은 “자동 결론”이 아닌 `REVIEW`로 올려 수동 확인을 유도합니다(6장 참고).
- 운영 유의:
  - 같은 티커라도 scan vs sell에서 adjusted 정책이 다르므로, 지표/가격 레벨의 절대값이 일치하지 않을 수 있습니다.
  - `sab entry`는 adjusted 신호 종가를 직접 쓰지 않고, buy report에 저장된 raw reference close와 entry 시점 raw/live price만 비교합니다.
  - raw reference close가 없거나 basis가 명시되지 않은 레거시 buy report는 `REVIEW`로 fail-closed 처리합니다.
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
  - 재수집 성공: 응답을 완성 세션 기준으로 다시 검증했을 때 `stale_sessions == 0`인 최신 캔들만 저장하고 사용합니다.
  - 재수집 응답이 여전히 stale하면 “재수집 실패”와 동일하게 취급합니다.
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
  - 거래소별 균등 버킷이 아니라, KIS rank metric을 정규화해 **미국 전체 top-N**을 단일 랭킹으로 병합합니다.
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
3. `use_market_regime_filter=true`이면, 시장별 benchmark(`rs_benchmark_ticker_kr/us`)의 완료 일봉 종가가 SMA200 위인지 먼저 확인합니다.
   - benchmark 종가가 SMA200 이하이면 그 시장의 ticker는 `Market regime filter blocked (...)` 사유로 scan에서 제외합니다.
   - benchmark를 구하지 못하거나 완료 히스토리/SMA200이 부족하면, 해당 시장의 레짐 필터는 비활성화하고 buy report `system_issues`에 경고를 남긴 뒤 scan은 계속 진행합니다.
   - 이 레짐 게이트는 **scan 전용**이며 sell/entry에는 적용하지 않습니다.
4. 각 티커별로 **완성 캔들 기준**으로 평가합니다.
5. 후보(candidate) 티커만 raw 캔들을 추가 warmup한 뒤, cache hit 기반으로 entry용 raw reference close를 보강합니다.
6. 후보를 정렬하고(점수/RS/유동성 등), 통화 표시/미국장 상태를 장식합니다.
7. buy 리포트(JSON)를 생성합니다.

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
    - 이 경우 `sab entry`는 gap guard 비교를 생략하고, raw 기준가/실시간 가격/strategy mode 기준으로만 `ENTER|REVIEW`를 판단합니다.
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
- `rs_diff_value`는 “종목 룩백 수익률 - 시장 benchmark 룩백 수익률”입니다.
  - benchmark는 `strategy.rs_benchmark_ticker_kr` / `strategy.rs_benchmark_ticker_us`로 지정합니다.
  - benchmark 수익률은 종목과 동일하게 adjusted 시계열 + `choose_eval_index()` + `rs_lookback_days` 기준으로 계산합니다.
  - benchmark를 구하지 못하면 RS 점수는 부여하지 않고, scan report `system_issues`에 경고를 남깁니다.
- 최종 후보 정렬은 다음 키를 우선합니다.
  - `score_value` desc → `rs_diff_value` desc → `avg_dollar_volume_value` desc → `pct_change_value` desc → ticker.
  - KR/US mixed run에서는 USD 후보의 거래대금을 FX로 환산해 유동성 tie-breaker를 비교합니다.
  - mixed run에서 FX를 구하지 못하면, 유동성 tie-breaker는 비활성화하고 다음 키(`pct_change_value`, ticker)로만 정렬합니다.

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
  - 감지 시 최종 action은 `REVIEW`로 강등/승격되어 자동 `SELL/HOLD`를 막고 수동 확인을 우선합니다.

### 6.2 `sell_mode=sma_ema_hybrid` (이익 보호 + 하드스탑)

근거 코드: `sab/signals/hybrid_sell.py`

#### 6.2.1 주요 규칙(요약)

- 이익실현 티어:
  - partial profit zone 도달 시 break-even 보호 stop을 제안하고 기본 action은 `HOLD`
  - low target 도달 시 보호 stop을 추가로 강화하고 기본 action은 `HOLD`
  - high target 도달 시 더 강한 보호 stop을 제안하되, 즉시 `SELL`하지는 않습니다
- 추세 붕괴:
  - EMA/SMA 이탈, EMA short<EMA mid 교차, RSI<50/40 등으로 `REVIEW/SELL`
  - 보호 stop 이탈이나 강한 reversal evidence가 있을 때만 강한 청산으로 이어집니다
- failed breakout:
  - holdings의 `strategy` 태그에 `breakout`이 포함된 경우 손실 임계로 `SELL`
- 하드 스탑 밴드(기본 3–5%):
  - 손실이 밴드 내면 `REVIEW`, 최대치 이상이면 `SELL`
- (옵션) extended time stop:
  - grace 이후에도 수익/추세 조건이 약하면 `SELL`
- corporate action 의심 감지 시 `flags=["CORPORATE_ACTION_SUSPECT"]`를 추가하고 최종 action은 `REVIEW`로 조정합니다.

### 6.3 corporate action(분할/역분할 등) 감지 계약

근거 코드: `sab/signals/sell_rules.py`, `sab/signals/hybrid_sell.py`

- 최근 N봉(기본 5) 내에 **전일 대비 비정상 급변(기본 ±45% 이상)** 이 발생했고,
  - 그 비율이 split-like ratio(2:1, 3:1, 1:2 등)로 보이면 corporate action 가능성을 기록합니다.
- 이 경우 `CORPORATE_ACTION_SUSPECT` 플래그를 기록하고 최종 action을 `REVIEW`로 조정해,
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
- `signal_price_basis=adjusted`, `signal_close_adjusted_value`, `entry_reference_close_raw_value`, `entry_reference_eval_date`를 포함합니다.
- `sab entry`는 `entry_reference_close_raw_value`가 있을 때만 raw/live entry 가격과 gap guard를 자동 판단합니다.
  - basis가 없거나 raw reference close가 없는 candidate는 `REVIEW`로 처리합니다.
- `gap_atr_multiplier <= 0`으로 gap guard가 의도적으로 비활성화된 run에서는, candidate에 gap guard 필드가 없어도 `sab entry`가 이를 system issue로 간주하지 않습니다.
- hybrid buy는 추가로 pattern/entry_state/gap_guard 관련 필드를 포함합니다.
- `sab entry`는 mixed KR/US buy report를 시장별로 분리해 평가할 수 있습니다.
- `sab entry`는 종목별 판정이 끝난 뒤 포트폴리오 가드(`portfolio.max_active_holdings`, `portfolio.max_new_entries_per_market`)를 최종 `ENTER` 후보에만 적용합니다.
  - 포트폴리오 차단은 system issue가 아니라 정책 결과로 취급하며, `entries[].reasons`와 `summary.portfolio_blocked_*`에만 반영합니다.
  - `REVIEW`/`SKIP` 후보는 포트폴리오 규율로 승격하지 않습니다.
- mixed entry report는 `market="MIXED"`와 `markets=["KR","US"]`를 기록하고, `signal_eval_date_by_market` / `entry_session_date_by_market`을 함께 남깁니다.
- 단일 시장 entry report의 `signal_eval_date`는 buy report의 top-level 값이 없을 때 candidate들의 `eval_date`를 우선 사용해 결정합니다.
- 같은 시장 안에서 candidate들의 `eval_date`가 혼재하면, `sab entry` 리포트의 `system_issues`에 혼재 경고를 기록합니다.

### 7.1.1 AI Brief report (entry 후속 요약)

- `sab ai-brief`는 전략 신호 생성기가 아니라 `sab entry` 결과의 후속 요약/판단 레이어입니다.
- 입력은 `*.entry.json`이며, `entries[].action == "ENTER"` 행만 추천 후보가 됩니다.
- `REVIEW`/`SKIP` 행은 추천으로 승격하지 않고 `excluded_candidates[]`에 남깁니다.
- provider 호출 전 후보는 최대 5개로 제한하며, 최종 `recommendations[]`는 최대 3개입니다.
- `fake` provider는 외부 GPT/news/API를 호출하지 않고, 낮은 confidence와 source issue를 남깁니다.
- `openai` provider는 OpenAI Responses API structured output으로 후보를 요약하지만, ticker 추가, `REVIEW`/`SKIP` 승격, 자동 주문/체결 언어를 허용하지 않습니다.
- `local-json` source provider는 로컬 source report를 후보 context로 붙일 수 있지만, entry report의 후보 universe를 확장하지 않습니다.
- `http-json` source provider는 HTTPS 외부 source API에 eligible ticker 목록을 POST하고, 응답 `sources[]`를 같은 source row 계약으로 정규화합니다. Source API fetch는 HTTPS/local-private/redirect/body-size 제한을 적용하고, 반환 row URL은 syntax/local-private/DNS 검증을 통과해야 합니다. 반환 ticker가 후보 universe 밖이거나 stale/future-time/invalid URL/cap 초과이면 모델 입력에서 제외하고 `source_issues[]`로 남깁니다.
- `finnhub` source provider는 `FINNHUB_API_KEY`로 Finnhub Company News를 호출하는 US-only vendor adapter입니다. Repo ticker는 `AAPL.NAS`→`AAPL`, `BRK.B.NYS`→`BRK.B`처럼 Finnhub symbol로 변환하고, KR ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 반환된 `headline`/`url`/Unix `datetime`은 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 모델 입력에 들어갑니다.
- `naver-news` source provider는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`로 Naver Search API 뉴스 endpoint(`https://openapi.naver.com/v1/search/news.json`)를 호출하는 KR-only vendor adapter입니다. Repo ticker는 buy report 회사명을 검색어로 우선 사용하고, 없으면 6자리 ticker를 사용하며, `display=10`, `start=1`, `sort=date`로 요청합니다. US ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 반환된 `title`(HTML 제거), `originallink` 또는 `link`, `pubDate`는 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 모델 입력에 들어갑니다.
- AI Brief source URL은 HTTP(S)와 hostname이 필요하며, whitespace/control char, userinfo, literal local/private IP, localhost를 허용하지 않습니다. Offline `local-json`/source eval 경로는 DNS를 조회하지 않고, live/http 경로에서만 hostname DNS 검증을 수행합니다. `published_at`은 offset 포함 ISO 8601이어야 하고 72시간 freshness 및 15분 future skew 정책을 통과해야 합니다.
- RSS/Atom/RDF 로컬 파일 또는 live HTTPS feed URL은 `scripts/collect_ai_brief_sources.py`로 `sab.ai_brief_sources.v1` payload를 생성한 뒤 `local-json` 주입이나 source eval에 사용할 수 있습니다. 로컬 feed 파일은 offline으로 처리하고, live feed URL은 HTTPS/local-private/redirect/body-size 제한과 live item URL DNS 검증을 통과해야 합니다. fetch/timeout/invalid feed 실패는 collector top-level `issues[]` WARN으로 남습니다. collector의 top-level `issues[]` 중 eligible ticker에 속한 항목은 `local-json` provider 주입 시 `source_issues[]`로 보존되며, source eval은 같은 diagnostics를 eval 결과의 `issues[]`로 보고합니다.
- OpenAI provider는 candidate에 주입된 source URL만 cite할 수 있습니다.
- OpenAI provider timeout/요청 실패/출력 계약 실패는 추천을 비우고 `system_issues[]`로 남깁니다.
- source provider timeout/HTTP/JSON 실패는 추천 생성을 중단하지 않고 `system_issues[]`로 남기며, 추천에 소스가 없으면 ticker별 `source_issues[]`로 disclose해야 합니다.
- `scripts/eval_ai_brief_recommendations.py`는 생성된 AI Brief artifact의 source-backed/manual-review 품질 게이트입니다. eligible/excluded/cap-excluded entry 후보 정합성, summary count 일관성, rank 연속성, source-backed recommendation 비율, source 없는 추천의 confidence 안전성을 오프라인으로 평가하며, 새 매매 신호를 생성하지 않습니다.
- `--buy-report`는 회사명/기존 buy 근거 보강용이며, entry report에 없는 ticker를 추가하지 않습니다.
- mixed KR/US entry report는 `--market KR|US`를 요구하고, AI Brief artifact는 단일 시장만 다룹니다.

### 7.2 Sell report (row)

- `action`은 `HOLD|REVIEW|SELL` 중 하나입니다.
- `stop_price`, `target_price`는 “가이드”이며, override가 있으면 override가 우선합니다.

## 8. 운영/재현성 권장 사항

- 같은 날짜 리포트라도 “실행 시각(장중/장후)”에 따라 평가 캔들이 달라질 수 있으므로,
  - 운영 스케줄을 장마감 이후로 고정하는 것을 권장합니다.
- 리포트에 `system_issues/failures`가 있으면 신호 해석보다 **데이터 정합성 확인**을 우선합니다.
- 데이터 제공자 경고(예: PyKRX 폴백/지연)는 결과 해석 전에 반드시 확인합니다(3.5 참고).

## 9. 백로그 메모

- volume 누락/0 처리 정책의 일관화(특히 hybrid buy)
- corporate action `flags` 전용 승격 계약 검토: `docs/spec-v1.3.md`
