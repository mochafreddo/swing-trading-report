# KIS Developers 설정 가이드 (요약)

상태: Accepted (설정 가이드)

이 문서는 한국투자증권 KIS Developers(Open API)를 본 프로젝트에서 사용하기 위한 최소 설정 절차를 요약합니다. 최신 정책/엔드포인트는 반드시 KIS 공식 문서를 확인하세요.

## 문서 상태

### 현재 제공

- KIS AppKey/AppSecret 기반 토큰 발급, 로컬 토큰 캐시, 국내/해외 일봉 조회, 해외 휴일 캐시를 현재 구현이 사용합니다.
- 해외 휴일/조기폐장 정보는 `holidays_us.json`과 `market_status`/session-state 경로에 반영됩니다.
- 시크릿은 `.env`, 비시크릿은 `config.yaml`에 두는 분리 원칙이 현재 계약입니다.

### 실험

- 별도 실험용 KIS 연동 문서는 운영하지 않습니다. API drift 확인은 공식 문서와 회귀 테스트를 우선합니다.

### 백로그

- GitHub Actions 등 비로컬 환경에서의 IP allowlist 운영 자동화는 backlog로 남아 있습니다.

### 폐기 후보

- 저장소 문서를 KIS 공식 정책의 단일 source of truth로 취급하는 방식은 채택하지 않습니다.

## 1) 계정/앱 등록

- 한국투자증권 계좌 개설 및 KIS Developers 가입
- 애플리케이션 등록 후 다음을 발급/확인
  - AppKey, AppSecret
  - 모의투자/실전 투자 환경 구분
  - 필요 시 콜백/허용 IP 등 설정

참고:

- 자동 실행을 GitHub Actions에서 돌릴 경우, KIS 설정이 “특정 IP만 허용” 형태라면 실행이 막힐 수 있습니다.
  - 이 경우 고정 IP 환경(VPS 등) 또는 로컬 런너로 전환이 필요할 수 있습니다.

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
  - 현재 구현은 캐시/세션 상태/후보 `market_status`에 휴일·조기폐장 정보를 반영합니다.

## 3) 인증/토큰 흐름 (개요)

- AppKey/AppSecret으로 접근 토큰 발급(24시간 유효). KIS 정책상 “1일 1회 발급 원칙”.
- 본 프로젝트는 토큰을 로컬 캐시(`data/kis_token_<env>.json`)에 저장/재사용하여 불필요한 재발급을 피합니다.
- 구현 시 유의사항
  - 요청/응답 로깅(민감정보 제외)
  - 토큰 만료 시 자동 재발급 시도, 실패 시 리포트에 실패 내역 표시
  - 레이트 리밋 준수(호출 간 지연/재시도 정책)
  - 인증 헤더 예시: `authorization: Bearer <token>`, `appkey: <...>`, `appsecret: <...>`, `tr_id: FHKST03010100`

## 4) 설정(권장)

### 4-1) `.env` (시크릿만)

`.env`는 커밋하지 않으며, 시크릿만 둡니다.

```bash
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
```

### 4-2) `config.yaml` (비시크릿)

- 샘플은 repo 루트의 `config.example.yaml`을 참고하세요.
- Base URL(모의/실전), 요청 간 최소 간격(`kis.min_interval_ms`), 스크리너/전략 임계치 등은 `config.yaml`에서 관리합니다.
- 주의: `config.yaml`과 `.env`에 **동일 키를 중복 정의하지 않습니다**(충돌 시 실패). 예를 들어 `KIS_BASE_URL`(env)과 `kis.base_url`(yaml)을 동시에 두면 안 됩니다.

## 5) 운영 팁

- 토큰은 24시간 유효(정책 변경 가능). 본 프로젝트는 토큰을 `data/`에 캐시해 같은 날 재발급을 피합니다.
- 레이트리밋 `EGW00201` 대응:
  - `kis.min_interval_ms`(또는 `KIS_MIN_INTERVAL_MS`)를 늘리고
  - 백오프 재시도로 안정화합니다.

## 6) 개발 팁

- uv 사용: 기본은 `uv sync` (기본 내장 파서로 `.env` 자동 로딩 지원)
- (선택) `python-dotenv` 기반 고급 파싱: `uv sync --extra dotenv`
- 커넥터 구조 제안
  - `sab/data/kis_client.py`: 토큰 발급/캐시(파일 저장), 일봉 조회 API 래퍼
  - 예외/재시도, 속도 제한, 간단 캐시(`./data/`) 포함
- 폴백 전략(옵션)
  - KIS 장애/인증 실패 시 PyKRX로 한시적 대체(리포트에 경고 표기)
- 구성 관리: 비시크릿은 `config.yaml`, 시크릿은 `.env`(중복 키 금지)

## 7) 주의사항

- KIS 정책/요금/허용 범위는 변경될 수 있음 → 정기적으로 공식 문서 확인
- 민감정보(AppSecret 등)는 절대 버전관리 금지
- 과도한 호출/스크래핑 금지, 이용약관 준수
