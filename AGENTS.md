# AGENTS.md

문제를 완전히 해결하는 가장 작은 안전한 변경을 한다.
기본 루프: **이해 -> 범위 설정 -> 변경 -> 테스트 -> 검토 -> 필요 시 리팩터링**.

## 프로젝트 개요

`swing-trading-report`: KR/US 시장용 온디맨드 스윙 트레이딩 시그널 스캐너 및 리포트 생성기. Python `sab` 패키지가 스캔을 실행해 JSON 리포트를 쓰고, 로컬 Next.js UI가 이를 열람하며, Supabase가 보유목록/리포트/실행이력을 저장하고, GitHub Actions가 스케줄 스캔 + 텔레그램/슬랙 알림을 수행. 툴체인 버전은 `mise.toml`에 고정(Python 3.14, uv, node, pnpm, just, direnv).

```
sab/         # Python 패키지; 엔트리포인트 `python -m sab`
             #   scan/sell/entry/backtest/ai-brief/sell-ai-brief/scheduled/probe 서브커맨드
             #   signals/ screener/ report/ data/ scheduler/ utils/ + scan/sell/entry/backtest/ai_brief 모듈
web/         # 로컬 UI: Next.js 16 + React 19 + TypeScript (`docker compose up -d --build web`로 기동)
tests/       # pytest 스위트 (~83개 테스트 파일)
scripts/     # 유지보수/평가 스크립트 (`uv run python scripts/...`로 실행)
docs/        # STRATEGY.md(전략 로직), ARCHITECTURE.md(컴포넌트 흐름), PRD.md, runbook.md, adr/
reports/     # 생성 산출물: YYYY-MM-DD(-n).{buy|sell|entry|backtest|ai-brief|ai-brief-skip|sell-ai-brief}.json
config.yaml, holdings.yaml   # 런타임 설정(config.yaml은 저장소에 기본값 포함) + 보유목록(holdings.yaml은 gitignore, holdings.example.yaml에서 복사)
```

이 파일은 `AGENTS.md`이며 `CLAUDE.md`는 이를 가리키는 심링크(다른 에이전트와 공유). `AGENTS.md`를 제자리에서 편집할 것. 새 파일로 교체하면 심링크가 깨짐.

공유 에이전트 참고: Codex 또는 특정 샌드박스에 의존하는 도구별 규칙은 그렇게 표시한다. 다른 에이전트는 정확히 같은 도구나 권한 모델이 있다고 가정하지 말고, 의도를 보존하면서 가장 가까운 안전한 대안을 사용한다.

로컬 전용 참고: `AGENTS.local.md`가 있으면 이 파일을 읽은 뒤 추가로 읽는다. 이 파일은 gitignore 대상이며 인증 정보 위치, 포트, 샌드박스 우회 같은 machine-local gotcha만 기록한다. 비밀값 자체는 어떤 문서에도 기록하지 않는다.

지침 예산: 이 파일은 초점을 유지하고 Codex의 기본 프로젝트 지침 예산을 넉넉히 밑돌게 관리한다. 특정 하위 트리에만 필요한 디렉터리별 규칙은 중첩된 `AGENTS.md` 파일로 옮긴다.

## 규칙 우선순위

더 높은 우선순위의 시스템, 개발자, 사용자 지침을 먼저 따른다. 이 파일 안에서 규칙이 충돌하면 다음 순서를 따른다.

1. **안전, 보안, 개인정보, 권한**
2. **정확성**
3. **저장소 관례**
4. **명확성**
5. **단순성**

안전, 정직성, 개인정보, 권한 제약은 양보하지 않는다. 그렇게 하는 편이 안전성, 정확성, 보안, 유지보수성을 약화하지 않는 한, 일반 스타일 규칙보다 저장소의 기존 아키텍처, 명명, 오류 처리, 테스트 패턴을 우선한다.

## 작업 원칙

