## ADR-0011 — 마켓 데이터 캐시 정책: adjusted 분리 + stale refresh + 미완성 캔들 방지

상태: 채택(Accepted)  •  날짜: 2026-03-03

### 배경

- 현재 캔들 수집은 `data/`의 JSON 캐시를 우선 사용합니다(`sab/market_data_pipeline.py`).
- 캐시 사용 여부는 “최신 완성 세션 대비 누락된 거래 세션 수(stale_sessions)”로 판단합니다.
- 하지만 현 구현에는 실전 운용에서 치명적인 정합성 문제가 있습니다.

1) **장중 호출로 생성된 “당일 미완성 일봉”이 캐시에 저장될 수 있음**
- KIS 일봉 API는 `end_date=오늘` 윈도우로 요청되며(`sab/data/kis/quote.py`), 장중에는 “오늘(세션 날짜)” 봉이 미완성 상태로 포함될 수 있습니다.
- 이 봉이 캐시에 저장되면, 장마감 이후에도 “마지막 캔들 날짜 == 세션 날짜”로 보이기 때문에 재수집 없이 그대로 재사용될 수 있습니다.
- 결과적으로 `AFTER_CLOSE` 평가가 미완성 봉을 EOD로 오인할 수 있습니다(특히 `choose_eval_index()`는 장후에는 최신 봉을 그대로 사용).

2) **`stale_sessions <= max`인 캐시는 재수집을 건너뛰어, stale 상태가 “고착”될 수 있음**
- 현재 정책은 “허용 범위 내 stale이면 캐시 사용 + provider 재수집 생략”입니다.
- 이 경우 일시적 장애로 stale 캐시를 한 번 사용하기 시작하면, 이후에도 계속 stale 캐시만 쓰고 “회복(최신화)”을 시도하지 않는 상태가 지속될 수 있습니다.

3) **adjusted(조정) vs raw(원시) 캔들이 같은 캐시 키를 공유해 혼합될 수 있음**
- `scan`은 기본 `adjusted=true`, `sell`은 기본 `adjusted=false`입니다(`docs/STRATEGY.md`, `sab/market_data_service.py`).
- 그러나 현재 캐시 키에는 adjusted 여부가 포함되지 않아, 같은 티커가 다른 실행에서 서로의 캐시를 덮어쓰거나 재사용할 수 있습니다.
- 이는 지표/가격레벨/손절/리스크 가이드 모두에 영향을 주는 데이터 정합성 이슈입니다.

### 목표

- (정합성) **완성 일봉만** 캐시에 저장/재사용하여 “장중 미완성 봉”이 장후 평가를 오염시키지 않게 합니다.
- (자연 회복) 허용 범위 내 stale 캐시를 사용하더라도, **최신화 시도**를 통해 정상 상태로 회복되게 합니다.
- (분리) `scan(adjusted)`와 `sell(raw)`의 캐시가 **서로 섞이지 않게** 합니다.
- (운영) API 장애 시에도 `market_cache_stale_sessions_*`의 의미(= fail-soft 여지)를 유지합니다.

### 비목표

- 분봉/실시간 데이터로의 전환(이 시스템은 기본적으로 완성 일봉 기반 의사결정 지원).
- 외부 캐시 인프라(Redis 등) 도입.
- provider별 완전 동일 시계열 보장(KIS/PyKRX 간 차이는 “폴백 경고”로 노출).

### 결정

#### 1) 캐시 키에 adjusted 정책을 포함한다(분리 저장)

- 신규 캐시 키는 adjusted 여부를 명시적으로 포함합니다.
  - KR: `candles_adj_{SYMBOL}` / `candles_raw_{SYMBOL}`
  - US: `candles_overseas_adj_{EXCHANGE}_{SYMBOL}` / `candles_overseas_raw_{EXCHANGE}_{SYMBOL}`
- 효과:
  - `scan`과 `sell`의 캐시가 분리되어 교차 오염이 원천 차단됩니다.
- 마이그레이션:
  - 기존 키(조정 여부 미표기)는 “legacy/ambiguous”로 간주하며, 자동 마이그레이션은 보수적으로 적용합니다.
  - 운영 권장: 업그레이드 직후 1회 provider 재수집으로 신규 키를 시딩합니다(특히 `sell(raw)`).

