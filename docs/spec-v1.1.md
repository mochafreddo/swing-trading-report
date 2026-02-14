# SPEC — v1.1 구현 명세 (Next.js + Supabase + GitHub Actions)

상태: Draft  
대상 릴리스: v1.1  
목적: PRD/ADR의 결정을 바탕으로 **v1.1 구현에 필요한 인터페이스/데이터/플로우를 고정**한다.

## 0. 참고 문서(우선순위)

- `docs/PRD.md`
- `docs/adr/ADR-0002-report-artifacts-dashboard.md` (JSON 아티팩트)
- `docs/adr/ADR-0004-web-stack-nextjs-local-docker.md` (Next.js + 로컬 Docker)
- `docs/adr/ADR-0005-automation-github-actions-supabase.md` (GHA schedule + Supabase)
- `docs/adr/ADR-0001-config-precedence.md`, `docs/adr/ADR-0003-config-conflict-policy.md` (설정/충돌 정책)

## 1. v1.1 목표 / 비목표

### 1.1 목표

- **웹 UI(Next.js, 로컬 Docker)** 에서 다음 기능 제공
  - 리포트 목록/상세/필터(= JSON 아티팩트 탐색)
  - 보유 목록(holdings) **CRUD**
  - 웹에서 `scan`/`sell` 실행 트리거(= GitHub Actions `workflow_dispatch`)
- **GitHub Actions** 로 다음 기능 제공
  - `scan`/`sell` 자동 실행(`schedule`)
  - `scan`/`sell` 수동 실행(`workflow_dispatch`) — 웹 UI에서 트리거
  - 산출물(JSON 아티팩트) **Supabase Storage 업로드**
  - 알림은 **자동 실행일 때만** 전송
  - **리포트 retention 기본 30일** 정리 작업 수행
- **Supabase** 를 단일 저장소로 사용
  - Postgres: holdings(보유 목록) 단일 소스
  - Storage: 리포트(공식 보관)

### 1.2 비목표(Out of Scope)

- 자동 매매(주문/체결/계좌연동)
- 멀티유저 인증/권한(로그인)
- 클라우드 상시 운영(VPS) 및 Vercel 공개 배포(추후)
- 리포트/보유 이력 기반의 “포트폴리오 성과 분석” (추후)

## 2. 용어 정의

- **자동 실행**: GitHub Actions `schedule`로 시작된 실행
- **수동 실행**: `workflow_dispatch`(웹 UI 트리거) 또는 로컬 CLI 실행
- **공식 보관**: Supabase Storage에 보관된 JSON 아티팩트
- **개발/디버그 보관**: 로컬 `reports/` 디렉터리의 JSON 아티팩트

## 3. 시스템 플로우(상위)

### 3.1 웹에서 리포트 보기

1. 웹 UI(Next.js)가 Supabase Storage에서 리포트 목록을 조회한다.
2. 사용자가 리포트를 선택하면 해당 JSON을 읽어 화면에 렌더링한다.

### 3.2 웹에서 holdings CRUD

1. 웹 UI(Next.js)가 Supabase Postgres의 `holdings` 테이블을 조회/수정한다.
2. 변경된 holdings는 다음 `sell` 실행의 입력으로 사용된다(단일 소스).

### 3.3 웹에서 scan/sell 실행

1. 사용자가 웹 UI에서 `scan` 또는 `sell`을 실행한다.
2. 웹 UI는 GitHub API로 `workflow_dispatch`를 호출한다.
3. GitHub Actions가 실행되며 `uv run -m sab scan|sell`을 수행한다.
4. 생성된 JSON 아티팩트를 Supabase Storage에 업로드한다.
5. 웹 UI는 Supabase에서 최신 리포트를 다시 조회해 확인한다.

### 3.4 자동 실행 및 알림

- GitHub Actions `schedule`로 `scan`/`sell` 실행
- 결과 업로드 후 **자동 실행일 때만** 알림(텔레그램/슬랙) 전송

## 4. 데이터/저장소 설계(Supabase)

### 4.1 Postgres: `holdings` (필수)

**역할**: 현재 보유 목록(단일 소스). `sab/holdings_loader.py`의 `Holding` 모델을 1:1로 대응한다.

