# AGENTS.md

## 실행 우선순위

- 도구체인 동기화: `mise install`
- 도구 버전 변경 시 lock 갱신: `mise lock --platform linux-x64,macos-arm64 && mise install`
- direnv zsh 훅(1회): `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc`
- direnv 프로젝트 허용(최초 1회): `direnv allow .`
- direnv는 `.env`를 자동 로드하지 않습니다(`.envrc.local`만 로드).
- 시크릿/개인 오버라이드는 `.envrc.local`에만 저장하고 커밋하지 않습니다.

## 권장 명령 (just)

- 레시피 목록: `just --list`
- 의존성/락: `just sync`, `just lock-upgrade`
- 트레이딩 실행: `just scan`, `just sell`, `just entry`
- 품질 게이트: `just quality` (`just check`는 동일 동작 alias)
- pre-commit: `just precommit-all`
- CI 대응 실행: `just ci-python`, `just ci-web` (`ci-web`는 비밀 없는 고정 CI placeholder env로만 실행)

## 직접 실행 (uv fallback)

- `UV_CACHE_DIR=.uv-cache uv sync --all-extras --dev`
- `UV_CACHE_DIR=.uv-cache uv lock --upgrade`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

## TDD (Red/Green/Refactor)

- 기능 추가/버그 수정은 기본적으로 Red/Green/Refactor 사이클을 따릅니다.
- Red: 먼저 실패하는 테스트를 작성하고, 실패를 확인한 뒤 구현을 시작합니다.
- Green: 테스트를 통과시키는 최소한의 코드만 작성합니다.
- Refactor: 테스트가 통과한 상태에서만 중복 제거와 구조 개선을 수행합니다.
- 버그 수정 시 재현 테스트(회귀 테스트) 없이 코드부터 수정하지 않습니다.
- 사이클 완료 전 품질 게이트를 모두 통과합니다.
- 권장: `just quality`
- fallback: `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`, `UV_CACHE_DIR=.uv-cache uv run ruff check .`, `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`

## 문서(설계 로직)

- 설계 로직(신호/리스크/평가 기준/모드별 규칙)이 변경될 경우 [STRATEGY.md](docs/STRATEGY.md) 를 함께 업데이트합니다.
- 로직/플로우/컴포넌트 책임이 변경될 경우 [ARCHITECTURE.md](docs/ARCHITECTURE.md) 업데이트 필요 여부를 함께 검토합니다.

## Pre-commit (샌드박스)

- 권장: `just precommit-all`
- 단일 훅 실행(권장): `just precommit mypy --all-files`
- 설정 검사(권장): `just precommit-validate`
- 전체 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- 단일 훅 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- 훅 업데이트: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- 설정 검사: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- 첫 실행 시 훅 저장소를 내려받기 위해 네트워크 접근이 필요할 수 있습니다.
- 커밋 시 staged 파일에 `web/` 변경이 있으면 `pnpm --dir web run lint`와 `pnpm --dir web run format:check`를 검사합니다.
- `web` 타입체크는 pre-commit에서 제외하고 CI(`.github/workflows/ci.yml`의 web job)에서 `pnpm run typecheck`로 강제합니다.

## 웹 스모크 체크

- 우선순위: 샌드박스에서 `next dev` 포트 바인딩이 `EPERM`으로 막힐 수 있으므로, `sab-web` 컨테이너가 실행 중이면 `http://127.0.0.1:${WEB_HOST_PORT}`로 먼저 검증합니다.
- `/run` 성공 조건: `GITHUB_OWNER`, `GITHUB_REPO`, `GITHUB_PAT`가 비어 있으면 `/api/run`이 500(Zod validation)으로 실패합니다.
- 브라우저 자동화 폴백: Playwright Chrome 런치가 세션 충돌로 실패할 수 있으므로, 이런 경우 `chrome-devtools` 기반 체크로 전환합니다.

## GitHub Actions 린트 팁

- `workflow_audit`의 `actionlint`는 `shellcheck` 스타일 경고(`SC2129`)도 실패로 처리될 수 있습니다.
- GitHub Actions `run: |`에서 heredoc(`cat <<'EOF'`) 사용 시 종료 토큰(`EOF`)은 줄 맨 앞(무들여쓰기)이어야 합니다. 들여쓰기가 들어가면 `SC1039`, `SC1072`, `SC1073`로 실패할 수 있습니다.
- 단순 문자열 파일 생성은 heredoc 대신 `printf`를 우선 사용합니다.
- 워크플로 문법/쉘 린트는 로컬에서 다음 명령으로 재현합니다: `docker run --rm -v "$PWD":/work -w /work rhysd/actionlint:latest`
- 로컬에서 `python` 실행이 불안정할 수 있으므로, 저장소 작업 스크립트는 `uv run python ...`을 우선 사용합니다.

## Context7 MCP

- 라이브러리/API 문서, 코드 생성, 설정/구성 단계가 필요할 때 사용자가 명시적으로 요청하지 않아도 항상 Context7 MCP를 사용합니다.
- `resolve-library-id`로 라이브러리 ID를 먼저 조회한 뒤 `query-docs`로 최신 문서를 가져옵니다.

## 커밋

- Conventional Commits 형식을 사용합니다.
- 의미 단위로 커밋합니다.
- 하나의 커밋에는 하나의 의도만 담습니다.
- 서로 다른 관심사가 섞여 있으면 커밋을 분리합니다.
- 모호한 커밋 메시지는 피합니다.
- 커밋 메시지의 제목과 본문은 한글로 작성합니다.
- 커밋 메시지 기본 형식은 제목 1줄(`type(scope): 요약`) + 빈 줄 1줄 + 본문(필요한 경우)입니다.
- 본문은 문장마다 줄을 띄우지 않고 문단 단위로 작성합니다.
- CLI에서 `-m`를 문장별로 여러 번 쓰지 않습니다.
- 권장 형식: `git commit -m "제목" -m "본문 전체"`
- 본문 줄바꿈이 필요하면 `"\n"`을 더블쿼트 안에 넣지 않습니다(문자 그대로 `\n`이 저장될 수 있음).
- 줄바꿈 권장 방식: zsh의 `$'...'` 인용 사용. 예: `git commit -m "chore(ci): ..." -m $'- 항목1\n- 항목2'`
- 줄바꿈 대안: `git commit`으로 편집기를 열어 작성합니다.
- 이미 푸시한 커밋 메시지를 고칠 때는 `git rebase -i`로 `reword` 후 `git push --force-with-lease`를 사용합니다(브랜치 정책/협업 상황 확인).
- `git status`, `git add`, `git commit` 같은 git 명령은 `/bin/zsh -lc` 같은 셸 래퍼 없이 직접 실행합니다.
- `git push`는 권한 상승(`sandbox_permissions="require_escalated"`)으로 실행합니다.
