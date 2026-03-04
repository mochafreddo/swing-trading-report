# 런북 — CLI + Web 운영 가이드

로컬에서 CLI와 웹 UI를 실행/디버그/운영하기 위한 실무 지침입니다.

## 설치/준비

- uv 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- 의존성 동기화: `UV_CACHE_DIR=.uv-cache uv lock -U && UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- toolchain 동기화: `mise install` (도구 버전 변경 시 `mise lock --platform linux-x64,macos-arm64 && mise install`)
  - 설정:
    - `config.yaml` 생성(기본값은 `config.example.yaml` 참고)
    - `.env`에는 v1.1 필수 키를 작성:
      - KIS: `KIS_APP_KEY`, `KIS_APP_SECRET`, (선택) `KIS_BASE_URL`
      - Supabase: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(권장), `SUPABASE_SERVICE_ROLE_KEY`(레거시 폴백)
      - Web(기본): `SAB_BASIC_AUTH_USER`, `SAB_BASIC_AUTH_PASS`, `SAB_SESSION_SECRET`, (표시용) `REPORT_RETENTION_DAYS`
      - Run 트리거(선택): `RUN_DISPATCH_ENABLED`(기본 `0`), `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT` (`RUN_DISPATCH_ENABLED=1`일 때 필수)
        - 하위 호환: `RUN_DISPATCH_ENABLED`가 비어 있고 `GITHUB_*` 3종이 모두 설정된 기존 환경은 자동 활성
      - Web 로그인 제한(선택): `SAB_LOGIN_MAX_ATTEMPTS`, `SAB_LOGIN_WINDOW_SECONDS`, `SAB_LOGIN_BLOCK_SECONDS`
      - 런타임 상태 저장소(선택): `SAB_RUNTIME_STATE_STORE` (`supabase`/`memory`, 기본은 테스트 외 `supabase`)
      - Web 로컬 실행(선택): `WEB_HOST_PORT`(prod, 기본 `55300`), `WEB_DEV_HOST_PORT`(dev, 기본 `55301`)
      - Notify(자동 실행): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
    - `config.yaml`과 `.env`에 동일 키를 중복 정의하지 않기(충돌 시 실패)
    - 선택: `uv sync --extra pykrx`로 KR 폴백/프로바이더 활성화
- 런타임:
  - Python 3.13+
  - Node.js + pnpm (버전 기준: `web/Dockerfile`, `web/package.json`)
  - 권장: `mise install`로 toolchain 동기화(`mise.lock` 기준)
  - 권장: `eval "$(mise activate zsh)"` 또는 `mise x -- <cmd>`로 mise 환경에서 실행
  - Docker Desktop + Docker Compose
- Supabase(권장):
  - 보유 목록/리포트/실행 이력은 Supabase(Postgres/Storage)를 단일 소스로 사용합니다.
  - GitHub Actions 런너가 자동 실행할 때도 동일한 Supabase를 사용합니다.

## 웹 UI 로컬 실행(Next.js + Docker)

- 기본 운영 기준:
  - `web` 서비스는 이미지 빌드 시 `pnpm run build`를 수행하고, 런타임 엔트리는 `pnpm run start`만 실행합니다.
- 전환 직후 1회 정리:
  - `docker compose down --remove-orphans && docker compose up -d --build web`
- 일반 재기동:
  - `docker compose up -d --build web`
- 개발 모드(HMR):
  - `docker compose --profile dev up -d --build web-dev`
- 개발 모드 중지:
  - `docker compose stop web-dev`
- 강제 재생성(문제 시):
  - `docker compose stop web`
  - `docker compose rm -f web`
  - `docker compose up -d --build web`
- 로그 확인(prod):
  - `docker compose logs -f web`
- 로그 확인(dev):
  - `docker compose --profile dev logs -f web-dev`
- 중지:
  - `docker compose stop web`
- 접속(prod):
  - `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
- 접속(dev):
  - `http://localhost:${WEB_DEV_HOST_PORT}` (기본값 `55301`)
