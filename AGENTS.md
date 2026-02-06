# AGENTS.md

## commands

- `UV_CACHE_DIR=.uv-cache uv run -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv lock -U`
- `UV_CACHE_DIR=.uv-cache uv sync --all-groups`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy sab`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`

## pre-commit (sandbox)

- Full run: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- Single hook: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- Hook updates: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- Config check: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- First run may require network access to fetch hook repositories.

## commits

- Use Conventional Commits.
- Commit by meaningful units of change.
- One intention per commit.
- Split commits when concerns are mixed.
- Avoid vague commit messages.
