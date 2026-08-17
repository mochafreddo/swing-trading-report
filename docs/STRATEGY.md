# 전략/로직 설계 — Swing Core Logic

상태: Accepted
계약 기준: [Spec v1.1](spec-v1.1.md)은 storage/report_index/runtime_state/web API 계약의 source of truth이고, 본 문서는 신호/리스크 로직의 source of truth입니다. backlog 항목은 [Spec v1.3](spec-v1.3.md) 참고.
최종 확인: 2026-07-02
대상: `sab scan`/`sab sell`/`sab entry`/`sab ai-brief`/`sab sell-ai-brief`의 **신호 평가 및 리스크 가이드 산출 로직**
비목표: 자동 주문/체결, 포지션 사이징, 멀티타임프레임(분봉) 매매 로직

## 문서 상태

### 현재 제공

- `ema_cross`/`sma_ema_hybrid` buy, `generic`/`sma_ema_hybrid` sell, `sab entry`, 로컬 `sab ai-brief`, 로컬 `sab sell-ai-brief`, trading sessions 기반 time stop은 현재 구현과 테스트가 따르는 계약입니다.
- corporate action 의심 시 현재 구현은 `flags=["CORPORATE_ACTION_SUSPECT"]`를 남기며, 기존 `SELL`은 보존하고 `SELL`이 아닌 action만 `REVIEW`로 보정합니다.
- Decision Board V0에는 sealed public fact만 받는 pure compiler와 local-only shadow runner가 있습니다. 이 runner는 기존 `scan`/`sell`/`entry` 결과나 알림을 바꾸지 않으며 production preparation/research adapter가 미설정된 기본 CLI는 `CONFIG_UNAVAILABLE`로 fail closed합니다. 별도 explicit live-shadow command만 credentialed adapter를 조립하고, recorded/live 비교와 manifest 승인 전에는 schedule에 연결하지 않습니다.

### 실험

- 별도 experimental 전략 계약은 두지 않습니다. 파라미터 튜닝은 설정과 replay fixture에서 검증합니다.

### Replay coverage vs historical backtesting

`tests/fixtures/replay_eod/scan/*` contains deterministic scan replay fixtures
for active threshold behavior. These fixtures protect implementation semantics:
market/regime gating, RSI zones, consolidation windows, gap rejection,
volume confirmation, relative-strength quality, volatility-vs-stop alignment,
and report artifact shape.

Replay fixtures are not profitability evidence. They do not estimate win rate,
expected value, MFE/MAE, stop/target hit-rate, slippage, transaction cost, or
survivorship effects.

`sab backtest` is the local historical runner for that research layer. It
reuses the same `ema_cross`/`sma_ema_hybrid` buy evaluators and
`generic`/`sma_ema_hybrid` sell evaluators over historical candle prefixes,
then writes a local `*.backtest.json` with the period, symbols, trades, win
rate, return, drawdown, holding period, equity curve, issues, and config
snapshot. Its execution assumptions are explicit: EOD buy signals enter on the
next available valid open, `SELL` exits use the signal-day close,
`SELL_PARTIAL` closes `--partial-exit-fraction` of the remaining position,
daily OHLC stop/target ambiguity is controlled by `--intraday-exit-policy`
using the previous completed sell prefix, and gap-through stop/target hits fill
at the candle open. Position size is weighted with `--position-size-pct`, costs
are configured with `--transaction-cost-bps`, and slippage is configured with
`--slippage-bps`.

`summary.total_return_pct` is a non-compounded closed-lot contribution metric
(`summary.return_model=non_compounded_initial_equity_contribution`), not a
portfolio NAV simulation. The artifact also records maximum gross exposure, and
`summary.max_drawdown_pct` uses conservative low-price mark-to-market events for
open positions so intratrade drawdown is visible.

Backtest artifacts are still research outputs, not production execution
instructions. Data-vendor survivorship bias, point-in-time universe
construction, benchmark selection, and corporate-action data quality are
recorded through the artifact `assumptions` object, optionally sourced from
`--assumptions-file`; the runner does not infer those facts from OHLCV alone.

### 백로그

- 현재 없음.

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
- **quality_state**: `sma_ema_hybrid` 기술 셋업 품질입니다. 주문 실행 준비도나 계좌 리스크 승인을 뜻하지 않습니다.
- **investment_readiness / implementation_ready**: 계좌 NAV/리스크 예산, 의도 포지션 규모 기준 유동성/청산 가능성, 포트폴리오 노출, source/fundamental context까지 확인됐는지 나타내는 실행 준비도 레이어입니다.
- **candidate**: buy 리포트에 들어가는 종목 단위 결과(dict).
- **sell action**: `HOLD|SELL_PARTIAL|REVIEW|SELL`.
- **entry_state**: hybrid buy candidate에서는 `WATCH|READY`(대기 vs 종가 기반 확인 신호)를 뜻합니다. entry report에서는 AI Brief 호환성을 위해 비하이브리드 `ENTER` row도 `READY`를 기록할 수 있습니다.

## 3. 입력 데이터 계약

### 3.1 Candle 스키마/정렬

- 캔들은 **날짜 오름차순**(old → new)으로 정렬되어야 합니다.
  - KIS 클라이언트는 날짜 기준으로 정렬 후 반환합니다(`sab/data/kis/quote.py`).
- `date`는 `YYYYMMDD` 형태의 문자열이어야 합니다.
- OHLC는 **finite float**(NaN/inf 불가)이어야 합니다.
- volume은 모드별로 처리 정책이 다릅니다(3.3 참고).
- scan/sell 수집은 장중 미완성 tail candle이 제거되어도 평가에 필요한 완성봉 수가 남도록 기본 요청 수에 1봉 버퍼를 더합니다.

### 3.2 시장/통화 구분

- 시장 키(`KR|US`)는 티커 정규화/파싱 결과를 기준으로 합니다.
  - KR: 6자리 숫자 티커.
  - US: 거래소 suffix가 명시된 티커(예: `.NAS/.NYS/.AMS`, `.NASDAQ/.NYSE/.AMEX` 등).
- RS benchmark와 market regime 게이트는 이 티커 기반 시장 키로 시장별 benchmark를 선택하고, `market_regime_blocked_by_market`/`market_regime_unavailable_by_market`도 같은 키로 기록합니다.
- 통화(`KRW|USD`)는 평가 metadata, 거래대금/가격 기준, 표시용 필드입니다.
  - scan은 티커 suffix로 통화를 추론합니다.
  - `currency == "USD"`는 US 금액 기준을 뜻하지만, market regime/RS 시장 키를 대체하지 않습니다.

### 3.3 Volume(거래량) 처리 정책

근거 코드: `sab/signals/evaluator.py`, `sab/signals/hybrid_buy.py`

- `strategy_mode=ema_cross`
  - 유동성 필터에서 volume은 **필수 데이터**입니다.
  - volume이 non-finite(파싱 불가/NaN/inf)이면 **system 이슈**로 처리하고 평가에서 제외합니다.