#### 2) “완성 세션 기준”으로 미완성/미래 캔들을 제거하고, 그 상태로만 캐시한다

- 캔들 배열의 마지막 날짜가 `latest_completed_session_date`를 초과하면, 초과분(보통 “당일 미완성 봉”)을 **제거**합니다.
- 적용 지점:
  - provider fetch 결과를 `save_json_fn()`에 저장하기 전
  - 캐시 로드 후 `stale_sessions` 계산/사용 전
- 설계 원칙:
  - 캐시 파일이 “완성 일봉만 포함한다”는 불변식을 강제해, 상위 평가 로직(예: `choose_eval_index()`)이 장후에도 안전하게 동작하도록 합니다.

#### 3) 캐시 정책을 “fresh는 캐시, stale은 refresh 시도 후 폴백”으로 변경한다

- `stale_sessions == 0`이면 캐시를 사용하고 provider 호출을 생략합니다(기존과 동일).
- `stale_sessions > 0`이면 provider 재수집을 **우선 시도**합니다.
  - 재수집 성공: 최신 캔들을 저장하고 사용합니다.
  - 재수집 실패: `stale_sessions <= max_stale_sessions`인 경우에만 캐시로 폴백합니다(= fail-soft).
  - `stale_sessions > max_stale_sessions`이면 폴백하지 않고 실패로 처리합니다(= fail-closed).
- 의미 변화(중요):
  - `market_cache_stale_sessions_*`는 “재수집 생략 임계치”가 아니라, **“장애 시 폴백 허용치”**로 해석합니다.

### 결과/영향

- 장점
  - 장중 실행이 캐시를 오염시키지 않아, 장후 평가의 신뢰도가 올라갑니다.
  - 허용 stale 설정을 쓰더라도 시스템이 자동으로 최신 상태로 회복합니다.
  - adjusted/raw 혼합이 차단되어, `scan`/`sell`의 설계 계약이 코드/캐시에 일관되게 반영됩니다.
- 단점/비용
  - 캐시 키 분리로 디스크 사용량이 증가합니다(대신 정합성 확보).
  - stale 구간에서는 provider 호출 시도가 늘어납니다(단, 성공 시 즉시 fresh로 회복).

### 대안 검토

- (대안 A) 기존 캐시 키 유지 + payload에 adjusted/시각 메타데이터 저장
  - 키 폭증 없이 정합성 검증이 가능하지만, 캐시 포맷 변경(스키마 버전/파서) 비용이 큽니다.
  - 본 ADR에서는 우선 “키 분리 + 불변식 강제”로 단순/명확한 경계를 택합니다.
- (대안 B) stale 허용 시 계속 캐시 사용(현행 유지)
  - API 절감에는 유리하지만, stale 고착/정합성 리스크가 실전에서 더 큽니다.

### 구현 체크리스트(요약)

- `sab/market_data_pipeline.py`
  - adjusted를 반영한 cache key 생성/탐색/마이그레이션
  - `latest_completed_session_date` 기반 캔들 sanitize(로드/저장 공통)
  - stale>0이면 refresh 시도, 실패 시 조건부 폴백 정책으로 변경
- `docs/STRATEGY.md`
  - 3.6 데이터 신선도(캐시) 정책 문구 업데이트(의미 변화 반영)
  - adjusted/raw 캐시 분리 계약을 명시

### 검증 기준(테스트/운영)

- 테스트(권장)
  - `stale_sessions > 0` & `stale_sessions <= max`인 캐시가 있어도 provider 재수집을 시도한다.
  - provider 재수집 실패 시, `stale_sessions <= max`이면 캐시로 폴백하고, `stale_sessions > max`이면 실패한다.
  - 장중(`latest_completed_session_date < session_date`)에 “당일 봉 포함” 캔들을 로드/수집해도, 저장/사용 시 당일 봉이 제거된다.
  - `adjusted=true`와 `adjusted=false` 요청이 서로의 캐시 키를 로드/덮어쓰지 않는다.
- 운영(스모크)
  - 같은 티커에 대해 장중 `scan`을 실행해도, 장후 `scan/sell`에서 “당일 봉이 고정된 채 재사용”되지 않고 최신화된다.