- 인증:
  - `/login` 페이지에서 관리자 계정(`SAB_BASIC_AUTH_USER/PASS`)으로 로그인하면 HttpOnly 세션 쿠키가 발급됩니다.
- 포트 변경(prod):
  - `.env`에 `WEB_HOST_PORT=55444` 설정 후 `docker compose up -d --build web`
- 포트 변경(dev):
  - `.env`에 `WEB_DEV_HOST_PORT=55445` 설정 후 `docker compose --profile dev up -d --build web-dev`
- 기본 화면:
  - `Reports`: Storage 리포트 목록/상세/검색
  - `Holdings`: Supabase `holdings` CRUD
  - `Run`: scan/sell `workflow_dispatch` 실행 트리거

## 보유 목록(holdings)

- 보유 목록은 **웹 UI(Next.js)에서 CRUD**로 관리합니다(단일 사용자 기준).
- `quantity<=0` 항목은 Holdings UI에서 비활성으로 취급되며, 기본은 숨김이고 토글로 표시할 수 있습니다.
- (선택) `holdings.yaml` import/export는 **v1.1 미구현**이며, v1.2에서 초기 이관/백업 용도로 도입 예정입니다.

## 자주 쓰는 실행

- Buy 스캔(KR+US 스크리너 + 워치리스트)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe both`
- Buy 스캔(스크리너만, 상위 20)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe screener --screener-limit 20`
- 보유 매도/보류 평가
  - `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
- 웹 UI(Next.js)
  - `docker compose up -d --build web`
  - 접속(prod): `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
  - 개발 모드(HMR): `docker compose --profile dev up -d --build web-dev`
  - 접속(dev): `http://localhost:${WEB_DEV_HOST_PORT}` (기본값 `55301`)
  - 또는 웹 디렉터리에서 직접 실행: `pnpm install && pnpm run dev`

- 자동 실행(GitHub Actions)
  - `schedule`로 scan/sell을 실행하고, 결과를 Supabase에 저장합니다.
  - 알림은 자동 실행일 때만 전송합니다.
  - 텔레그램: 리포트 본문(매수 후보/매도·점검 후보 상위 5건 + 나머지 개수)을 전송합니다.
  - 슬랙: 기존 key=value 요약 포맷을 유지합니다.
- Audit 실행(GitHub Actions)
  - 감사 워크플로: `.github/workflows/audit.yml`
  - 트리거: `pull_request`, `workflow_dispatch`, 매주 월요일 11:00 UTC(`0 11 * * 1`)
  - Job:
    - `workflow_audit`: `rhysd/actionlint`로 워크플로 YAML 정합성 검사
    - `security_audit`: `aquasecurity/trivy-action`으로 `vuln,secret` 통합 검사
  - 차단 기준: `HIGH,CRITICAL` 발견 시 실패(`ignore-unfixed=true`)
  - 산출물: `trivy-results.json` 아티팩트(성공/실패와 무관하게 업로드)
- 로컬 CLI 업로드(선택)
  - 기본은 로컬 파일 생성만 수행합니다.
  - 로컬 실행에서도 Supabase 업로드가 필요하면 `SAB_UPLOAD_REPORTS=true`를 설정합니다.

## Audit 수동 점검

- 빠른 점검:
  - `trivy fs .`
- CI 동일 정책 점검:
  - `trivy fs --scanners vuln,secret --severity HIGH,CRITICAL --ignore-unfixed --format json --output trivy-results.json .`
- 취약점 예외:
  - `.trivyignore`에 임시 예외만 등록
  - 항목별 만료일/사유 주석 필수
  - 만료된 예외는 즉시 삭제

## PR 차단 기준(브랜치 보호)

- `main` 브랜치 보호 규칙은 classic branch protection으로 관리합니다.
- 현재 운영 모드는 임시 `solo-dev`로, `main` 직접 push를 허용합니다.
- `required_status_checks=null`, `required_pull_request_reviews=null` 상태입니다.
- `enforce_admins=true`로 관리자 우회를 차단합니다.
- `allow_force_pushes=false`, `allow_deletions=false`는 유지합니다.
- PR 기반 운영으로 복귀 시 `docs/governance/main-branch-protection.stage1.payload.json`을 적용하고,
- 아래 4개 Required status checks를 복원합니다:
  - `Ruff + Mypy + Pytest (Python 3.13)`
  - `Next.js Web (Lint + Typecheck + Test + Build)`
  - `workflow_audit`
  - `security_audit`