- `strategy_mode=sma_ema_hybrid`
  - volume은 **필수 데이터**입니다.
  - volume이 `null`/빈 문자열이면 **system 이슈**로 처리하고 평가에서 제외합니다.
  - volume이 non-finite(파싱 불가/NaN/inf)이면 **system 이슈**로 처리하고 평가에서 제외합니다.
  - finite `0` volume은 데이터 값으로는 허용하지만, 평가 구간의 평균 거래대금이 `0`이면 `min_dollar_volume=0`이어도 후보에서 제외합니다.
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
  - 의도: 보유(진입단가/손절/타깃) 판단을 **원시 가격 기준**으로 해석하고, corporate action은 플래그로 노출해 수동 확인을 유도합니다. 단, 하드 스탑 등으로 이미 `SELL`인 결론은 보존합니다(6장 참고).
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
   - benchmark를 구하지 못하거나 완료 히스토리/SMA200이 부족하면 `strategy.market_regime_unavailable_policy`로 처리합니다.
     - `warn_continue`이면 buy report `system_issues`에 경고를 남기고 해당 시장의 레짐 필터만 비활성화한 뒤 scan을 계속하며, summary에 `market_regime_unavailable_by_market`(`issue_code`, `message`)을 기록합니다.
     - `block_market`이면 benchmark를 구하지 못한 시장의 후보를 제외하고 summary에 `market_regime_blocked_by_market`와 `market_regime_unavailable_by_market`을 기록합니다.
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
  - scan은 기본적으로 `max(min_history_bars, 200) + 1`봉을 수집하려고 시도합니다. 추가 1봉은 장중 미완성 tail candle 제거 후에도 200개 완성봉을 유지하기 위한 버퍼입니다.
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
  - EMA20/EMA50이 전일 대비 상승(`require_slope_up`).
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
  - dynamic benchmark는 각 후보의 평가일과 정렬되어야 합니다. 같은 시장 안에서도 후보 평가일이 다르면 해당 평가일별 benchmark 수익률을 따로 계산합니다. benchmark가 후보 평가일보다 뒤처지면 stale system 이슈로 처리하고 해당 후보의 dynamic RS 점수를 비활성화합니다.
  - benchmark를 구하지 못하면 RS 점수는 부여하지 않고, scan report `system_issues`에 경고를 남깁니다.
- 최종 후보 정렬은 다음 키를 우선합니다.
  - `score_value` desc → `rs_diff_value` desc → `avg_dollar_volume_value` desc → `pct_change_value` desc → ticker.
  - `rs_diff_value`가 없는 후보는 “0% 중립”이 아니라 알 수 없는 값으로 취급해, 유한한 `rs_diff_value`가 있는 후보보다 뒤에 둡니다.
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

- SMA trend/EMA/RSI 등 패턴 판단에 필요한 핵심 지표가 계산되지 않으면 일반 신호 탈락이 아니라 **system 이슈**로 처리합니다.
- `use_sma60_filter=true`인데 SMA60이 계산되지 않으면 필터 실패가 아니라 **system 이슈**로 처리합니다.

- Swing high breakout의 박스권(consolidation) 폭 계산은 **돌파 신호봉을 제외한 직전 구간**으로 평가합니다.
  - 의도: 돌파 당일 변동폭이 큰 정상 breakout이 “박스권 과대”로 오탐지되어 탈락하는 것을 방지합니다.
  - 허용 박스권 폭은 `strategy.hybrid.breakout_consolidation_max_range_pct`로 설정하며 기본값은 `0.10`(10%)입니다.
- Hybrid buy의 볼륨 확인은 패턴별 신호봉을 제외한 직전 `strategy.hybrid.volume_lookback_days`일 평균 거래량 대비로 평가합니다.
  - 적용 대상: Trend pullback bounce, Swing high breakout, RSI oversold reversal.
  - 의도: 신호봉 당일 거래량이 자기 자신의 비교 기준선을 움직이지 않게 해 `volume > Nd avg` 해석을 고정합니다.
  - RSI oversold reversal은 직전 lookback 평균 거래량이 양수이고 신호봉 거래량이 그 이상일 때만 볼륨 확인을 통과합니다. 직전 lookback 거래량이 0이면 신호봉 거래량만으로 후보를 만들지 않습니다.
- KR breakout confirmation이 켜진 경우 첫 돌파 종가는 `WATCH`가 될 수 있습니다.
  - 다음 완성 일봉이 **원래 박스권 swing high** 위에서 한 번 더 마감하면 `READY`로 승격할 수 있습니다.
  - 이때 직전 돌파봉의 고점을 새 swing high로 잘못 재계산하지 않고, 돌파 전 박스권의 swing high를 유지합니다.

#### 5.3.3 `entry_state` 계약(READY vs WATCH)

hybrid buy는 candidate에 `entry_state`를 포함합니다.

- `WATCH`: 초기 셋업(대기)
- `READY`: 종가 기반으로 확인된 신호(다음 단계(예: entry 체크)에 바로 사용 가능)

`READY` 판단은 패턴별로 다르며, “종가가 EMA 위인지”, “RSI 확인(예: RSI>50)”, “볼륨 확인” 등을 조합합니다.

- Trend pullback bounce의 `READY`는 종가가 EMA short 위에 있는 것을 전제로 합니다.
  - hammer near EMA, RSI>50, volume thrust는 EMA reclaim 이후의 확인 신호로만 사용합니다.
  - EMA reclaim 전의 hammer near EMA는 `WATCH`입니다.

#### 5.3.4 gap guard(ATR 기반) 계약

- hybrid buy candidate는 ATR 기반 `gap_guard_pct`와 상/하단 가격을 함께 산출합니다.
- gap guard는 **신호봉 종가 시점의 ATR(t)** 를 사용해 다음 세션 entry 판단에 필요한 최신 변동성 가이드를 제공합니다.
- 이는 “다음 거래일 시초 갭” 해석을 위한 **가드 값**이며, `sab entry` 단계에서 `ENTER|REVIEW|SKIP` 판정에 사용됩니다.

#### 5.3.5 entry trigger guard 계약

- hybrid buy candidate는 다음 entry 단계에서 재확인할 트리거 기준을 `entry_trigger_price_value`, `entry_trigger_operator`, `entry_trigger_label`로 기록할 수 있습니다.
- `entry_trigger_price_basis`는 트리거 가격 기준을 표시합니다. 현재 hybrid buy는 adjusted 신호 캔들에서 트리거를 계산하므로 `adjusted`를 기록합니다.
- Swing high breakout은 원래 박스권 `swing_high`를 `gte` 기준으로 기록합니다.
- EMA 회복을 전제로 한 pullback/reversal 후보는 EMA short 값을 `gte` 기준으로 기록할 수 있습니다.
- `sab entry`는 이 필드가 있는 `READY` 후보에 한해 raw/live entry 가격이 트리거 기준을 유지하는지 재확인합니다.
  - 트리거가 adjusted 기준이면 entry 단계에서 `entry_reference_close_raw_value / signal_close_adjusted_value` 비율로 raw 기준 트리거로 환산한 뒤 live/raw 가격과 비교합니다.
  - 기준 미달이면 `SKIP`입니다.
  - 레거시 리포트처럼 trigger guard 필드가 없으면 기존 호환성을 위해 `entry_state=READY` 판단을 유지합니다.

#### 5.3.6 상대강도(RS) 계약

- hybrid buy candidate도 `ema_cross`와 동일하게 `rs_return_value`, `rs_diff_value`, `rs_benchmark_value`, `rs_benchmark_ticker`를 포함합니다.
- `rs_return_value`는 candidate 종목의 adjusted 완료 일봉 종가와 `rs_lookback_days` 기준으로 계산합니다.
- `rs_benchmark_value`는 scan 단계가 주입한 같은 시장 benchmark 수익률을 우선 사용하고, 없으면 정적 `strategy.rs_benchmark_return`을 사용합니다.
- benchmark close series에 NaN/inf 같은 non-finite 값이 있으면 benchmark를 사용할 수 없는 것으로 처리합니다.
- `rs_diff_value = rs_return_value - rs_benchmark_value`이며, 전체 후보 정렬의 tie-breaker에 사용됩니다(5.2.4 참고).

#### 5.3.7 리스크 정합성/품질 상태 계약

- hybrid buy candidate는 `risk_alignment`를 포함합니다.
  - 값: `aligned | tight_stop_vs_volatility | unknown`
  - `volatility_reference_pct`는 gap guard 비율을 우선 사용하고, 없으면 ATR/종가 비율을 사용한 숫자 값입니다.
  - `risk_alignment_reasons`는 `gap_guard_exceeds_stop_max`, `atr_exceeds_stop_max`, `volatility_reference_unavailable` 같은 안정적인 reason code 목록입니다.
  - `tight_stop_vs_volatility`는 후보 변동성 기준이 `sell.hybrid.stop_loss_pct_max`보다 큰 경우이며, scan 후보에서는 즉시 제외하지 않고 warning 근거로 표시합니다.
  - `sab entry`는 hybrid candidate에 `risk_alignment`가 명시되어 있고 값이 `aligned`가 아니면, 가격/갭/트리거 조건이 통과해도 자동 `ENTER` 대신 `REVIEW`로 낮춥니다.
