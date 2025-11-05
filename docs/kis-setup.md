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
```

## 5) 개발 팁

- uv 사용: `uv add requests python-dotenv`
- 커넥터 구조 제안
  - `sab/data/kis_client.py`: 토큰 발급/캐시(파일 저장), 일봉 조회 API 래퍼
  - 예외/재시도, 속도 제한, 간단 캐시(`./data/`) 포함
- 폴백 전략(옵션)
  - KIS 장애/인증 실패 시 PyKRX로 한시적 대체(리포트에 경고 표기)

## 6) 주의사항

- KIS 정책/요금/허용 범위는 변경될 수 있음 → 정기적으로 공식 문서 확인
- 민감정보(AppSecret 등)는 절대 버전관리 금지
- 과도한 호출/스크래핑 금지, 이용약관 준수
