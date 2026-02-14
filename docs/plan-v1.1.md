## v1.1 구현 계획 (`docs/spec-v1.1.md`)

본 문서는 `docs/spec-v1.1.md`(v1.1 구현 명세)의 수용 기준(AC1~AC5)을 만족시키기 위한 구현 순서/작업 항목/검증 체크리스트를 고정한다.

### 목표(요약)

- **웹 UI(Next.js, 로컬 Docker)**: 리포트 탐색(목록/상세/필터), holdings CRUD, scan/sell 실행 트리거(GitHub Actions `workflow_dispatch`)
- **GitHub Actions**: `scan`/`sell` 자동(`schedule`)·수동(`workflow_dispatch`) 실행, JSON 아티팩트 Supabase Storage 업로드, 자동 실행일 때만 알림, 리포트 retention(기본 30일) 정리
- **Supabase 단일 저장소**: Postgres=`holdings`, Storage=`reports`

### 비목표(Out of Scope)

- 주문/체결/계좌연동 등 자동매매
- 멀티유저 인증/권한(RLS 포함)
- 공개 배포(Vercel 등), 포트폴리오 성과 분석

---

## 구현 원칙

- **단일 소스**: holdings는 Supabase Postgres만을 “정답”으로 본다.
- **키/시크릿 노출 금지**: `SUPABASE_SECRET_KEY`/`SUPABASE_SERVICE_ROLE_KEY`, `GITHUB_PAT`는 브라우저로 절대 노출하지 않는다(Next.js 서버 측에서만 사용).
- **점진적 완성**: (1) 데이터·파이프라인 연결 → (2) 최소 UI → (3) 운영(리텐션/알림) → (4) UX·성능 개선.
- **품질 게이트**: PR에 ruff/mypy/pytest가 최소 한 번은 통과하도록 유지한다.
- **체크 기준**: `- [x]`는 “코드 작성”만이 아니라, 외부 시스템(Supabase/GitHub Actions 등) 적용이 필요한 항목은 **클라우드 적용 + 검증 완료**까지 끝난 상태를 의미한다.

---

## 산출물(Deliverables)

- **Supabase**
  - `holdings` 테이블(스키마는 `docs/spec-v1.1.md` 4.1 준수)
  - Storage 버킷 `reports`(private) + 오브젝트 키 규칙(4.2)
- **Python(엔진)**
  - `scan`/`sell` 결과를 **JSON 아티팩트(sab.report.v1)** 로 생성
  - 실행 후 Supabase Storage 업로드(키 규칙 + 중복 실행 suffix 처리)
  - (권장) retention cleanup 로직(삭제 대상 판정) 재사용 가능하게 모듈화
- **GitHub Actions**
  - `.github/workflows/scan.yml`, `sell.yml`, `cleanup.yml`
  - 자동 실행일 때만 알림 전송
- **웹 UI(Next.js)**
  - `web/`에 Next.js 앱(App Router 권장)
  - Reports/Holdings/Run 최소 화면 + 서버 라우트(또는 Server Actions)로 Supabase/GitHub 호출
- **문서**
  - `docs/runbook.md`에 “로컬 웹 실행 / GHA 시크릿 설정 / Supabase 준비” 추가/정리

---

## 마일스톤 및 작업 체크리스트

### M0. 기준선 정리(개발 환경/시크릿)

- [x] `.env.example`에 v1.1 필수 환경변수 목록을 최신화
  - KIS: `KIS_APP_KEY`, `KIS_APP_SECRET`, (선택)`KIS_BASE_URL`
  - Supabase: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(권장), `SUPABASE_SERVICE_ROLE_KEY`(레거시 폴백)
  - Web: `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT`, (표시용)`REPORT_RETENTION_DAYS`
  - Notify(자동 실행): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`(슬랙은 선택)
- [x] 로컬 실행 커맨드 확정(AGENTS.md 기준)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan`
  - `UV_CACHE_DIR=.uv-cache uv run -m sab sell`

**완료 정의**
- 로컬에서 `scan`/`sell`이 기존과 동일하게 실행되고(또는 실행 실패 시 원인이 명확히 출력되고) 기본 품질 게이트(ruff/pytest)가 돌기 시작한다.

---

### M1. Supabase 스키마/스토리지 준비

