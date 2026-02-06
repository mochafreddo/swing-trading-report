# KIS Developers 설정 가이드 (요약)

이 문서는 한국투자증권 KIS Developers(Open API)를 본 프로젝트에서 사용하기 위한 최소 설정 절차를 요약합니다. 최신 정책/엔드포인트는 반드시 KIS 공식 문서를 확인하세요.

## 1) 계정/앱 등록

- 한국투자증권 계좌 개설 및 KIS Developers 가입
- 애플리케이션 등록 후 다음을 발급/확인
  - AppKey, AppSecret
  - 모의투자/실전 투자 환경 구분
  - 필요 시 콜백/허용 IP 등 설정

## 2) 엔드포인트와 환경

- Base URL은 환경(모의/실전)에 따라 상이하며, KIS는 포트를 사용합니다.
  - 실전: `https://openapi.koreainvestment.com:9443`
  - 모의: `https://openapivts.koreainvestment.com:29443`
- 본 프로젝트는 `.env`의 `KIS_BASE_URL`에서 포트를 생략해도 자동으로 보정합니다
  - 예: `https://openapi.koreainvestment.com` → 내부적으로 `:9443` 부착
  - 예: `https://openapivts.koreainvestment.com` → 내부적으로 `:29443` 부착
- 본 프로젝트는 EOD(일봉) 수집 기준으로 사용하며, 토큰 발급 → 데이터 조회 순서로 호출합니다.

### 해외 주식(US) 관련

- 엔드포인트: KIS 해외주식 카테고리(예: 현재가/체결/차트 등) REST API 사용
- 차이점: 심볼 포맷(미국 티커), 통화(USD), 거래시간(미 동부 기준), 휴장일 상이
- 권장: `UNIVERSE_MARKETS=KR,US`, 필요시 환율 조회/표시(선택)
- 스크리너(랭킹): KIS 해외 시세분석 카테고리 활용
  - 거래량순위: `trade_vol`
  - 시가총액순위: `market_cap`
  - 거래대금순위: `trade_pbmn`
  - 구성/쿼리 파라미터(EXCD=거래소, LIMIT 등)는 KIS 문서 기준에 맞춰 조정
- 휴일/휴장일: KIS 해외 결제/휴일 조회 API 참고(`countries_holiday`)
  - 메타데이터에 “US Holiday: true/false, name” 등 표기 예정

## 3) 인증/토큰 흐름 (개요)

- AppKey/AppSecret으로 접근 토큰 발급(24시간 유효). KIS 정책상 “1일 1회 발급 원칙”.
- 본 프로젝트는 토큰을 로컬 캐시(`data/kis_token_<env>.json`)에 저장/재사용하여 불필요한 재발급을 피합니다.
- 구현 시 유의사항
  - 요청/응답 로깅(민감정보 제외)
  - 토큰 만료 시 자동 재발급 시도, 실패 시 리포트에 실패 내역 표시
  - 레이트 리밋 준수(호출 간 지연/재시도 정책)
  - 인증 헤더 예시: `authorization: Bearer <token>`, `appkey: <...>`, `appsecret: <...>`, `tr_id: FHKST03010100`

## 4) .env 설정 (예시)

```
DATA_PROVIDER=kis
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_BASE_URL=https://openapivts.koreainvestment.com  # 예: 모의 환경(포트는 자동 보정됨)
SCREEN_LIMIT=30
REPORT_DIR=reports
DATA_DIR=data  # 토큰/캐시 저장 디렉터리
# 전략/스크리너 옵션 예시
USE_SMA200_FILTER=true
GAP_ATR_MULTIPLIER=1.0
MIN_DOLLAR_VOLUME=5000000000
MIN_HISTORY_BARS=120
EXCLUDE_ETF_ETN=true
REQUIRE_SLOPE_UP=true
SCREENER_ENABLED=true
SCREENER_LIMIT=30
SCREENER_ONLY=false
SCREENER_CACHE_TTL=5
UNIVERSE_MARKETS=KR,US
ENTRY_CHECK_ENABLED=false
MIN_PRICE=1000
RS_LOOKBACK_DAYS=60
RS_BENCHMARK_RETURN=0.0
SELL_ATR_MULTIPLIER=1.0
SELL_TIME_STOP_DAYS=10
SELL_REQUIRE_SMA200=true

## 7) 일봉 히스토리 누적 수집

- API 특성: 일봉 기간별 시세는 호출당 최대 100봉이 반환됩니다.
- 요구사항: 전략 안정성을 위해 `MIN_HISTORY_BARS`(권장 200) 이상 확보가 필요합니다.
- 접근법:
  - 날짜 창을 이동하며 여러 번 호출해 과거로 누적 수집(첫 호출: 최신 구간, 다음 호출: 가장 오래된 일자 이전으로 확장)
  - 응답 헤더의 `tr_cont`가 제공되는 API는 이를 활용해 페이지네이션을 진행할 수 있습니다.
  - 이후 실행에서는 최근 구간만 증분 갱신하여 호출 수를 최소화합니다.
- 레이트리밋: 초당 거래건수 초과(EGW00201) 발생 시, 요청 간 최소 간격(`KIS_MIN_INTERVAL_MS`)과 백오프 재시도를 통해 안정화합니다.

## 8) 매도/보유 평가 & 장 오픈 진입 체크
- holdings.yaml 스키마를 정의해 보유 종목을 관리하고, 무효화/리스크/시간 스탑 규칙으로 Sell/Review 섹션을 생성합니다.
- 전일 리포트 후보를 기준으로, 다음 날 시초가 갭과 장초 5–15분 흐름을 확인해 진입 가이드를 표기합니다.
```

## 5) 개발 팁

- uv 사용: 기본은 `uv sync`, `.env` 자동 로딩은 `uv sync --extra dotenv`
- 커넥터 구조 제안
  - `sab/data/kis_client.py`: 토큰 발급/캐시(파일 저장), 일봉 조회 API 래퍼
  - 예외/재시도, 속도 제한, 간단 캐시(`./data/`) 포함
- 폴백 전략(옵션)
  - KIS 장애/인증 실패 시 PyKRX로 한시적 대체(리포트에 경고 표기)
- 구성 관리: `config.yaml`(예: `config.example.yaml`)에 기본값/임계치 기록 후 `.env`에서 필요한 값만 override

## 6) 주의사항

- KIS 정책/요금/허용 범위는 변경될 수 있음 → 정기적으로 공식 문서 확인
- 민감정보(AppSecret 등)는 절대 버전관리 금지
- 과도한 호출/스크래핑 금지, 이용약관 준수
