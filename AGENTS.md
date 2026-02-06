# AGENTS.md

## 명령어

- `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv lock -U`
- `UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy sab`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

## pre-commit (샌드박스)

- 전체 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- 단일 훅 실행: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- 훅 업데이트: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- 설정 검사: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- 첫 실행 시 훅 저장소를 내려받기 위해 네트워크 접근이 필요할 수 있습니다.

## 커밋

- Conventional Commits 형식을 사용합니다.
- 의미 단위로 커밋합니다.
- 하나의 커밋에는 하나의 의도만 담습니다.
- 서로 다른 관심사가 섞여 있으면 커밋을 분리합니다.
- 모호한 커밋 메시지는 피합니다.
- 커밋 메시지의 제목과 본문은 한글로 작성합니다.
- 커밋 메시지 기본 형식:
  - 제목 1줄 (`type(scope): 요약`)
  - 빈 줄 1줄
  - 본문(필요한 경우에만) 문단/불릿으로 작성
- 본문 작성 규칙:
  - 문장마다 줄을 띄우지 않고 문단 단위로 작성합니다.
  - CLI에서 `-m`를 문장별로 여러 번 쓰지 않습니다.
  - 권장: `-m "제목"` + `-m "본문 전체"` 형태로 작성합니다.
- `git status`, `git add`, `git commit` 같은 git 명령은 `/bin/zsh -lc` 같은 셸 래퍼 없이 직접 실행합니다.
- `git push`는 권한 상승(`sandbox_permissions=\"require_escalated\"`)으로 실행합니다.