- **테이블명**: `holdings`
- **기본키**: `ticker` (TEXT)
- **컬럼(권장)**
  - `ticker` TEXT PRIMARY KEY
    - KR: `005930`(6자리 코드) 등
    - US: `AAPL.US` 또는 `AAPL.NASD/NYSE/AMEX` (현재 엔진이 허용하는 포맷)
  - `quantity` DOUBLE PRECISION NOT NULL DEFAULT 0
  - `entry_price` DOUBLE PRECISION NOT NULL DEFAULT 0
  - `entry_currency` TEXT NULL
  - `entry_date` DATE NULL
  - `strategy` TEXT NULL
  - `notes` TEXT NULL
  - `tags` TEXT[] NOT NULL DEFAULT '{}'
  - `stop_override` DOUBLE PRECISION NULL
  - `target_override` DOUBLE PRECISION NULL
  - `created_at` TIMESTAMPTZ NOT NULL DEFAULT now()
  - `updated_at` TIMESTAMPTZ NOT NULL DEFAULT now()
- **인덱스(권장)**
  - `updated_at` (정렬/최근 수정 기준 UI에 유리)
- **데이터 규칙**
  - `quantity <= 0`인 행은 UI에서 “비활성(또는 숨김)” 처리할 수 있다(삭제와 별개).
  - ticker 포맷은 엔진이 해석 가능한 값만 허용한다.

> 참고: v1.1에서는 “거래 이력/복수 체결/분할 매수”를 저장하지 않는다(현 보유 상태만).

### 4.2 Storage: `reports` 버킷 (필수)

**역할**: JSON 리포트(공식 보관).

- **버킷명(권장)**: `reports`
- **권한(권장)**: private
- **MIME 정책(권장)**: `allowed_mime_types = ["application/json"]`
  - 업로더는 반드시 `contentType=application/json`으로 업로드한다.
- **오브젝트 키 규칙(권장)**
  - `YYYY/MM/YYYY-MM-DD.buy.json`
  - `YYYY/MM/YYYY-MM-DD.sell.json`
  - 같은 날짜 다회 실행 시 suffix 유지:
    - `YYYY/MM/YYYY-MM-DD-1.buy.json`
    - `YYYY/MM/YYYY-MM-DD-2.sell.json`
- **콘텐츠**: ADR-0002의 JSON 아티팩트 스키마(`schema: "sab.report.v1"`) 준수

### 4.3 (선택) Postgres: `run_history`

v1.1에서는 “GitHub Actions 링크”로 충분하므로 **생략**한다(ADR-0006). 필요해지면 다음 테이블을 추가한다.

- `run_history(id, run_type, trigger, started_at, finished_at, status, github_run_url, report_keys[])`

### 4.4 (선택) 캔들 캐시(리텐션은 `max()` 기반)

v1.1에서는 **미도입**한다(ADR-0006). API 호출 수/속도가 문제가 되면 v1.2에서 재검토한다.

- **정책**: 티커별 **최근 `max(min_history_bars, retention_bars)` 봉**만 유지
  - `min_history_bars`: 지표 계산에 필요한 최소 봉수(예: 200)
  - `retention_bars`: 운영 상 유지 봉수(예: 250)
- **구현 선택지(후보)**
  - (A) Postgres row-per-bar (정규화, 인덱스/쿼리 유리)
  - (B) Postgres JSONB-per-ticker (구현 단순, v1.1에 적합)

## 5. 리텐션(보관/정리) 정책

### 5.1 리포트 retention (기본값 30일)

- **기본값**: 30일
- **정리 기준**: 오브젝트 키의 날짜(`YYYY-MM-DD`)를 `report_date`로 해석해,
  - `report_date < (오늘 - 30일)`이면 삭제 대상
- **정리 주체(권장)**: GitHub Actions의 별도 `cleanup` 워크플로우(매일 1회 또는 주 1회)
- **로컬 `reports/`**: 개발 편의상 남겨도 되지만, 필요 시 동일 기준으로 정리한다.

### 5.2 알림 전송 조건

- 자동 실행(`schedule`)일 때만 요약을 전송(기본 채널: 텔레그램)
- 수동 실행(`workflow_dispatch`, 로컬 CLI)은 기본 비전송
- 실패/에러 알림(기본)은 GitHub Actions 기본 알림(Notifications/메일/모바일 푸시)로 수신한다.

## 6. GitHub Actions 워크플로우(권장 구성)

### 6.1 워크플로우 파일(예시)

- `.github/workflows/scan.yml`
  - 트리거: `schedule`, `workflow_dispatch`
  - 실행: `uv run -m sab scan ...`
  - 업로드: 생성된 `reports/*.buy.json` → Supabase Storage `reports` 버킷
  - 알림: `schedule`일 때만 텔레그램으로 요약 전송(실패/에러는 GitHub 기본 알림)