- hybrid buy candidate는 `quality_state`를 포함합니다.
  - 값: `A | B | C`
  - `A`: READY + RS 양호 + 리스크 정합성 양호
  - `B`: READY지만 RS 약세 또는 손절폭 대비 변동성 warning이 있음
  - `C`: WATCH, RS 기준 미확보, 또는 변동성 기준 미확보
  - `quality_reasons`는 `entry_state_ready`, `relative_strength_negative`, `risk_alignment_tight_stop` 같은 reason code 목록입니다.
- 2026-06-22 검토 결과, `quality_state=A`는 기본값에서 SMA60이나 SMA200 같은 개별 종목 중장기 추세 필터를 추가로 요구하지 않습니다.
  - 근거: 현행 `A` 판정은 READY, benchmark 대비 RS 양호, 변동성/손절폭 정합성 양호를 요구하고, 시장 방향성은 market regime benchmark SMA200 필터가 담당합니다.
  - SMA20/EMA10/21 패턴 조건보다 긴 개별 종목 추세를 기본 hard/quality gate로 승격하는 것은 replay matrix만으로는 수익성이나 민감도를 검증할 수 없습니다.
  - 더 보수적인 로컬 운용이 필요하면 `HYBRID_USE_SMA60_FILTER=true`로 기존 optional SMA60 hard filter를 명시적으로 켭니다. SMA60/SMA200 기반 기본 품질 기준 변경은 별도 historical backtest/parameter-sensitivity 검증 후 다룹니다.
- `sab entry`는 `sma_ema_hybrid` candidate의 gap/trigger/risk checks 이후 `quality_state`를 마지막 자동 진입 정책으로 적용합니다.
  - `quality_state=A`만 자동 `ENTER` 후보가 될 수 있습니다.
  - `quality_state=B|C` 또는 누락/unknown 값은 수동검토 reason과 함께 `REVIEW`입니다.
- `quality_state=A`는 기술 셋업 라벨일 뿐이며, entry row의 주문 실행 준비도와 분리됩니다.
- `strategy_mode=sma_ema_hybrid` 정렬은 `quality_state`를 먼저 적용한 뒤 기존 점수/RS/유동성/등락률/ticker tie-breaker를 사용합니다. `ema_cross` 정렬은 기존 score 우선 계약을 유지합니다.

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
  - 리스크 가드(`gap_guard_atr`, 필요 시 `breakout_extended`, `risk_alignment_tight_stop`)
  - RS 비교(`rs_above_benchmark` 또는 `rs_below_benchmark`)

운영/호환성 원칙:

- 구조화 필드를 우선 사용하고, 없는 경우 기존 문자열 필드로 폴백합니다.
- 기존 자동화/스크립트와의 호환을 위해 레거시 문자열 필드는 제거하지 않습니다.

## 6. Sell 로직 설계

Sell은 보유 종목을 `HOLD|SELL_PARTIAL|REVIEW|SELL`로 분류하고, stop/target 가이드를 제공합니다.

- 평가 대상은 `quantity > 0`인 활성 보유분으로 한정합니다(`quantity <= 0`은 평가에서 제외).
- holdings row가 `broker_state=not_seen_in_toss`이면 시장 데이터 평가를 건너뛰고 `REVIEW`로 표시합니다. 이 row는 Toss의 non-empty snapshot에서 보이지 않았다는 broker-state quarantine이며, `broker_missing_first_seen_date`, `broker_missing_last_seen_date`, `broker_missing_count`, `broker_missing_diff_hash` 증거를 함께 보존합니다.
- `entry_date`가 평가 캔들 날짜보다 미래이면 time stop 계산을 건너뛰고 `REVIEW`로 올립니다.
  - 의도: holdings 날짜/평가일 불일치를 정상 0세션 보유로 해석하지 않고 수동 확인을 요구합니다.

### 6.1 `sell_mode=generic` (EMA/RSI/ATR 트레일 중심)

근거 코드: `sab/signals/sell_rules.py`

#### 6.1.1 주요 규칙(요약)

- (옵션) SMA200 컨텍스트 이탈 시 `REVIEW`
  - SMA200이 계산되지 않으면 일반 컨텍스트 이탈이 아니라 system 이슈 reason과 함께 `REVIEW`
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
  - 기존 action이 `SELL`이면 보존하고, `HOLD` 등 `SELL`이 아닌 action만 `REVIEW`로 보정해 수동 확인을 우선합니다.

### Decision Board V0 ENTRY/HOLDING compiler policy (shadow)

Decision Board V0 compiler는 기존 `scan`/`sell`/`entry` action을 바꾸는 runtime
통합이 아니라, 이미 선택·봉인된 public SWING fact를 Task 1 payload로 투영하는 순수
shadow 경계입니다. 모델, 네트워크, 파일, clock, broker, 주문 API를 호출하지 않으며
후보나 보유 universe를 넓히지 않습니다.

첫 구현 범위는 US SWING ENTRY/HOLDING뿐입니다. KR과 LONG_TERM 판단, horizon mandate,
portfolio optimizer는 이 truth table을 재사용해 추측하지 않고 별도 gate가 생길 때까지
범위 밖입니다. 현재 기본 CLI에는 production preparation/research/claim-verifier adapter가
연결되지 않아 `CONFIG_UNAVAILABLE`로 닫히며, fixture/recorded 검증 통과를 실제 shadow
운영으로 오해해서는 안 됩니다. 모든 action은 조언이고 매수·매도는 사용자가 직접 합니다.

ENTRY 우선순위는 item/identity 미승인 `REVIEW`, non-candidate signal omit, 필수
mandate/signal/price/exposure gap `REVIEW`, deterministic exposure fail `AVOID`, research
gap/conflict `REVIEW`, action-eligible `MATERIAL_ADVERSE` `AVOID`, 나머지 `BUY`입니다.
독립 exposure fail이 있으면 stale/unapproved evidence가 없어도 `AVOID`가 유지되지만,
evidence conflict만으로 adverse veto를 추측하지 않고 `REVIEW`합니다.

HOLDING 우선순위는 current broker/candle/rule에 근거한 hard stop/confirmed exit `SELL`,
item/identity 또는 deterministic input gap `REVIEW`, action-eligible material adverse
`REVIEW`, research coverage gap/error `REVIEW`, 나머지 `HOLD`입니다. 유효한 hard
`SELL`은 supportive/adverse evidence, timeout, conflict, `NOT_SELECTED_CAP`이
`HOLD`/`REVIEW`로 낮출 수 없습니다. research selection은 priority/order로 최대 5개만
고르는 별도 순수 정책이고, 여섯 번째 이후 holding도 compiler universe에는 남아 정확히
한 번 평가됩니다. selection result는 선택 당시 전체 holding universe의 immutable policy
snapshot에 process-local로 결속되고 `compile_holding`의 필수 입력입니다. compiler는
selection과 다른 subset/누락/중복 universe를 거부하고, unselected holding에
`NOT_SELECTED_CAP`을 직접 적용합니다. 모든 compiler enum은 문자열 equality가 아니라
canonical enum member identity까지 확인하므로 raw/fresh-equal 문자열 mutation은 action
precedence를 바꿀 수 없습니다. item ID와 research priority/order도 매 selection/compile에서
exact scalar type과 lane/ticker/grammar/range를 재검증한 snapshot만 정렬에 사용하므로
equal subclass나 post-factory mutation은 selection, output order, canonical hash를 바꿀 수
없습니다.

### Decision Board V0 claim evidence policy (shadow)

