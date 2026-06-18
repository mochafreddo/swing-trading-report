# Local Development

상태: Accepted (로컬 개발 가이드)

이 문서는 신규 개발자가 저장소를 받아 로컬에서 Python CLI, Next.js 웹 UI, 테스트/품질 게이트를 실행하는 절차를 정리합니다.

## 문서 상태

### 현재 제공

- `mise`, `uv`, `pnpm`, `just`, Docker Compose 기반 로컬 개발 절차를 제공합니다.
- 외부 credential이 필요한 live 실행은 요구사항과 확인 명령만 제공합니다.

### 실험

- 별도 experimental setup은 운영하지 않습니다.

### 백로그

- 로컬 Supabase full bootstrap 절차는 현재 runbook 수준 SQL 확인 중심입니다. 완전한 first-run wizard는 없습니다.

### 폐기 후보

- `uv init`처럼 이미 초기화된 저장소에 맞지 않는 bootstrap 절차는 사용하지 않습니다.

## 요구사항

| Tool | Required | Source |
| --- | --- | --- |
| Python 3.14 | yes | `pyproject.toml`, `mise.toml` |
| uv | yes | `justfile`, `pyproject.toml` |
| Node.js 24.16.0 | web only | `mise.toml`, `web/Dockerfile` |
| pnpm 11.1.2 | web only | `mise.toml`, `web/package.json` |
| Docker Desktop | web/scheduler compose | `docker-compose.yml`, `docker-compose.scheduler.yml` |
| just | recommended | `justfile` |
| direnv | optional | `.envrc`, `.envrc.local.example` |

## 1. Toolchain 동기화

```bash
mise install
just --list
```

`mise install`은 `mise.toml`/`mise.lock` 기준으로 Python, uv, Node.js, pnpm, just, direnv 버전을 맞춥니다.

## 2. Python 의존성 설치

```bash
UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups
```

기본 실행만 필요하면 `UV_CACHE_DIR=.uv-cache uv sync`도 가능하지만, 개발자는 테스트와 optional provider 검증을 위해 `--all-extras --all-groups`를 권장합니다.

## 3. 환경변수 준비

```bash
cp .env.example .env
```

`.env`에는 실제 값을 넣되 커밋하지 않습니다. 값은 출력하거나 문서화하지 마세요. 주요 요구사항은 [Configuration](configuration.md)을 따릅니다.

최소 CLI KIS 실행:

```env
KIS_APP_KEY=replace-with-kis-app-key
KIS_APP_SECRET=replace-with-kis-app-secret
```

웹 UI 실행에는 Supabase와 관리자 로그인 값이 추가로 필요합니다.

```env
SUPABASE_URL=https://example.supabase.co
SUPABASE_SECRET_KEY=replace-with-server-side-key
SAB_BASIC_AUTH_USER=admin
SAB_BASIC_AUTH_PASS=replace-with-password
SAB_SESSION_SECRET=replace-with-32-plus-char-random-string
```

## 4. Python CLI 실행

```bash
just scan --universe both
just sell
just entry
```

직접 실행:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m sab scan --universe both
UV_CACHE_DIR=.uv-cache uv run python -m sab sell
UV_CACHE_DIR=.uv-cache uv run python -m sab entry
UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief --entry-report reports/YYYY-MM-DD.entry.json
```

`scan`/`sell`/`entry`는 KIS/Supabase/시장 데이터 상태에 따라 실패할 수 있습니다. 실패 시 [Troubleshooting](troubleshooting.md)을 먼저 확인합니다.

## 5. Web UI 실행

Docker Compose production mode:

```bash
docker compose up -d --build web
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/favicon.ico
```

기대값: 두 요청 모두 `200`

Docker Compose development mode:

```bash
docker compose --profile dev up -d --build web-dev
```

Host 직접 실행:

```bash
pnpm --dir web install --frozen-lockfile
pnpm --dir web run dev
```

직접 실행의 기본 bind host는 `127.0.0.1`입니다. non-loopback bind는 `SAB_ALLOW_NON_LOOPBACK_BIND=1` 없이는 시작 단계에서 거부됩니다.

## 6. 테스트와 품질 게이트

Python-only 변경:

```bash
just quality
```

Web 변경:

```bash
just ci-web
```

문서 구조 변경:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q
```

Fallback 직접 실행:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run ruff format --check .
UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q
pnpm --dir web run lint
pnpm --dir web run format:check
pnpm --dir web run typecheck
pnpm --dir web run test:coverage
pnpm --dir web run build
```

## 7. Web UI smoke / QA

웹 UI, 인증, 라우팅, API guard, 또는 웹에서 소비하는 리포트/API 계약을 바꾸면 `sab-web` 컨테이너에서 브라우저 smoke를 남깁니다.

```bash
docker compose up -d --build web
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login
```

기본 unauthenticated smoke 범위:

- `/`가 `/login?next=%2F`로 redirect되는지 확인합니다.
- `/reports`, `/holdings`, `/run` 같은 보호 페이지가 `/login?next=...`로 redirect되는지 확인합니다.
- 로그인 폼의 빈 제출(required validation)과 잘못된 자격 증명(`Unauthorized`) 상태를 확인합니다.
- desktop과 mobile viewport에서 텍스트/폼/alert가 겹치지 않는지 확인합니다.
- `/favicon.ico`가 `200`을 반환해 기본 browser console이 clean한지 확인합니다.
- browser console error가 없는지 확인합니다.

로컬 QA 리포트, baseline, 스크린샷은 `.gstack/qa-reports/`에 저장합니다. 이 디렉터리는 검증 증거용 로컬 산출물이므로 git에 커밋하지 않습니다.

## 8. 자주 발생하는 로컬 문제

| Symptom | First check |
| --- | --- |
| `pnpm` not found | `mise install`, then `mise exec -- just ci-web` |
| Web env validation fails | `SAB_BASIC_AUTH_*`, `SAB_SESSION_SECRET`, `SUPABASE_URL`, server-side Supabase key |
| `/api/run` returns env error | `RUN_DISPATCH_ENABLED=1`이면 `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT` 필요 |
| KIS token/auth failure | `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_BASE_URL`, `data/kis_token_*` cache |
| `pykrx` scan fails | `provider=pykrx`는 KR watchlist/AFTER_CLOSE 중심으로 사용 |

## NOT_RUN

- 실제 KIS live scan, Supabase remote migration, Telegram/Slack 발송은 이 문서 작성 중 실행하지 않았습니다.