#### M1-1. Postgres `holdings`
- [x] `docs/spec-v1.1.md` 4.1의 컬럼으로 `holdings` 테이블 생성 SQL 작성/적용
- [x] `updated_at` 자동 갱신(트리거 또는 앱 레벨) 방식 결정 및 적용
- [x] 인덱스: `updated_at` 추가

#### M1-2. Storage `reports`
- [x] 버킷 `reports` 생성(private)
- [x] 오브젝트 키 규칙을 문서화 및 테스트 가능한 함수로 고정
  - 기본: `YYYY/MM/YYYY-MM-DD.buy.json`, `YYYY/MM/YYYY-MM-DD.sell.json`
  - 중복 실행: `YYYY/MM/YYYY-MM-DD-1.buy.json` …

**완료 정의**
- Supabase 콘솔에서 `holdings` CRUD가 가능하고, `reports` 버킷에 파일 업로드/다운로드가 가능한 상태다.

---

### M2. JSON 아티팩트 생성(스키마 고정) + 업로드 경로 연결

#### M2-1. 아티팩트 스키마
- [x] ADR-0002(JSON 아티팩트) 기준으로 `schema: "sab.report.v1"`를 포함한 최소 스키마 고정
- [x] 아티팩트에 “UI 리스트/요약”에 필요한 최소 메타 포함(권장)
  - 생성 시각, run_type(buy/sell), universe/provider, 주요 카운트(예: candidates/decisions 수)
  - (선택) 티커 집합(리스트 필터/검색 성능을 위해)

#### M2-2. Storage 업로드
- [x] Supabase Storage 업로더 구현(서비스 롤 키 사용)
- [x] 업로드 `contentType`을 `application/json`으로 고정(`reports` 버킷 MIME 정책 준수)
- [x] 키 충돌 시 suffix 증가 규칙 구현(존재 여부 확인 + 다음 번호 선택)
- [x] 로컬 `reports/`는 “개발/디버그 보관”으로 유지(스펙 2.5)

#### M2-3. `scan`/`sell` 후처리
- [x] `uv run -m sab scan|sell` 실행 결과에서 아티팩트 파일 생성 보장
- [x] (GHA 환경에서) 실행 후 자동으로 Storage 업로드 수행

**완료 정의**
- 로컬에서 한 번 실행 시 `reports/*.buy.json` 또는 `reports/*.sell.json`이 생성된다.
- 업로드 기능을 실행하면 `reports` 버킷에 동일 JSON이 저장되고, 키 규칙이 지켜진다.

---

### M3. GitHub Actions 워크플로우(자동/수동) + 알림 조건

#### M3-1. scan/sell 워크플로우
- [x] `.github/workflows/scan.yml` 생성
  - 트리거: `schedule`, `workflow_dispatch`
  - 입력: `universe`(`KR|US|both`), `provider`(`kis|pykrx`) (스펙 6.2)
  - 실행: `uv run -m sab scan ...`
  - 업로드: 생성된 아티팩트 → Supabase Storage
- [x] `.github/workflows/sell.yml` 생성
  - 트리거/입력: scan과 유사(단, `universe`는 필요 시만)
  - 입력 holdings: Supabase Postgres에서 읽기(단일 소스)
  - 업로드: sell 아티팩트 → Storage

#### M3-2. 알림(자동 실행만)
- [x] `github.event_name == 'schedule'`일 때만 텔레그램/슬랙 요약 전송
- [x] 수동 실행(`workflow_dispatch`) 및 로컬 CLI에서는 기본 비전송

**완료 정의**
- Actions에서 수동 실행 시 업로드까지 성공하며, 자동 실행에서만 알림이 발송된다.

---

### M4. 리포트 retention cleanup 워크플로우

- [x] `.github/workflows/cleanup.yml` 생성(`schedule`)
- [x] Storage listing → 날짜 파싱(`YYYY-MM-DD`) → 보관기간(기본 30일) 초과 삭제
- [x] 삭제 기준/로그(몇 개 삭제했는지) 출력

**완료 정의**
- 과거 날짜 테스트 오브젝트를 넣었을 때, 기준일 이후 자동 삭제가 동작한다.

---

### M5. 웹 UI(Next.js, 로컬 Docker): Reports / Holdings / Run

> 위치는 스펙 권장에 따라 `web/`로 고정한다. (현재 다른 위치에 웹 코드가 있으면 `web/`로 이동/정리한다.)