- 필요한 만큼 관련 파일, 호출 경로, 설정, 테스트를 확인한 뒤 변경한다.
- 요청이 명시적으로 다르게 말하지 않는 한 기존 공개 동작을 보존한다.
- 작업, 커밋, PR은 작고 집중된 상태로 유지하고, 관련 없는 리팩터링, 이름 변경, 의존성 업그레이드, 포맷 전용 변경을 섞지 않는다.
- 저장소의 기존 아키텍처, 명명, 오류 처리, 테스트 패턴을 우선한다. 새 추상화는 실제 복잡도나 반복을 줄일 때만 추가한다.
- 오류는 구체적으로 처리하고, 로그/테스트/문서/스크린샷에 비밀이나 민감정보를 남기지 않는다.
- 입력, 파일 접근, 인증/인가, 토큰/비밀, 리디렉션, 역직렬화, 외부 시스템 경계는 특히 보수적으로 검토한다.
- 시간대, 시장 개장/폐장, 동시성, 재시도, 멱등성, 관측성은 변경과 관련 있을 때 확인한다.
- 동작, API, 스키마, 설정, UX, 전략 로직이 바뀌면 관련 테스트와 문서를 함께 업데이트한다.
- 검증은 변경 위험과 영향 범위에 맞춘다. 전체 게이트를 건너뛰거나 실행할 수 없으면 이유와 다음으로 좋은 검사를 기록한다.

## 저장소별 규칙

### 실행 우선순위

- 툴체인 동기화: 고정된 도구가 없거나 오래되었을 때, `mise.toml` 변경 후, 또는 고정 도구를 사용할 수 없어 명령이 실패했을 때만 `mise install`을 실행한다.
- `pnpm`이 `PATH`에 없어 `just ...`가 실패하면 mise를 통해 다시 실행한다. 예: `mise exec -- just ...` 또는 `mise exec -- just ci-web`.
- 도구 버전이 바뀌면 lockfile을 갱신한다: `mise lock --platform linux-x64,macos-arm64 && mise install`
- `direnv allow .`는 로컬 신뢰 결정이므로 자동화 에이전트가 임의로 실행하지 않는다. 필요하면 사용자 승인을 받고 한 번만 실행한다.
- direnv는 `.env`를 자동 로드하지 않고 `.envrc.local`만 로드한다.
- 비밀과 private override는 `.envrc.local`에만 저장하고 커밋하지 않는다.

### 권장 명령 (just)

- 레시피 목록: `just --list`
- 의존성/lock 파일: `just sync`, `just lock-upgrade`
- 의존성 audit: `just audit` (소스별 검사는 `just audit-python-osv`, `just audit-web-prod`)
- 트레이딩 워크플로: `just scan`, `just sell`, `just entry`
- AI Brief 워크플로: `just ai-brief-source-collect`, `just ai-brief-source-eval`, `just ai-brief-source-live-compare`, `just ai-brief-eval`
- 품질 게이트: `just quality`(`just check`와 같은 alias), `just ci-web`, `just ci-python`
- 미사용 코드 검사: `just deadcode`
- pre-commit: `just precommit-all`
- CI 동등성: `just ci-python`, `just ci-web` (`ci-web`는 비밀 없는 고정 CI placeholder env로만 실행)

### 검증 빠른 참조

- Python 전용 변경: `just quality`를 우선하고, 대체 검증은 대상 pytest + `just ruff` + `just mypy`.
- Web 전용 변경: `just ci-web`을 우선하고, 대체 검증은 영향받은 `just web-*` 검사.
- Python + web 변경: 관련 게이트를 모두 실행하거나 더 좁은 검증을 택한 이유를 설명한다.
- 문서/정적 전용 변경: 포맷, 문법, 링크, 스키마, 공백 문제를 잡는 가장 저렴한 검사를 실행한다.
- 개별 검사: `just mypy`, `just web-typecheck`, `just ruff`, `just format-check`, `just web-lint`, `just web-format-check`, `just test`, `just web-test`, `just deadcode-python`, `just deadcode-web`, `shellcheck scripts/upgrade_deps.sh`.

### 직접 실행 (uv 대체 경로)