- 한 validation은 공개 claim 하나와 검증된 공개 기사 하나만 다룹니다.
- entailment는 `SUPPORTED`, `CONTRADICTED`, `UNCLEAR` 중 하나이며 세 상태 모두 normalized article text 안의 exact nonempty `[start, end)` 근거 span이 필요합니다.
- directional action 변경 자격은 발급 당시 원래 claim이 `action_changing=true`이고 validation의 exact issued instrument/location identity 및 validation/request/article/source/policy의 immutable issuance snapshot과 deep revalidation을 통과한 unchanged `SUPPORTED`일 때만 생깁니다.
- `CONTRADICTED`와 `UNCLEAR`는 review 자료이며 action 변경을 승인하지 않습니다. context-only `SUPPORTED`도 action 변경을 승인하지 않습니다.
- compiler가 게시하는 public EvidenceRef는 위 자격을 다시 확인한 claim/source에서만 만들며 `SUPPORTING|OPPOSING` role, HTTPS source URL, publisher, published time, `WITHIN_POLICY` freshness, citation label을 포함합니다. 모델·provider가 임의로 쓴 URL이나 citation metadata는 사용하지 않습니다.
- 이 정책은 advice-only shadow 경계입니다. runner는 exact issued item/selection만 compiler에 전달하며 주문 생성·수정·취소 경로를 추가하지 않습니다.

### Decision Board V0 run aggregation policy (shadow)

- shared snapshot/preflight prerequisite가 유효하지 않으면 directional payload 없이 typed `BLOCKED`를 local artifact로 남기며 exit 0입니다.
- shared prerequisite가 유효하면 item timeout/provider/coverage failure를 해당 item의 `REVIEW`로 격리합니다. 모든 item이 `REVIEW`이거나 ENTRY signal item이 0개여도 run은 `PUBLISHED`, exit 0입니다.
- raw/mutated/wrong-lane authority, compiler payload identity mismatch, unexpected adapter error, persistence invariant failure는 `FAILED`, exit 2이며 invalid artifact를 쓰거나 upload하지 않습니다.
- HOLDING research cap은 enrichment 호출만 최대 5개로 제한합니다. full universe는 compile하며 hard `SELL`은 timeout과 `NOT_SELECTED_CAP`보다 우선합니다.
- local canonical write가 항상 upload보다 먼저입니다. optional upload 실패는 local `PUBLISHED|BLOCKED`를 degraded 상태로 보존하고, required upload 실패는 retained local path를 가진 typed `FAILED`입니다.

### Decision Board V0 shadow graduation policy

- 첫 측정 전에 policy/researcher/verifier version, planned ENTRY/HOLDING slot, diff reason,
  provider/coverage/freshness threshold를 local gate manifest로 승인합니다.
- 최소 20 US 거래 session 동안 모든 planned slot과 기존 경로의 후보/action 차이를
  `EXPECTED_POLICY_CHANGE|INPUT_GAP|SOURCE_GAP|BUG|UNEXPLAINED`로 분류합니다.
- `UNEXPLAINED`, privacy leak, order/notification access, replay mismatch, eligible holding
  누락, queue 밖 hard-SELL 누락은 각각 0건이어야 합니다.
- 관찰 뒤 threshold를 바꾸거나 서로 다른 policy version을 한 통계로 합치지 않습니다.
  변경 시 새 gate version과 새 20-session 기간이 필요합니다.
- gate 통과는 다음 cutover 검토 자격일 뿐 schedule/load, notification, workflow,
  credential scope를 자동 변경하지 않습니다. 주문 실행은 영구적으로 사용자 수동입니다.

측정 절차와 산식은 [Decision Board shadow evaluation](decision-board-shadow-evaluation.md),
public interface는 [Decision Board V0 reference](decision-board.md)를 기준으로 합니다.

### 6.2 `sell_mode=sma_ema_hybrid` (이익 보호 + 하드스탑)

근거 코드: `sab/signals/hybrid_sell.py`

#### 6.2.1 주요 규칙(요약)

- 이익실현 티어:
  - `entry_date`가 유효하면 진입일 이후 완료 일봉의 최고 종가 기준 P&L로 보호 stop 티어를 활성화합니다.
  - `entry_date`가 없거나 유효하지 않으면 기존 호환성을 위해 평가일 현재 P&L만 사용합니다.
  - `entry_date`가 유효하지만 평가 구간에 진입일 이후 완료봉이 없으면, pre-entry 가격으로 profit protection을 활성화하지 않습니다.
  - partial profit zone 도달 시 break-even 보호 stop을 제안하고 기본 action은 `HOLD`
  - low target 도달 시 보호 stop을 추가로 강화하고 기본 action은 `SELL_PARTIAL`입니다. 이 action은 부분 이익실현 검토/실행 제안이며 자동 주문은 아닙니다.
  - high target 도달 시 더 강한 보호 stop을 제안하고 기본 action은 `SELL_PARTIAL`입니다. stop 이탈 전에는 전체 `SELL`로 승격하지 않습니다.
  - high target 보호 stop이 활성화된 뒤 종가가 해당 stop 아래로 내려오면 `SELL`, 그보다 낮은 티어의 보호 stop 이탈은 `REVIEW`입니다.
  - corporate action 의심 구간에서는 분할/병합 전 가격 피크가 왜곡될 수 있으므로 과거 피크 기반 profit protection을 쓰지 않고 수동 확인 경로를 우선합니다.
  - corporate action 의심 여부는 최근 봉뿐 아니라 `entry_date` 이후 평가 구간 전체의 split-like 변동도 확인합니다.
- 추세 붕괴:
  - EMA/SMA 이탈, EMA short<EMA mid 교차, RSI<50/40 등으로 `REVIEW/SELL`
  - 최신 EMA short/EMA mid/SMA trend/RSI 중 필요한 지표가 NaN이면 `HOLD`로 두지 않고 `REVIEW`로 fail closed 처리합니다.
  - 보호 stop 이탈이나 강한 reversal evidence가 있을 때만 강한 청산으로 이어집니다
- failed breakout:
  - holdings의 `strategy` 또는 `tags` 중 하나에 `breakout`이 포함된 경우 손실 임계로 `SELL`
  - 로컬 `holdings.yaml`은 buy/entry report의 `pattern`을 `entry_pattern`으로 보존할 수 있습니다. 하위 hybrid sell evaluator는 구조화 필드(`pattern`, `entry_pattern`, `signal_pattern`)를 exact pattern ID로 해석하며, `swing_high_breakout`만 failed-breakout marker로 사용합니다.
  - 기존 holdings와의 호환을 위해 free-form `strategy`/`tags`의 `breakout` substring marker는 계속 인식합니다.
  - Supabase/web/scheduled export 경로는 active holdings의 `entry_pattern`을 보존합니다. 런타임이 `entry_pattern` 컬럼을 선택하므로 DB migration과 PostgREST schema cache가 먼저 적용되어야 합니다.
- 하드 스탑 밴드(기본 3–5%):
  - 손실이 밴드 내면 `REVIEW`, 최대치 이상이면 `SELL`
  - long position stop 가이드는 기존 보호 stop과 hard stop 중 더 타이트한 값(더 높은 stop price)을 유지합니다. 따라서 profit protection stop이 이미 더 높으면 hard stop이 리포트 stop을 낮추지 않습니다.
- (옵션) extended time stop:
  - 기본 time stop은 `sell.hybrid.time_stop_days`, `sell.hybrid.time_stop_grace_days`, `sell.hybrid.time_stop_profit_floor`를 사용합니다.
  - `sell.hybrid.pattern_time_stops.<pattern>`이 있으면 구조화 필드(`pattern`, `entry_pattern`, `signal_pattern`)의 exact pattern ID에 한해 지정된 time stop 필드만 override하고, 누락된 필드는 전역 hybrid 값을 상속합니다.
  - free-form `strategy`/`tags`의 `breakout` substring은 failed-breakout 손실 청산 호환성에는 계속 쓰지만, pattern-specific time stop override를 활성화하지 않습니다.
  - pattern key는 `trend_pullback_bounce`, `swing_high_breakout`, `rsi_oversold_reversal`만 허용합니다.
  - 운영 기본값은 `swing_high_breakout`을 15 trading sessions + 5 grace sessions + 1% profit floor로 짧게 적용해, 약한 breakout 셋업을 전역 30+15 세션보다 빨리 수동검토/청산 후보로 올립니다.
  - grace 이후에도 수익/추세 조건이 약하면 `SELL`
  - 수익 조건은 충족했지만 추세 지표가 부족한 경우, 지표 부족만으로 `SELL`하지 않고 `REVIEW`를 유지합니다.
