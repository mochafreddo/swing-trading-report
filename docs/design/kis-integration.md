# 설계 — KIS 연동

인증, 캔들 수집, 랭크 스크리너, 레이트리밋 대응 등 KIS Developers API 활용 방안을 정리합니다.

## 인증/토큰

- 엔드포인트: `POST {BASE}/oauth2/tokenP` (`appkey`, `appsecret`, `grant_type=client_credentials`)
- 정책: 유효기간 약 24시간, 1일 1회 발급 권장 → `data/kis_token_<env>.json` 캐시, 만료 5분 전 갱신
- 환경: 실전/모의(vts)는 `KIS_BASE_URL`로 추론, 포트는 생략 시 실전 `:9443`/모의 `:29443` 자동 보정

## 국내 일봉(KR)

- 엔드포인트: `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice` (TR `FHKST03010100`)
- 파라미터(요지): `FID_COND_MRKT_DIV_CODE=J`, `FID_INPUT_ISCD=<티커>`, `FID_INPUT_DATE_1/2=<시작/끝>`, `FID_PERIOD_DIV_CODE=D`, `FID_ORG_ADJ_PRC=0`
- 페이징: 호출당 최대 100봉 → 약 240일 윈도우를 뒤로 이동하며 누적(≥ `MIN_HISTORY_BARS`)
- 파싱: `stck_*` 필드를 OHLCV로 매핑, 오래된 순으로 정렬 후 타깃 길이에 맞게 자름

## 해외 일봉(US)

- 엔드포인트: `/uapi/overseas-price/v1/quotations/inquire-daily-price` (TR `HHDFS76200200`)
- 파라미터: `EXCD=<거래소: NASD/NYSE/AMEX>`, `SYMB=<심볼>`, `GUBN=0`, `BYMD=<YYYYMMDD>`, `MODP=1|0(수정주가)`
- 누적: 국내와 동일한 다중 윈도우 방식
- 심볼 포맷: `SYMBOL.US`/`SYMBOL.NASD/NYSE/AMEX` 허용, `US`는 기본 `NASD`로 매핑

## KR 랭크 스크리너(거래량)

- 엔드포인트: `/uapi/domestic-stock/v1/quotations/volume-rank` (TR `FHPST01710000`)
- 전략: N개 초과 조회 → 최소 가격/거래대금 필터 → 중복 제거 → `SCREENER_CACHE_TTL`분 캐시
- 메타데이터: 캐시 상태(`hit`/`refresh`), `by_ticker` 행 맵 포함

## US 랭크 스크리너(거래량/시가총액/거래대금)

- `sab/screener/kis_overseas_screener.py`에서 KIS 해외 랭크 엔드포인트 호출
  - `trade_vol`(거래량), `market_cap`(시가총액), `trade_pbmn`(거래대금)
- 주의: 엔드포인트 경로/TR_ID는 환경에 따라 다를 수 있음. 실패 예시/문서를 공유해 주면 즉시 정합화
- 폴백: 실패 시 `screener.us_defaults` 목록 사용

## 유닛 테스트 계획 — 해외 거래대금 랭크(`trade-pbmn`)

- 대상: `KISClient.overseas_trade_value_rank` (`/uapi/overseas-stock/v1/ranking/trade-pbmn`, TR `HHDFS76320010`)
- 목적: 랭크 요청 시 파라미터/헤더 정합성 보장 및 가격 필터 로직 회귀 방지
- 케이스
  1. 정상 호출: `exchange/limit/nday/volume_filter`, 가격 구간 → `_fetch_overseas_rank_items`에 정확히 전달되고 반환값을 그대로 노출해야 함.
  2. 가격 필터 정규화: `price_min/price_max`가 `None`이나 0 이하일 때 빈 문자열, 양수일 때 `int` 문자열로 전달되어야 함(소수점 절사).
  3. 제한 수량 전달: `limit` 값이 그대로 `_fetch_overseas_rank_items`에 위임되어 페이징 로직이 동일하게 동작해야 함.

## 레이트리밋/백오프

- 서버/레이트리밋: `429/418/503` 또는 본문 `EGW00201` → 지수형 백오프 + 요청 간 최소 간격(`KIS_MIN_INTERVAL_MS`)
- 재시도: 최대 시도 제한(기본 3회). 캔들 조회는 기간 분할로 재시도 비용을 낮춤

## 휴장일/거래시간(US)

- 메타데이터에 뉴욕(ET) 정규장 개/폐장(09:30–16:00, 월–금) 상태를 표시
- KIS 휴장일 API(`countries_holiday`)를 조회해 휴일/조기폐장 여부와 메모를 캐시(`data/holidays_us.json`) 후 리포트에 반영
- 휴장일 데이터가 없을 경우 기본적으로 `US market open/closed` 상태를 표기