- `UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups`
- `UV_CACHE_DIR=.uv-cache uv lock --upgrade`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab entry`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab backtest --data-file data/history.json --tickers AAPL.NAS`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief --entry-report <path>`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief-latency-probe --primary-model <model>`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`
- `UV_CACHE_DIR=.uv-cache uv run python scripts/run_vulture.py`
- `UV_CACHE_DIR=.uv-cache uv export --quiet --locked --all-extras --all-groups --no-emit-project --output-file /tmp/swing-trading-report-pip-audit-requirements.txt`
- `pip-audit --disable-pip -r /tmp/swing-trading-report-pip-audit-requirements.txt`
- `pnpm --dir web audit --audit-level low`
- `pnpm --dir web run deadcode`

### 의존성 audit 주의사항

- Python + web 의존성 audit에는 `just audit`를 선호한다.
- `pip-audit --locked .`는 현재 이 프로젝트의 `uv.lock`을 읽지 못한다. 먼저 `uv.lock`에서 export한 뒤 생성된 requirements 파일을 audit한다.
- hash를 포함하는 `uv export`와 `pip-audit --disable-pip`를 함께 사용한다. 일반 `pip-audit -r ...`는 임시 venv를 만들 수 있고 샌드박스된 `ensurepip`에서 실패할 수 있다.
- pnpm 보안 override는 `web/package.json`이 아니라 `web/pnpm-workspace.yaml`에 둔다. 이는 `web/scripts/dependency-overrides.test.mjs`가 강제한다.
- `pnpm why`가 pnpm store SQLite 권한 오류로 실패하면 의존성 경로를 확인하기 위해 `web/pnpm-lock.yaml`을 직접 살펴본다.

### 문서화 (전략 로직)

- 신호, 위험, 평가 기준, 모드별 규칙을 포함해 전략 로직이 바뀌면 [STRATEGY.md](docs/STRATEGY.md)를 함께 업데이트한다.
- 로직, 흐름, 컴포넌트 책임이 바뀌면 [ARCHITECTURE.md](docs/ARCHITECTURE.md)도 업데이트해야 하는지 평가한다.

### 릴리스 자동화

- 기능 PR이 반영된 뒤 `.release-please-manifest.json`, `CHANGELOG.md`, `pyproject.toml`, `web/package.json`의 릴리스 버전 올림은 Release Please가 소유한다.
- 기능 PR에서 Release Please 소유 파일을 미리 버전 올림하지 않는다. 릴리스를 수동으로 복구한 경우 Release Please를 다시 실행하기 전에 manifest 버전에 맞는 GitHub release/tag를 만든다.
- Release Please가 `pyproject.toml`을 업데이트하면 릴리스 PR을 병합하기 전에 `UV_CACHE_DIR=.uv-cache uv lock`으로 `uv.lock`을 갱신한다.

### Pre-commit (샌드박스)

- 권장: `just precommit-all`
- 단일 hook 권장: `just precommit mypy --all-files`
- 설정 검증 권장: `just precommit-validate`
- 전체 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- 단일 hook 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- hook 업데이트: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- 설정 검증: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- 첫 실행은 hook 저장소를 다운로드하기 위해 네트워크 접근이 필요할 수 있다.
- staged 상태의 `web/` 변경을 커밋할 때는 `pnpm --dir web run lint`와 `pnpm --dir web run format:check`를 확인한다. staged 변경에 `web/src/app/`이 포함되면 `web-route-static-check` hook도 확인한다(`uv run python scripts/check_next_app_routes.py`).
- web typecheck는 pre-commit에서 제외되어 있고, `.github/workflows/ci.yml`의 `web` job에서 `pnpm run typecheck`로 CI에서 강제된다.

### Web 스모크 체크

- 우선순위: 샌드박스에서는 `next dev` 포트 바인딩이 `EPERM`으로 실패할 수 있으므로, `sab-web` 컨테이너가 실행 중이면 먼저 확인한다. `WEB_HOST_PORT`가 설정되어 있으면 `http://127.0.0.1:${WEB_HOST_PORT}`, 설정되어 있지 않으면 기본값 `http://127.0.0.1:55300`을 사용한다.
- `/run` 성공 조건: `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT` 중 하나가 비어 있으면 `/api/run`은 Zod validation으로 500을 반환한다.
- 브라우저 자동화 대체 경로: Playwright Chrome 실행은 세션 충돌로 실패할 수 있다. 이때는 `chrome-devtools` 기반 검사로 전환한다.