- corporate action 의심 감지 시 `flags=["CORPORATE_ACTION_SUSPECT"]`를 추가합니다. 기존 action이 `SELL`이면 보존하고, `SELL`이 아닌 action만 `REVIEW`로 조정합니다.

### 6.3 corporate action(분할/역분할 등) 감지 계약

근거 코드: `sab/signals/sell_rules.py`, `sab/signals/hybrid_sell.py`

- 최근 N봉(기본 5) 내에 **전일 대비 비정상 급변(기본 ±45% 이상)** 이 발생했고,
  - 그 비율이 split-like ratio(2:1, 3:1, 1:2 등)로 보이면 corporate action 가능성을 기록합니다.
- 이 경우 `CORPORATE_ACTION_SUSPECT` 플래그를 기록합니다.
  - 기존 action이 `SELL`이면 보존해 하드 스탑/커스텀 스탑을 corporate action 플래그가 덮지 않습니다.
  - `SELL`이 아닌 action은 `REVIEW`로 조정해 “단가/수량/데이터 조정 여부”를 먼저 확인하도록 합니다.

### 6.4 sell의 히스토리 길이(target_bars) 정책(요약)

근거 코드: `sab/sell.py`

- sell은 “보유 기간(최초 진입일)”을 기준으로, 평가에 필요한 히스토리 길이(target bars)를 동적으로 늘릴 수 있습니다.
  - 기본값: `max(min_history_bars, 200) + 1`
  - 보유 기간이 길면: 달력 일수를 trading sessions로 근사해 추가 버퍼를 더하고(상한 4000), 마지막에 미완성 tail candle 제거용 1봉 버퍼를 더해 가능한 한 entry 이후 구간을 포함하도록 합니다.
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
- `PRE_OPEN|INTRADAY`의 KIS live 가격 스냅샷 해석은 시장별로 분리합니다.
  - US `overseas price-detail` 응답은 날짜/시각/as-of marker(`xymd`, `trade_date`, `trade_time`, `timestamp`, `as_of` 등)가 없으면 이전 세션 가격과 구분할 수 없으므로 `entry_price=null`로 fail closed 처리하고 `REVIEW`로 남깁니다. KIS HTTP 응답의 `Date` 헤더가 로컬 수신 시각 기준 최근 5분 이내이고 미래 skew가 1분 이내로 정상 파싱되면 KIS client가 이를 `entry_snapshot_at` marker로 보강해 같은 freshness 증거로 사용합니다. marker가 있을 때만 `curr`가 있으면 `USD`일 때 양수 `last`/`last_price`/`stck_prpr`/`ovrs_nmix_prpr`/`ovrs_prpr` 값을 entry snapshot으로 사용합니다.
  - KR `domestic price-detail` 응답은 날짜/시각 계열 스냅샷 marker(`stck_cntg_hour`, `xymd` 등)가 없으면 `entry_price=null`로 fail closed 처리하고 `REVIEW`로 남깁니다.
- `gap_atr_multiplier <= 0`으로 gap guard가 의도적으로 비활성화된 run에서는, candidate에 gap guard 필드가 없어도 `sab entry`가 이를 system issue로 간주하지 않습니다.
  - `sab entry`는 source buy report의 `config_snapshot.gap_atr_multiplier`를 우선 사용해 이 판단을 재현하고, entry report에는 현재 runtime 설정과 별도로 `effective_gap_atr_multiplier` / `source_report_gap_atr_multiplier`를 기록합니다.
- hybrid buy는 추가로 pattern/entry_state/gap_guard/entry trigger guard 관련 필드를 포함합니다.
  - `risk_alignment`가 명시된 hybrid candidate는 `aligned`일 때만 자동 `ENTER` 대상이 될 수 있습니다. `tight_stop_vs_volatility`나 `unknown`은 entry row에 수동검토 reason을 남기고 `REVIEW`로 처리합니다.
  - `risk_alignment`가 없는 레거시 candidate는 기존 호환성을 위해 이 규칙만으로 차단하지 않습니다.
- `sma_ema_hybrid` buy report의 `config_snapshot`은 공통 전략 설정과 함께 `strategy.hybrid.*` 값을 기록해, hybrid 후보 평가 파라미터를 사후 재현할 수 있게 합니다.
- `strategy_mode=ema_cross` 같은 비하이브리드 entry row는 최종 `action=ENTER`이고 source `entry_state`가 비어 있으면 `entry_state=READY`를 기록합니다. 이는 AI Brief base gate와 후속 소비자가 실행 가능 기술 신호를 동일하게 해석하도록 하기 위한 호환 필드입니다.
- static `strategy.rs_benchmark_return`이 설정된 buy report는 `config_snapshot.rs_benchmark_return`도 기록해 RS tie-breaker 입력을 사후 재현할 수 있게 합니다.
- `sab entry`는 mixed KR/US buy report를 시장별로 분리해 평가할 수 있습니다.
- `sab entry`는 종목별 판정이 끝난 뒤 포트폴리오 가드(`portfolio.max_active_holdings`, `portfolio.max_new_entries_per_market`, `portfolio.exposure_limits`)를 최종 `ENTER` 후보에만 적용합니다.
  - `max_active_holdings`는 기존 활성 보유와 이번 run에서 승인된 신규 진입을 합산합니다.
  - `max_new_entries_per_market`은 이번 run에서 승인된 신규 진입만 세며, 기존 활성 보유 수는 시장별 신규 진입 한도에 포함하지 않습니다.
  - `exposure_limits[]`는 `dimension/value/max_active` 목록이며, 기존 활성 보유와 이번 run에서 먼저 승인된 신규 진입을 같은 bucket으로 합산합니다. 지원 dimension은 `currency`, `sector`, `theme`, `beta_bucket`, `correlation_bucket`, `tag`입니다.
  - currency bucket은 티커/통화에서 자동 추론합니다. sector/theme/beta/correlation bucket은 buy candidate 필드(`sector`, `theme`, `beta_bucket`/`beta`, `correlation_bucket` 등)나 holdings tag prefix(`sector:semiconductor`, `theme:ai`, `beta:high_beta`, `correlation:ai-megacap`)에서 읽습니다.
  - 포트폴리오 차단은 system issue가 아니라 정책 결과로 취급하며, `entries[].reasons`와 `summary.portfolio_blocked_*`에만 반영합니다. 노출 차단은 `portfolio exposure cap reached (<dimension>=<value>, max=<n>)` reason과 `summary.portfolio_blocked_by_exposure`에 기록됩니다.
  - `REVIEW`/`SKIP` 후보는 포트폴리오 규율로 승격하지 않습니다.
- 새 entry row는 `implementation_ready=false`, `investment_readiness="CONTEXT_REQUIRED"`, `investment_readiness_reasons[]`를 포함합니다.
  - 현재 기본 누락 reason은 `nav_risk_budget_unavailable`, `liquidity_exit_capacity_unavailable`, `portfolio_exposure_context_unavailable`, `source_fundamental_context_unavailable`입니다.
  - candidate가 `intended_position_value`(또는 호환 position-value 필드)와 `avg_dollar_volume_value`(또는 호환 평균 거래대금 필드)를 제공하면 `sab entry`는 `liquidity_exit_capacity`에 포지션 금액, 평균 거래대금, ADV 대비 비율, 정상 참여율 10%/스트레스 참여율 3% 기준 예상 청산 일수를 기록합니다. 이 경우 `liquidity_exit_capacity_unavailable`은 readiness reason에서 제거됩니다.
  - candidate가 `risk_stop_price_value`와 의도 포지션 금액을 제공하면 `sab entry`는 `downside_risk`에 stop 가이드 기준 하방 손실액과 포지션 손실률을 기록합니다. buy candidate가 생성한 stop/target 가이드는 `risk_price_basis="adjusted"`를 함께 기록하며, entry 단계는 `signal_close_adjusted_value`와 `entry_reference_close_raw_value`의 비율로 raw 진입가 기준 stop/target으로 환산한 뒤 하방 리스크를 계산합니다. `portfolio_value`/`account_value`/`nav` 계열 값도 있으면 포트폴리오 손실률과 bps를 함께 기록합니다. 이 값은 stop 체결 보장이나 계좌 손실 한도가 아니라 gap/slippage 전 하방 참고값입니다.
  - 의도 포지션 크기나 평균 거래대금이 없으면 `liquidity_exit_capacity.status`를 `position_size_unavailable`, `avg_traded_value_unavailable`, 또는 `position_size_and_liquidity_unavailable`로 남기고 `liquidity_warnings[]`에 누락 warning을 기록합니다.
  - candidate의 `liquidity_flags`/`liquidity_risk_flags` 또는 boolean flag가 `small_cap`, `event_driven`, `crowded` 계열을 표시하면 `liquidity_warnings[]`에 `small_cap_liquidity_risk`, `event_driven_liquidity_risk`, `crowded_name_exit_risk`를 보존합니다.
  - `portfolio_exposure_buckets[]`는 entry 후보가 속한 노출 bucket을 기록하며, web entry 상세의 Exposure 열과 AI Brief provider 입력에 전달됩니다.
  - 따라서 `action=ENTER` 또는 `quality_state=A`는 기술적 진입 조건 통과를 뜻하며, 계좌 크기/리스크 예산/유동성 청산 능력/포트폴리오 집중/source-fundamental 확인까지 끝난 주문 가능 상태를 뜻하지 않습니다.
