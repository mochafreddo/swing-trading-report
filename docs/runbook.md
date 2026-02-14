# 런북 — CLI + Web 운영 가이드

로컬에서 CLI와 웹 UI를 실행/디버그/운영하기 위한 실무 지침입니다.

## 설치/준비

- uv 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- 의존성 동기화: `UV_CACHE_DIR=.uv-cache uv lock -U && UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- 설정:
  - `config.yaml` 생성(기본값은 `config.example.yaml` 참고)
  - `.env`에는 v1.1 필수 키를 작성:
    - KIS: `KIS_APP_KEY`, `KIS_APP_SECRET`, (선택) `KIS_BASE_URL`
    - Supabase: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`(권장), `SUPABASE_SERVICE_ROLE_KEY`(레거시 폴백)
    - Web: `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT`, (표시용) `REPORT_RETENTION_DAYS`
    - Web 로컬 실행(선택): `WEB_HOST_PORT` (기본값 `55300`)
    - Notify(자동 실행): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  - `config.yaml`과 `.env`에 동일 키를 중복 정의하지 않기(충돌 시 실패)
  - 선택: `uv sync --extra pykrx`로 KR 폴백/프로바이더 활성화
- 런타임:
  - Python 3.13+
  - Node.js 20+
  - Docker Desktop + Docker Compose
- Supabase(권장):
  - 보유 목록/리포트/실행 이력은 Supabase(Postgres/Storage)를 단일 소스로 사용합니다.
  - GitHub Actions 런너가 자동 실행할 때도 동일한 Supabase를 사용합니다.

## 웹 UI 로컬 실행(Next.js + Docker)

- 전환 직후 1회 정리:
  - `docker compose down --remove-orphans && docker compose up -d --build web`
- 일반 재기동:
  - `docker compose up -d --build web`
- 강제 재생성(문제 시):
  - `docker compose stop web`
  - `docker compose rm -f web`
  - `docker compose up -d --build web`
- 로그 확인:
  - `docker compose logs -f web`
- 중지:
  - `docker compose stop web`
- 접속:
  - `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
- 포트 변경:
  - `.env`에 `WEB_HOST_PORT=55444` 설정 후 `docker compose up -d --build web`
- 기본 화면:
  - `Reports`: Storage 리포트 목록/상세/검색
  - `Holdings`: Supabase `holdings` CRUD
  - `Run`: scan/sell `workflow_dispatch` 실행 트리거

## 보유 목록(holdings)

- 보유 목록은 **웹 UI(Next.js)에서 CRUD**로 관리합니다(단일 사용자 기준).
- (선택) `holdings.yaml` import/export로 초기 이관/백업을 지원합니다.

## 자주 쓰는 실행

- Buy 스캔(KR+US 스크리너 + 워치리스트)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe both`
- Buy 스캔(스크리너만, 상위 20)
  - `UV_CACHE_DIR=.uv-cache uv run -m sab scan --universe screener --screener-limit 20`
- 보유 매도/보류 평가
  - `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
- 웹 UI(Next.js)
  - `docker compose up -d --build web`
  - 접속: `http://localhost:${WEB_HOST_PORT}` (기본값 `55300`)
  - 또는 웹 디렉터리에서 직접 실행: `pnpm install && pnpm run dev`

- 자동 실행(GitHub Actions)
  - `schedule`로 scan/sell을 실행하고, 결과를 Supabase에 저장합니다.
  - 알림은 자동 실행일 때만 전송합니다.
- 로컬 CLI 업로드(선택)
  - 기본은 로컬 파일 생성만 수행합니다.
  - 로컬 실행에서도 Supabase 업로드가 필요하면 `SAB_UPLOAD_REPORTS=true`를 설정합니다.

## 파일/경로

- 로컬 리포트(개발/디버그): `reports/YYYY-MM-DD.buy.json`, `...sell.json`(중복 시 `-1`)
- Storage 오브젝트 키(공식 보관): `YYYY/MM/YYYY-MM-DD.buy.json`, `...sell.json`(중복 시 `-1`, `-2`, ...)
- Storage 업로드 MIME: `contentType=application/json`으로 고정(`reports` 버킷 정책)
- 키 규칙 구현: `sab/report/storage_key.py`의 `build_report_storage_key`
- 캐시/상태: `data/`(KIS 토큰, 캔들, 스크리너 캐시)
- 보유 목록(공식 소스): Supabase Postgres `holdings` 테이블
- 선택 백업 파일: `holdings.yaml`(import/export 용도)

## 문제 해결

- 토큰 오류/401: `KIS_APP_KEY/SECRET/BASE_URL` 확인, `data/kis_token_*` 삭제로 강제 갱신(24시간 정책 유의)
- 레이트리밋 `EGW00201`: `KIS_MIN_INTERVAL_MS`(예: 500–1000) 증가 후 재시도. 스크리너 TTL도 호출 수 절감에 도움
- 히스토리 부족: `MIN_HISTORY_BARS=200+` 권장, 누적 수집으로 보완. 신규상장 등은 기준 미달 가능
- US 심볼: `SYMBOL.US` 또는 `SYMBOL.NASD/NYSE/AMEX` 사용. US에는 PyKRX 폴백이 적용되지 않음
- US 스크리너: `screener.us_mode=kis`로 KIS 랭크 사용. 실패 시 `screener.us_defaults`로 자동 폴백
- 환율/통화: `FX_MODE=kis`(기본)로 설정하면 KIS 해외 현재가상세에서 `t_rate`를 받아 자동 환율을 적용하고, `FX_CACHE_TTL`분 동안 캐시합니다. 실패 시 `USD_KRW_RATE` 값으로 폴백하거나, 값이 없으면 리포트 Appendix에 경고를 남깁니다.
- 휴장일: 미국 휴일 정보는 KIS `countries-holiday` API를 조회해 `data/holidays_us.json`에 캐시합니다. 파일을 삭제하면 다음 실행 시 자동 갱신됩니다.

## 확장

- RS 벤치마크: 지수 클라이언트를 추가해 시장별 `rs_benchmark_return`을 동적으로 주입
- Entry 체크: 시초/1–15분 데이터를 받아 OK/Wait/Avoid 규칙을 `sab/entry.py`에 구현