- 모드 전환/동기화 절차와 2단계 상향 기준은 `docs/governance/main-branch-protection.md`를 따릅니다.

## 파일/경로

- 로컬 리포트(개발/디버그): `reports/YYYY-MM-DD.buy.json`, `...sell.json`(중복 시 `-1`)
- Storage 오브젝트 키(공식 보관): `YYYY/MM/YYYY-MM-DD.buy.json`, `...sell.json`(중복 시 `-1`, `-2`, ...)
- Storage 업로드 MIME: `contentType=application/json`으로 고정(`reports` 버킷 정책)
- 키 규칙 구현: `sab/report/storage_key.py`의 `build_report_storage_key`
- 캐시/상태: `data/`(KIS 토큰, 캔들, 스크리너 캐시)
- 보유 목록(공식 소스): Supabase Postgres `holdings` 테이블
- 선택 백업 파일: `holdings.yaml`(import/export 용도, v1.2 예정)

## 문제 해결

- 토큰 오류/401: `KIS_APP_KEY/SECRET/BASE_URL` 확인, `data/kis_token_*` 삭제로 강제 갱신(24시간 정책 유의)
- 레이트리밋 `EGW00201`: `KIS_MIN_INTERVAL_MS`(예: 500–1000) 증가 후 재시도. 스크리너 TTL도 호출 수 절감에 도움
- 히스토리 부족: `MIN_HISTORY_BARS=200+` 권장, 누적 수집으로 보완. 신규상장 등은 기준 미달 가능
- US 심볼: `SYMBOL.NAS/NYS/AMS`(또는 동의어 `NASDAQ/NYSE/AMEX`)처럼 거래소를 명시해 사용. `.US`는 입력에서 허용되지 않음. US에는 PyKRX 폴백이 적용되지 않음
- US 클래스 심볼: `BRK.B.NYS`가 캐노니컬이며, `BRK/B.NYS` 입력은 내부에서 `BRK.B.NYS`로 정규화
- KIS 클래스 심볼 호환: 내부 캐노니컬은 dot(`BRK.B`)를 유지하고, KIS 호출에서는 `invalid symbol(msg_cd=SYMB0001)`일 때에만 dot/slash 대체 표기를 1회 시도합니다. 그 외 오류(레이트리밋/토큰/서버)는 즉시 실패하며, 성공 형태는 런타임에 기억합니다.
- US 스크리너: `screener.us_mode=kis`는 자동 폴백 없이 fail-closed. `--universe screener`에서는 즉시 실패, `--universe both`에서는 watchlist는 유지하고 US 스크리너만 건너뜀
- watchlist 로딩: `--universe watchlist|both`에서 watchlist 파일이 없으면 즉시 실패합니다. `--universe screener`에서는 watchlist를 로드하지 않습니다.
- 환율/통화: `FX_MODE=kis`(기본)로 설정하면 KIS 해외 현재가상세에서 `t_rate`를 받아 자동 환율을 적용하고, `FX_CACHE_TTL`분 동안 캐시합니다. 실패 시 `USD_KRW_RATE` 값으로 폴백하거나, 값이 없으면 리포트 Appendix에 경고를 남깁니다.
- 휴장일: 미국 휴일 정보는 KIS `countries-holiday` API를 조회해 `data/holidays_us.json`에 캐시합니다. 파일을 삭제하면 다음 실행 시 자동 갱신됩니다.

## 확장

- RS 벤치마크: 지수 클라이언트를 추가해 시장별 `rs_benchmark_return`을 동적으로 주입
- Entry 체크: 시초/1–15분 데이터를 받아 OK/Wait/Avoid 규칙을 `sab/entry.py`에 구현