- mixed entry report는 `market="MIXED"`와 `markets=["KR","US"]`를 기록하고, `signal_eval_date_by_market` / `entry_session_date_by_market`을 함께 남깁니다.
- 단일 시장 entry report의 `signal_eval_date`는 buy report의 top-level 값이 없을 때 candidate들의 `eval_date`를 우선 사용해 결정합니다.
- 같은 시장 안에서 candidate들의 `eval_date`가 혼재하면, `sab entry` 리포트의 `system_issues`에 혼재 경고를 기록합니다.
- `entry_check.fatal_missing_price_ratio`는 entry price 누락 비율이 어느 수준부터 fatal인지 정합니다. 활성 운영 기본값은 `0.0`이므로 누락이 1건이라도 있으면 entry report를 쓴 뒤 `sab entry`가 non-zero로 종료합니다. YAML config가 없어도 같은 active default를 사용하며, env override는 YAML config가 로드되지 않은 경우에만 허용됩니다.

### 7.1.1 AI Brief report (entry 후속 요약)

- `sab ai-brief`는 전략 신호 생성기가 아니라 `sab entry` 결과의 후속 요약/판단 레이어입니다.
- 입력은 `*.entry.json`이며, AI Brief는 entry row를 `executable`, `blocked_but_valid`, `watch_only`, `excluded` 역할로 먼저 분류합니다.
  - 공통 base gate는 `entry_state=READY`와 `entry_price_status=available`입니다. `entry_price_status`가 없는 legacy entry row는 `entry_price`가 유효한 양수일 때만 available로 해석합니다. 이 gate를 통과하지 못하면 추천/관찰 후보가 아니라 `excluded_candidates[]`에 남깁니다.
  - `executable`: `action=ENTER` 후보입니다. 모델 추천의 최종 `action`은 계속 `ENTER`로 기록되지만, 원본 entry action은 `entry_action`으로 따로 보존합니다.
  - `blocked_but_valid`: 포트폴리오 상한 때문에 `SKIP`된 후보 또는 손절폭 대비 변동성 warning 때문에 `REVIEW`된 후보입니다. 포트폴리오/리스크로 자동 진입은 막혔지만 스윙 트레이딩 관점의 기술 셋업은 살아 있는 후보로 취급합니다.
  - `watch_only`: hybrid trigger guard 실패로 `SKIP`된 후보입니다. 추천 ranking에는 들어가지 않고 `watch_candidates[]`/`watch_tickers[]`로 분리해 재트리거 조건 확인용으로만 표시합니다.
  - 그 외 `REVIEW`/`SKIP`/unsupported action은 `excluded_candidates[]`에 남기며 추천으로 승격하지 않습니다.
- 모델 ranking 입력은 `executable` + `blocked_but_valid` 후보 중 entry report 순서 기준 최대 5개(`eligible_tickers[]`)로 제한하며, 초과분은 `cap_excluded_candidates[]`에 남깁니다. 최종 `recommendations[]`는 최대 3개입니다.
- `summary.recommendable_count`는 호환성을 위해 `executable_count + blocked_but_valid_count` aggregate로 유지합니다. `executable_tickers[]`와 `blocked_but_valid_tickers[]`는 알림/web에서 실행 가능 후보와 차단/검토 후보를 따로 표시하기 위한 역할별 원본 ticker 배열입니다.
- source provider universe는 preselection cap을 통과한 후보만이 아니라 전체 `executable`/`blocked_but_valid` 후보와 `watch_only` 후보를 포함합니다. 따라서 `source_provider_summary.final.recommendable_total`은 `summary.recommendable_count`, `watch_total`은 `summary.watch_count`와 맞아야 합니다.
- `fake` provider는 외부 GPT/news/API를 호출하지 않고, 낮은 confidence와 source issue를 남깁니다.
- AI Brief provider 입력과 최종 recommendation/watch row는 entry row의 `implementation_ready` / `investment_readiness` / `liquidity_exit_capacity` / `liquidity_warnings` / `downside_risk` / `portfolio_exposure_buckets` 필드를 보존합니다. `implementation_ready=false` 또는 context-required readiness가 있는 recommendation은 rationale/checklist에 수동 확인 caveat를 포함해야 합니다.
- `openai` provider는 OpenAI Responses API structured output으로 후보를 요약하지만, ticker 추가, `watch_only` 후보의 추천 승격, 한국어/영어 자동 주문·체결 언어를 허용하지 않습니다. `watch_candidates[]`는 `action=WATCH`, 수동 확인 이유, 재트리거 조건만 담을 수 있습니다.
- `local-json` source provider는 로컬 source report를 후보 context로 붙일 수 있지만, entry report의 후보 universe를 확장하지 않습니다.
- `http-json` source provider는 HTTPS 외부 source API에 source universe ticker 목록을 POST하고, 응답 `sources[]`를 같은 source row 계약으로 정규화합니다. Source API fetch는 HTTPS/local-private/redirect/body-size 제한을 적용하고, 반환 row URL은 syntax/local-private/DNS 검증을 통과해야 합니다. 반환 ticker가 후보 universe 밖이거나 stale/future-time/invalid URL/cap 초과이면 모델 입력에서 제외하고 `source_issues[]`로 남깁니다.
- `finnhub` source provider는 `FINNHUB_API_KEY`로 Finnhub Company News를 호출하는 US-only vendor adapter입니다. Repo ticker는 `AAPL.NAS`→`AAPL`, `BRK.B.NYS`→`BRK.B`처럼 Finnhub symbol로 변환하고, KR ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 반환된 `headline`/`url`/Unix `datetime`은 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 모델 입력에 들어갑니다.
- `polygon-news` source provider는 `POLYGON_API_KEY`로 Polygon.io Stocks News endpoint(`https://api.polygon.io/v2/reference/news`)를 호출하는 US-only vendor adapter입니다. Repo ticker는 `AAPL.NAS`→`AAPL`, `BRK.B.NYS`→`BRK.B`처럼 Polygon symbol로 변환하고, KR ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 요청은 `ticker`, `limit=10`, `order=desc`, `sort=published_utc`로 보내며 API key는 `Authorization: Bearer` header로만 전송합니다. 반환된 `title`/`article_url`/`published_utc`는 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 모델 입력에 들어갑니다.
- `alpha-vantage-news` source provider는 `ALPHA_VANTAGE_API_KEY`로 Alpha Vantage `NEWS_SENTIMENT` endpoint(`https://www.alphavantage.co/query`)를 호출하는 US-only vendor adapter입니다. Repo ticker는 `AAPL.NAS`→`AAPL`, `BRK.B.NYS`→`BRK.B`처럼 Alpha Vantage symbol로 변환하고, KR ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 요청은 `function=NEWS_SENTIMENT`, `tickers`, `time_from=<now-72h UTC>`, `sort=LATEST`, `limit=10`으로 보내며 반환된 `feed[].title`/`feed[].url`/`feed[].time_published`는 기존 source row 계약으로 정규화됩니다.
- `marketaux-news` source provider는 `MARKETAUX_API_TOKEN`으로 Marketaux Finance & Market News endpoint(`https://api.marketaux.com/v1/news/all`)를 호출하는 US-only vendor adapter입니다. Repo ticker는 `AAPL.NAS`→`AAPL`, `BRK.B.NYS`→`BRK.B`처럼 Marketaux symbol로 변환하고, KR ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 요청은 `symbols`, `countries=us`, `language=en`, `filter_entities=true`, `must_have_entities=true`, `published_after=<now-72h UTC>`, `limit=10`으로 보내며 반환된 `data[].title`/`data[].url`/`data[].published_at`은 기존 source row 계약으로 정규화됩니다.
- `benzinga-news` source provider는 `BENZINGA_API_TOKEN`으로 Benzinga News endpoint(`https://api.benzinga.com/api/v2/news`)를 호출하는 US-only vendor adapter입니다. Repo ticker는 `AAPL.NAS`→`AAPL`, `BRK.B.NYS`→`BRK.B`처럼 Benzinga symbol로 변환하고, KR ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 요청은 `token`, `tickers`, `pageSize=10`, `displayOutput=headline`, `sort=created:desc`, `publishedSince=<now-72h UTC Unix>`로 보내며 반환된 `title`/`url`/`created` 또는 `updated`는 기존 source row 계약으로 정규화됩니다.
- `naver-news` source provider는 `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`로 Naver Search API 뉴스 endpoint(`https://openapi.naver.com/v1/search/news.json`)를 호출하는 KR-only vendor adapter입니다. Repo ticker는 buy report 회사명을 검색어로 우선 사용하고, 없으면 6자리 ticker를 사용하며, `display=10`, `start=1`, `sort=date`로 요청합니다. US ticker는 요청하지 않고 `source_issues[]` WARN으로 남깁니다. 반환된 `title`(HTML 제거), `originallink` 또는 `link`, `pubDate`는 기존 source row 계약으로 정규화되며, freshness/future-time/duplicate/cap/URL safety/DNS 검증을 통과한 row만 모델 입력에 들어갑니다.
- AI Brief source URL은 HTTP(S)와 hostname이 필요하며, whitespace/control char, userinfo, literal local/private IP, localhost를 허용하지 않습니다. Offline `local-json`/source eval 경로는 DNS를 조회하지 않고, live/http 경로에서만 hostname DNS 검증을 수행합니다. `published_at`은 offset 포함 ISO 8601이어야 하고 72시간 freshness 및 15분 future skew 정책을 통과해야 합니다.
- `AI_BRIEF_ARTICLE_READER=lightpanda` 또는 `--article-reader lightpanda`는 source provider chain이 만든 canonical source URL 중 설정 cap 안의 URL만 읽어 `article_read` 메타데이터를 붙입니다. `max_urls=0` 또는 reader `none`이면 시도하지 않습니다. Cap 이후 source row는 `not_attempted`로 기록되며 attempt count에 포함하지 않습니다.
  - `article_read.status`: `not_attempted | metadata_only | accessed | verified | blocked | failed`.
  - `article_read.tier`: `metadata_backed | article_accessed | article_verified`.
  - `verified`는 bounded excerpt 안에서 ticker root 또는 buy report 회사명 term이 확인된 경우입니다. 기사 텍스트는 읽었지만 term match가 없으면 `accessed`이며, source-backed보다 강한 확인으로 보지 않습니다.
  - paywall, CAPTCHA/challenge, 로그인 요구, robots/bot block, 403/429, timeout, response-size 초과, 빈 본문, Lightpanda navigation failure는 `blocked` 또는 `failed`와 `issue_code`로 기록하고 `source_issues[]`에 보존합니다. Reader는 접근 제어를 우회하지 않습니다.
