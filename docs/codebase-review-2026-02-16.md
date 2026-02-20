# Swing Trading Report 코드베이스 종합 리뷰

- 리뷰 일시: 2026-02-16
- 범위: 전체 저장소 (`sab`, `web`, `.github/workflows`, `supabase`, `tests`)
- 기준 관점: Architecture, Code Quality, Maintainability, Performance, Security, Testing, DX

## Executive Summary

- Overall maturity score: **7/10**
- Biggest architectural risk: **로컬 호스트 헤더 기반 보호 경계에 고권한 키 사용이 결합된 구조**
- Biggest scaling risk: **리포트 조회 시 Storage 전체 스캔 + 개별 JSON 다운로드 루프**
- Biggest maintainability risk: **`scan/sell` 오케스트레이션 shim + 중복 market-data 로직**

검증 결과:

- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q` → **160 passed**
- `pnpm --dir web run test` → **38 passed**
- `UV_CACHE_DIR=.uv-cache uv run ruff check .` / `uv run mypy sab` / `pnpm --dir web run lint typecheck build` 모두 통과

---

## Detailed Findings

### 1) Critical - 헤더 기반 경계 신뢰 + 고권한 키 결합

- Severity: **Critical**
- File/Location:
  - `web/src/lib/local-request-guard.ts:55`
  - `web/src/lib/env.server.ts:59`
  - `web/src/lib/supabase-admin.ts:26`
  - `web/src/lib/github-actions.ts:64`
- Why it matters:
  - `x-forwarded-host`를 우선 신뢰하는 local guard로 API 접근을 제한하고,
  - 동일 서버 프로세스에서 `SUPABASE_SECRET_KEY/SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_PAT`로 실제 privileged action을 수행함.
  - 프록시/네트워크 설정 실수 또는 헤더 신뢰 경계 오판 시 권한 상승 위험이 큼.
- Refactoring suggestion:
  - 호스트 헤더 기반 보호를 보조 수단으로 격하하고, `/api/*`에 명시적 인증 계층 추가.
  - 최소안: `X-SAB-Admin-Token` + server-side constant-time check.
  - 권장안: 실제 사용자 auth/session + role 기반 인가.
- Example improvement:
  - `assertLocalRequest` 유지하되, `requireAdminAuth(request)`를 모든 route handler에서 선행 호출.

### 2) High - 리포트 조회 N+1/선형 스캔 구조

- Severity: **High**
- File/Location:
  - `web/src/app/api/reports/route.ts:74`
  - `web/src/app/api/reports/route.ts:90`
  - `web/src/lib/supabase-admin.ts:107`
- Why it matters:
  - 요청마다 Storage key를 전수 수집하고, 검색 시 `searchWindow` 범위 객체를 순차 다운로드/파싱함.
  - 데이터 증가에 따라 응답시간과 비용이 선형으로 악화됨.
- Refactoring suggestion:
  - 리포트 메타 인덱스 테이블을 별도로 유지하고 API는 SQL 조회로 전환.
- Example improvement:
  - 단기: `downloadStorageJson` 병렬화 + 매치 `limit` 도달 시 early-stop.
  - 중기: `report_index` 테이블(`key`, `type`, `report_date`, `tickers`) 도입.

### 3) High - scan/sell market data 파이프라인 중복

- Severity: **High**
- File/Location:
  - `sab/scan_market_data.py:34`
  - `sab/sell_market_data.py:28`
  - `sab/scan_market_data.py:150`
  - `sab/sell_market_data.py:98`
- Why it matters:
  - provider 초기화, fallback, 캐시 처리, 에러 누적 규칙이 두 파일에 중복되어 drift 위험이 높음.
  - 한쪽만 수정되는 순간 기능 불일치 및 회귀 가능성 증가.
- Refactoring suggestion:
  - 공통 `MarketDataService` 계층으로 통합하고 scan/sell은 모드별 전략만 주입.
- Example improvement:
  - `collect_market_data(runtime, mode, hooks)` 단일 경로로 통합.

### 4) Medium - 내부 shim API를 외부 계약처럼 고정

- Severity: **Medium**
- File/Location:
  - `sab/scan.py:15`
  - `tests/test_scan_shim_compat.py:6`
  - `tests/test_sell_shim_compat.py:39`
- Why it matters:
  - 내부 `_impl` 위임 심볼이 테스트로 고정되어 구조 리팩터링 비용이 커짐.
- Refactoring suggestion:
  - 공개 API를 최소화(`run_scan`, `run_sell`)하고 내부 helper 노출 계약을 제거.
- Example improvement:
  - shim compatibility 테스트 축소 또는 제거, behavior 테스트 중심으로 전환.

### 5) Medium - `load_config` 단일 함수 과부하

- Severity: **Medium**
- File/Location:
  - `sab/config.py:148`
- Why it matters:
  - 환경/파일 병합, 기본값, 정책 검증, 교차 규칙 처리까지 한 함수에 집중됨.
  - 필드 추가 시 side-effect 추적이 어려움.
- Refactoring suggestion:
  - 섹션별 설정 객체(`data/strategy/sell/fx`)로 분리 후 조합 단계에서 검증.
- Example improvement:
  - parser 계층 + validator 계층 분리.

### 6) Medium - API 입력정책과 워크플로 정책 불일치

- Severity: **Medium**
- File/Location:
  - `web/src/lib/schemas.ts:144`
  - `web/src/app/api/run/route.ts:36`
  - `.github/workflows/scan.yml:113`
- Why it matters:
  - API는 허용하지만 워크플로에서 나중에 실패하는 조합이 존재하여 UX/운영 추적성이 떨어짐.
- Refactoring suggestion:
  - API 스키마에 워크플로 제약을 동일 반영.
- Example improvement:
  - `provider=pykrx`인 경우 `universe=KR`만 허용하도록 refine 추가.

### 7) Medium - API route 계층 테스트 공백

- Severity: **Medium**
- File/Location:
  - `web/vitest.config.ts:7`
  - `web/src/app/api/run/route.ts:12`
  - `web/src/app/api/reports/route.ts:37`
- Why it matters:
  - 테스트가 `src/lib/__tests__`로 제한되어 route handler의 상태코드/에러 매핑 회귀를 잡기 어려움.
- Refactoring suggestion:
  - route-level integration test 추가.
- Example improvement:
  - `/api/run` invalid JSON, invalid payload, guard failure, GitHub 4xx/5xx 매핑 케이스 검증.

### 8) Medium - KIS 핵심 재시도/토큰 경로 테스트 부족

- Severity: **Medium**
- File/Location:
  - `sab/data/kis_client.py:204`
  - `sab/data/kis_client.py:292`
  - `tests/test_kis_client_overseas_holidays.py:22`
  - `tests/test_kis_client_overseas_rank.py:18`
- Why it matters:
  - 현재 테스트는 holiday/rank 일부 분기에 집중되어 핵심 신뢰성 경로 커버가 약함.
- Refactoring suggestion:
  - `ensure_token`, `daily_candles`, `overseas_price_detail`의 오류 코드(`EGW00123`, rate limit) 재시도 시나리오 확장.
- Example improvement:
  - stale token cache, malformed JSON, 429/503 backoff 테스트 추가.

### 9) Low - 대형 클라이언트 컴포넌트 집중도

- Severity: **Low**
- File/Location:
  - `web/src/components/holdings-client.tsx:1`
  - `web/src/components/holdings-client.tsx:165`
  - `web/src/components/reports-client.tsx:1`
- Why it matters:
  - UI 상태/비즈니스 로직/fetch 로직이 단일 파일에 결합되어 유지보수성이 떨어짐.
- Refactoring suggestion:
  - query/form/state를 custom hook으로 분리하고 view 컴포넌트와 분리.
- Example improvement:
  - `useHoldingsQuery`, `useHoldingsForm`, `HoldingsTable`, `ReportsList`, `ReportDetail` 분리.

### 10) Low - 컨테이너 기본 엔트리 dev 모드

- Severity: **Low** (현재 로컬 운영 전제)
- File/Location:
  - `web/Dockerfile:11`
  - `docker-compose.yml:22`
- Why it matters:
  - production 오인 배포 시 성능/보안 기본값 약화.
- Refactoring suggestion:
  - dev/prod Dockerfile 분리 및 프로파일 기반 실행.
- Example improvement:
  - `Dockerfile.prod`에서 `next build && next start`, non-root user 적용.

---

## Refactoring Roadmap

### Quick wins (1-2 days)

1. `/api/*` 공통 인증 계층 도입 (`X-SAB-Admin-Token` 또는 사용자 auth).
2. `/api/run` 입력정책을 워크플로 정책과 일치시키기.
3. API route 통합 테스트 추가 (`run`, `reports`, `holdings`).
4. `reports` 검색 루프에 병렬화/early-stop 적용.

### Mid-term improvements

1. 리포트 메타 인덱스 테이블 도입 후 Storage 전수 조회 제거.
2. `scan_market_data`/`sell_market_data` 공통 서비스화.
3. `config.py`를 섹션 기반 파서+검증 구조로 분해.

### Long-term architecture improvements

1. Next.js API에서 고권한 키 직접 사용 제거(내부 백엔드로 privileged action 분리).
2. Python 앱 레이어 명시화: `application / domain / infra` 재구성.
3. 리포트 생성 파이프라인과 조회 API를 이벤트/인덱스 기반으로 분리.

---

## 추가 메모

- 현재 품질 게이트(테스트/린트/타입체크/빌드)는 안정적으로 통과하며 기본 품질 바닥은 확보되어 있음.
- 리스크의 핵심은 “기능 불능”보다 “경계 보안 + 데이터 증가 시 구조적 비용 증가 + 내부 구조 복잡도”에 집중되어 있음.