#### M5-1. 프로젝트/로컬 실행
- [x] `web/`에 Next.js 앱 생성 및 Docker Compose로 로컬 실행 가능하게 구성
- [x] 환경변수는 서버 측만 접근(서비스 롤/깃헙 PAT 포함)

#### M5-2. Reports
- [x] 목록: 최신순, 타입(buy/sell) 필터
- [x] ticker substring 검색(초기에는 “서버에서 소량(최근 N개) JSON을 읽어 contains 매칭”으로 단순 구현)
- [x] 상세: 구조화 렌더링 + Raw JSON 토글

#### M5-3. Holdings
- [x] 목록: ticker, quantity, entry_price, entry_date, notes, tags
- [x] 생성/수정/삭제(삭제는 hard delete 또는 quantity=0 정책 중 선택)
- [ ] (선택) import/export(초기 이관/백업용) — v1.1에서는 후순위

#### M5-4. Run
- [x] scan/sell 버튼 → Next.js 서버에서 GitHub API `workflow_dispatch` 호출
- [x] 트리거 후: “Actions에서 실행 중” 안내 + 워크플로우/런 링크 제공

**완료 정의**
- AC1~AC3이 웹 UI 상호작용으로 재현된다(holdings 반영, scan/sell 트리거, 업로드된 리포트 조회).

---

### M6. 안정화(문서/운영/리팩터링)

- [x] `docs/runbook.md`에 다음을 한 페이지로 정리
  - Supabase 준비(테이블/버킷)
  - GitHub Secrets 설정 목록
  - 로컬 웹 실행(Docker) + 로컬 CLI 실행(uv)
  - 장애 시 점검 포인트(권한/키/버킷/워크플로우 입력)
- [x] “오픈 결정” 항목 결정(필요 시 ADR/SPEC 업데이트) — ADR-0006
  - v1.1: Storage listing 기반 유지, index 테이블(run_history 등) 미도입
  - v1.1: 캔들 캐시(Supabase) 미도입(필요 시 v1.2에서 재검토)
  - v1.1: 로컬 전용(공개 배포 전 인증/권한(RLS) 별도 ADR/SPEC으로 결정)

**완료 정의**
- 운영자가 runbook만 보고 로컬/Actions/Supabase를 재설정할 수 있다.

---

## 테스트/검증 계획

### Python

- [x] 아티팩트 스키마 유효성 테스트(필수 필드/버전)
- [x] Storage 오브젝트 키 생성/충돌(suffix) 테스트
- [x] retention 판정 로직 테스트(날짜 파싱/경계: 오늘-30일)
- [x] (가능하면) Supabase 연동은 “클라이언트 호출”을 얇게 감싸고, 핵심 로직은 순수 함수로 분리해 단위 테스트로 커버

권장 커맨드:
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy sab`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

### Web

- [x] 서버 라우트(Reports listing/download, Holdings CRUD, Workflow dispatch) 최소 스모크 테스트
- [x] 시크릿 노출 점검(브라우저 번들에 서비스 롤/깃헙 PAT 포함 금지)

---

## AC 매핑(스펙 8)

- **AC1**: M1(Postgres holdings) + M5(Holdings UI) + M3(sell이 Supabase holdings 사용)
- **AC2**: M2(아티팩트+업로드) + M3(scan 워크플로우) + M5(Run UI)
- **AC3**: M2(아티팩트+업로드) + M3(sell 워크플로우) + M5(Run UI)
- **AC4**: M3-2(알림 조건)
- **AC5**: M4(cleanup 워크플로우)

---

## 리스크/주의사항(초기부터 고정)

- **ticker 검색**: Storage listing만으로는 ticker 인덱스가 없으므로, v1.1에서는 “최근 N개 JSON을 읽어 서버에서 검색”으로 단순 구현한다. 리포트 수가 늘면 인덱스 테이블 도입을 검토한다.
- **키 충돌 처리**: suffix 규칙은 “동일 날짜 다회 실행”에서 반드시 재현 가능해야 하므로, 업로드 직전 존재 여부 확인이 필요하다(레이스 가능성은 v1.1에서는 허용 범위로 둔다).
- **서비스 롤 키**: Next.js 서버 전용. GHA에서도 서비스 롤 키 사용은 허용하되, 로그에 출력되지 않도록 주의한다.