- RSS/Atom/RDF 로컬 파일 또는 live HTTPS feed URL은 `scripts/collect_ai_brief_sources.py`로 `sab.ai_brief_sources.v1` payload를 생성한 뒤 `local-json` 주입이나 source eval에 사용할 수 있습니다. 로컬 feed 파일은 offline으로 처리하고, live feed URL은 HTTPS/local-private/redirect/body-size 제한과 live item URL DNS 검증을 통과해야 합니다. fetch/timeout/invalid feed 실패는 collector top-level `issues[]` WARN으로 남습니다. collector의 top-level `issues[]` 중 eligible ticker에 속한 항목은 `local-json` provider 주입 시 `source_issues[]`로 보존되며, source eval은 같은 diagnostics를 eval 결과의 `issues[]`로 보고합니다.
- source provider chain은 comma-separated provider 목록입니다. chain은 앞 provider가 채우지 못한 남은 ticker만 다음 provider에 요청하며, provider별 `success|failed|skipped`, `covered`, `total`을 `source_provider_summary.providers[]`에 기록합니다. 중간 provider의 0건/실패 진단은 최종 chain 뒤에도 source가 없는 ticker에 대해서만 top-level `source_issues[]`/`system_issues[]`로 승격하고, fallback provider가 source를 채우면 provider summary에만 남깁니다. `none`은 단독으로만 허용하고, 중복 provider나 unsupported provider는 fail-closed입니다.
- 일반 `sab ai-brief` 실행은 명시적 `--source-provider`, `--source-report`, `--source-api-url`이 있으면 env chain으로 덮어쓰지 않습니다. 명시 입력이 없을 때만 `AI_BRIEF_SOURCE_PROVIDER_CHAIN_<MARKET>` → `AI_BRIEF_SOURCE_PROVIDER_CHAIN` → 단일 provider 기본값 순서로 해석합니다.
- scheduled runner는 요청 인자 `--source-provider`가 있으면 단일 provider를 최우선으로 사용하고, 그다음 `AI_BRIEF_SOURCE_PROVIDER_CHAIN_<MARKET>`, `AI_BRIEF_SOURCE_PROVIDER_CHAIN`, market/global 단일 provider, market/global `AI_BRIEF_SOURCE_API_URL` 순서로 fallback합니다. Chain에 `http-json`이 포함되면 matching source API URL이 필요합니다.
- OpenAI provider는 request-local source catalog의 `source_refs`만 통해 candidate source를 cite할 수 있으며, structured output schema는 `recommendations[]`/`vetoed_candidates[]` ticker를 `eligible_tickers[]`로, `watch_candidates[]` ticker를 `watch_tickers[]`로 제한합니다. `recommendations[].rank`는 배열 순서대로 `1..N` 연속값이어야 합니다.
- AI Brief 모델 provider는 source 객체(`title`/`url`/`published_at`)를 신뢰 경계 밖에서 재작성하지 않습니다. Source provider가 만든 canonical source row는 실행 중 request-local `source_id`를 받고, 모델은 `source_refs`만 선택합니다. 최종 artifact에는 로컬 코드가 `source_refs`를 canonical `sources[]` 객체로 복원한 결과만 저장합니다.
- 모델이 특정 후보에 대해 잘못된 `source_refs`를 반환하면 해당 추천은 제외하거나 watch 후보는 deterministic fallback으로 복원하고, `source_issues[]`에 `model_source_ref_*` 진단을 남깁니다. 추천 품질 게이트는 복원된 최종 artifact를 기준으로 판단합니다.
- 모델이 `watch_tickers[]` 또는 `eligible_tickers[]` 밖의 ticker를 `vetoed_candidates[]`에 반환하면 해당 row는 제외하고 `source_issues[]`에 `model_watch_veto_dropped` 또는 `model_ineligible_veto_dropped` WARN을 남깁니다.
- OpenAI가 추천하지 않기로 판단한 `eligible_tickers[]` 후보는 `vetoed_candidates[]`에 남기며, 알림과 웹 상세 화면에서 추천과 별도로 표시합니다.
- `summary`는 `entry_count`, `recommendable_count`, `executable_count`, `blocked_but_valid_count`, `watch_count`, `preselected_count`, `recommendation_count`, `vetoed_count`, `excluded_count`, `cap_excluded_count`, `source_issue_count`, `system_issue_count`를 기록해 추천/관찰/제외/모델 입력 cap을 분리해 검증할 수 있어야 합니다.
- OpenAI provider timeout/요청 실패/출력 계약 실패는 추천을 비우고 `system_issues[]`로 남깁니다. `watch_only` 후보가 있으면 모델 출력 없이도 입력 후보에서 결정론적 `WATCH` row를 만들어 `watch_candidates[]`/`watch_tickers[]` 계약과 진단 artifact를 보존합니다.
- source provider timeout/HTTP/JSON 실패는 추천 생성을 중단하지 않습니다. 단일 provider 또는 chain 최종 결과에서도 미커버 ticker가 남으면 `system_issues[]`/ticker별 `source_issues[]`로 disclose하고, fallback provider가 source를 채우면 provider summary에만 남깁니다.
- 새로 작성되는 `sab.ai_brief.v1` artifact는 top-level `brief_state`와 `brief_reason`을 항상 포함합니다. `NO_SIGNAL/no_enter_candidates`의 reason 문자열은 legacy 이름을 유지하지만 현재 의미는 preselected model 후보와 watch 후보가 모두 없는 상태입니다. `NEEDS_REVIEW_WATCH_ONLY/watch_only_trigger_pending`은 모델 ranking 후보는 없고 재트리거 확인용 watch 후보만 있는 상태입니다. `FINAL_JUDGMENT/source_backed_final`은 표시 추천이 모두 source-backed이고 source/system issue가 없으며, article reader 메타데이터가 있는 run에서는 표시 추천이 모두 `article_verified`인 최종 판단입니다.
- 그 외 후보가 있었지만 뉴스 근거가 약하거나 모델/source/system 문제가 있으면 `NEEDS_REVIEW_WEAK_NEWS`로 낮춰 표시합니다. reason은 `model_or_system_issue`, `weak_news_coverage`, `model_deferred` 중 하나이며 런타임 AI가 아니라 artifact count, watch count, recommendation source, issue 배열로만 결정합니다.
- `scripts/eval_ai_brief_recommendations.py`는 생성된 AI Brief artifact의 source-backed/manual-review 품질 게이트입니다. executable/blocked/watch/excluded/cap-excluded entry 후보 정합성, summary count 일관성, rank 연속성, watch 후보 계약, source-backed recommendation 비율, source 없는 추천의 confidence 안전성, article reader tier coverage를 오프라인으로 평가하며, 새 매매 신호를 생성하지 않습니다. Preselected model 후보가 있는데 `recommendations[]`와 `vetoed_candidates[]`가 모두 비면 source/system issue 존재 여부와 관계없이 `FAIL`입니다. Article reader 메타데이터가 하나라도 있는 run에서 모든 recommendation이 `article_verified`가 아니면 evaluator는 `WARN`을 기록하고 brief state는 `NEEDS_REVIEW_WEAK_NEWS`로 낮아질 수 있습니다. 수동 GitHub workflow와 scheduled runner는 이 평가가 `FAIL`이면 Supabase 업로드, 알림 전송, 성공 처리를 중단합니다.
- `--buy-report`는 회사명/기존 buy 근거 보강용이며, entry report에 없는 ticker를 추가하지 않습니다.
- mixed KR/US entry report는 `--market KR|US`를 요구하고, AI Brief artifact는 단일 시장만 다룹니다.