- `.github/workflows/sell.yml`
  - 트리거: `schedule`, `workflow_dispatch`
  - 실행: `uv run -m sab sell ...`
  - 입력: holdings는 Supabase(Postgres)에서 읽는다(단일 소스)
  - 업로드: `reports/*.sell.json` → Supabase Storage
  - 알림: `schedule`일 때만 텔레그램으로 요약 전송(실패/에러는 GitHub 기본 알림)
- `.github/workflows/cleanup.yml` (권장)
  - 트리거: `schedule`(매일 1회 또는 주 1회)
  - 실행: Supabase Storage에서 30일 초과 리포트 삭제

### 6.2 `workflow_dispatch` 입력(최소)

v1.1에서는 최소 입력만 제공한다(필요 시 확장).

- `universe`: `KR` | `US` | `both` (scan에만)
- `provider`: `kis` | `pykrx` (기본 `kis`, 해외 포함 시 `kis` 권장)

### 6.3 시크릿/환경변수(필수)

- KIS
  - `KIS_APP_KEY`
  - `KIS_APP_SECRET`
  - (선택) `KIS_BASE_URL`
- Supabase
  - `SUPABASE_URL`
  - `SUPABASE_SECRET_KEY`(권장) 또는 `SUPABASE_SERVICE_ROLE_KEY`(레거시)
- 알림(기본, 자동 실행에만 사용)
  - Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

## 7. 웹 UI(Next.js) 명세(로컬 Docker)

### 7.1 구현 위치(권장)

- Next.js 앱 디렉터리: `web/` (repo 루트 하위)
- 로컬 구동: Docker Compose로 `web` 서비스 실행

### 7.2 화면/기능(최소)

- **Reports**
  - 목록: 최신순, 타입(buy/sell) 필터, ticker substring 검색
  - 상세: JSON 내용을 표/섹션으로 렌더링 + Raw JSON 보기
- **Holdings**
  - 목록: ticker, quantity, entry_price, entry_date, notes, tags
  - 생성/수정/삭제
  - (선택) import/export 버튼(초기 이관/백업용)
- **Run**
  - scan/sell 트리거 버튼
  - 트리거 후: “Actions에서 실행 중” 안내 + 워크플로우 페이지 링크

### 7.3 보안/키 관리(원칙)

- **서버 전용 Supabase 키(`SUPABASE_SECRET_KEY` 또는 `SUPABASE_SERVICE_ROLE_KEY`)는 브라우저로 노출하지 않는다.**
  - Supabase 접근은 Next.js **서버 측(Route Handler/Server Action)** 에서만 수행한다.
- v1.1은 로컬 전용이므로 인증은 생략 가능하지만,
  - 추후 Vercel 등 공개 배포 시 인증/권한(RLS 포함)을 별도 SPEC/ADR로 추가한다.
  - (현재) `holdings`는 RLS 강제 + `anon`/`authenticated` 권한 제거로 서비스 키 기반(server-only) 접근만 허용한다.

### 7.4 웹 UI 환경변수(예시)

- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`(권장) 또는 `SUPABASE_SERVICE_ROLE_KEY`(레거시)
- `GITHUB_OWNER`
- `GITHUB_REPO`
- `GITHUB_PAT` (workflow_dispatch 호출용, 로컬에만 저장)
- `REPORT_RETENTION_DAYS=30` (UI 표시/안내용; 실제 삭제는 Actions에서 수행)

## 8. v1.1 수용 기준(AC)

- AC1: 웹 UI에서 holdings를 CRUD하면 Supabase `holdings`에 반영되고, 이후 `sell` 입력으로 사용된다.
- AC2: 웹 UI에서 `scan`을 트리거하면 GitHub Actions가 실행되고, Buy 아티팩트가 Supabase Storage에 업로드된다.
- AC3: 웹 UI에서 `sell`을 트리거하면 GitHub Actions가 실행되고, Sell 아티팩트가 Supabase Storage에 업로드된다.
- AC4: 자동 실행(`schedule`) 결과만 텔레그램/슬랙 요약 알림이 전송된다.
- AC5: cleanup 워크플로우가 30일을 초과한 리포트를 정리한다(기본값).

## 9. 오픈 결정(정리)

v1.1에서 아래 항목은 “미도입(보류)”로 정리한다(ADR-0006).

- 리포트 목록: Storage listing 기반 유지, `run_history`/인덱스 테이블 미도입
- 캔들 캐시: 미도입(필요 시 v1.2에서 JSONB-per-ticker 우선 검토)
- 인증/권한: v1.1 로컬 전용(공개 배포 전 별도 ADR/SPEC으로 결정)