### GitHub Actions lint 팁

- `workflow_audit`의 `actionlint`는 `SC2129` 같은 `shellcheck` 스타일 경고로 실패할 수 있다.
- GitHub Actions `run: |` 블록에서 `cat <<'EOF'` 같은 heredoc을 사용할 때 closing token(`EOF`)은 줄 맨 앞에서 시작해야 한다. 들여쓰기는 `SC1039`, `SC1072`, `SC1073` 실패를 일으킬 수 있다.
- 단순 문자열 파일 생성에는 heredoc보다 `printf`를 선호한다.
- 로컬 `python` 실행은 불안정할 수 있으므로 저장소 작업 스크립트는 `uv run python ...`을 선호해야 한다.
- workflow 문법과 shell lint는 로컬에서 다음으로 재현한다: `docker run --rm -v "$PWD":/work -w /work rhysd/actionlint:latest`

### 최신 문서

- 현재 또는 버전별 외부 동작이 중요하면 기억 대신 권위 있는 최신 문서를 사용한다.
- 서드파티 요약보다 공식 문서나 저장소 로컬 문서가 더 적절하면 이를 선호한다.
- Codex: OpenAI가 아닌 library/API 문서, 코드 생성, setup/configuration 단계에는 Context7 MCP가 사용 가능하고 적합할 때 확인을 선호한다.
- Codex: Context7을 사용할 때는 먼저 `resolve-library-id`로 library ID를 resolve한 뒤 `query-docs`로 최신 문서를 가져온다.

### 커밋

- Conventional Commits를 사용하고 커밋 하나에는 하나의 의도만 담는다.
- 관련 없는 관심사가 섞이면 커밋을 나누고, 모호한 커밋 메시지는 피한다.
- 커밋 메시지 제목과 본문은 한국어로 작성한다.
- 기본 형식은 제목 한 줄(`type(scope): summary`), 빈 줄 하나, 필요할 때 본문이다. 본문을 문장마다 나누지 말고 문단으로 작성한다.
- CLI에서 문장마다 `-m`을 한 번씩 넘기지 않는다. 권장 형식은 `git commit -m "title" -m "entire body"`이다.
- 본문에 줄바꿈이 필요하면 큰따옴표 안에 `"\n"`을 넣지 않는다. zsh `$'...'` quoting이나 editor를 사용한다. 예: `git commit -m "chore(ci): ..." -m $'- item 1\n- item 2'`
- push된 커밋 메시지 수정이나 push된 이력 재작성은 사람이 주도하는 작업이다. 먼저 branch policy와 협업 맥락을 확인한다. 자동화 에이전트는 비대화형 git 방법을 선호하고, 사용자가 요청할 때만 force-push 명령을 사용한다.
- `git status`, `git add`, `git commit` 같은 git 명령은 `/bin/zsh -lc` 같은 shell wrapper 없이 직접 실행한다.
- Codex: `git push`는 상승 권한으로 실행한다(`sandbox_permissions="require_escalated"`).

## 배포 설정 (/setup-deploy로 구성됨)

- 플랫폼: custom/local Docker + GitHub Actions
- 프로덕션 URL: `http://127.0.0.1:55300`
- 배포 workflow: 로컬 Docker 수동 배포, GitHub Actions workflow 파일은 `main`으로 병합해 배포
- 배포 상태 명령: `docker compose ps`
- 병합 방식: merge
- 프로젝트 유형: 로컬 web app + Python CLI 자동화
- 배포 후 상태 확인: `http://127.0.0.1:55300/login`

### 사용자 정의 배포 hook

- 병합 전: `just quality`와 `just ci-web`
- 배포 트리거: `docker compose up -d --build web`
- 배포 상태: `docker compose ps`
- 상태 확인: `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login`