### 7.2 Sell report (row)

- `action`은 `HOLD|SELL_PARTIAL|REVIEW|SELL` 중 하나입니다.
- buy report의 `risk_guide`와 sell report의 `stop_price`, `target_price`는 모두 “의사결정 가이드”입니다. 리포트 top-level `risk_disclosure`는 해당 필드가 체결 보장이나 계좌 손실 한도가 아니며, gap/slippage로 실제 체결·손실이 가이드를 벗어날 수 있음을 명시합니다.
- sell `stop_price`, `target_price`는 override가 있으면 override가 우선합니다.
- `rules.time_stop_days`는 generic sell time stop 설정을 유지합니다. `sell_mode=sma_ema_hybrid` 리포트는 별도 `rules.hybrid_time_stop` 객체에 hybrid 전역 time stop과 `pattern_time_stops` override snapshot을 기록합니다.

### 7.2.1 Sell AI Brief report (sell 후속 판단)

- `sab sell-ai-brief`는 새 매도 신호 생성기가 아니라 `sab sell` 결과의 후속 설명/판단 레이어입니다.
- 입력은 `*.sell.json`이며, 모델 판단 대상은 원본 `action`이 `SELL`, `SELL_PARTIAL`, non-broker-state `REVIEW`인 row로 제한합니다. `HOLD`는 `excluded_hold_candidates[]`에 남기고, `broker_state=not_seen_in_toss` row는 `broker_state_review_candidates[]`에 missing-broker evidence와 함께 남긴 뒤 모델 입력과 최종 판단에서 제외합니다.
- 모델 ranking 입력은 sell report 순서 기준 최대 5개(`actionable_tickers[]`)로 제한하며, 초과분은 `cap_excluded_candidates[]`에 남깁니다. 지원하지 않는 action, ticker 누락, 잘못된 ticker row는 `unsupported_action_candidates[]`와 `system_issues[]`로 격리합니다.
- 최종 `judgments[]`는 원본 `sell_action`을 보존해야 합니다. 모델은 ticker를 추가하거나, `HOLD`를 판단으로 승격하거나, `SELL`/`SELL_PARTIAL`/`REVIEW`를 다른 action으로 바꿀 수 없습니다.
- 모델은 `ai_stance`, `confidence`, `rationale`, `checklist[]`, `sources[]`로 판단과 이유를 설명합니다. 최신 기사/source가 부족하거나 접근/검증 문제가 있으면 자신감 있는 최종 판단이 아니라 weak-news/manual-review 상태로 낮춥니다.
- OpenAI provider는 request-local `source_refs[]`만 선택하고, 최종 artifact는 로컬 코드가 canonical `sources[]`로 복원한 값만 저장합니다. 모델이 source title/url/published time을 새로 쓰는 것은 허용하지 않습니다.
- `summary`는 `evaluated_count`, `actionable_count`, `preselected_count`, `judgment_count`, `broker_state_review_count`, `excluded_hold_count`, `unsupported_action_count`, `vetoed_count`, `cap_excluded_count`, `source_issue_count`, `system_issue_count`를 기록해 broker-state review, HOLD 제외, cap, 모델 판단, 이슈를 분리 검증합니다.
- `brief_state`는 `NO_ACTION`, `FINAL_JUDGMENT`, `NEEDS_REVIEW_WEAK_NEWS`, `MODEL_OR_SYSTEM_ISSUE` 중 하나입니다. `NO_ACTION`이면 모델 호출을 시도하지 않고, actionable 후보가 있는데 judgment/veto가 모두 없거나 시스템 문제가 있으면 최종 판단으로 표시하지 않습니다.
- `scripts/eval_sell_ai_brief.py`는 source sell report와 Sell AI Brief artifact의 정합성을 평가합니다. Actionable/broker-state review/HOLD/unsupported/cap 후보 정합성, summary count, 원본 action 보존, source-backed ratio, 자동 주문/체결 문구 금지를 확인하며, 새 매도 신호를 생성하지 않습니다.
- Sell AI Brief Telegram 본문은 판단과 이유를 보여주는 HTML rich text입니다. 표시되는 `sell_action`은 원본 sell action이며 자동 주문, 자동 체결, 브로커 실행을 뜻하지 않습니다.

## 8. 운영/재현성 권장 사항

- 같은 날짜 리포트라도 “실행 시각(장중/장후)”에 따라 평가 캔들이 달라질 수 있으므로,
  - 운영 스케줄을 장마감 이후로 고정하는 것을 권장합니다.
- 리포트에 `system_issues/failures`가 있으면 신호 해석보다 **데이터 정합성 확인**을 우선합니다.
- 데이터 제공자 경고(예: PyKRX 폴백/지연)는 결과 해석 전에 반드시 확인합니다(3.5 참고).

## 9. 백로그 메모

- 현재 없음.
