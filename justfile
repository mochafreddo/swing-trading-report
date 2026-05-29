set shell := ["bash", "-euo", "pipefail", "-c"]
set positional-arguments

export UV_CACHE_DIR := ".uv-cache"
export PRE_COMMIT_HOME := ".pre-commit-cache"

ci_sab_basic_auth_user := "ci-user"
ci_sab_basic_auth_pass := "ci-pass"
ci_sab_session_secret := "ci_session_secret_0123456789abcdef"
ci_supabase_url := "https://example.supabase.co"
ci_supabase_secret_key := "sb_secret_ci"
ci_github_owner := "ci-owner"
ci_github_repo := "ci-repo"
ci_github_pat := "ghp_ci_token"

alias qa := quality
alias pc := precommit
alias pca := precommit-all
alias pp := prepush

default:
  @just --list

# Dependency and lockfile operations
sync *args:
  uv sync --all-extras --all-groups {{args}}

lock:
  uv lock

lock-upgrade:
  uv lock --upgrade

# Trading workflows
scan *args:
  uv run python -m sab scan {{args}}

sell *args:
  uv run python -m sab sell {{args}}

entry *args:
  uv run python -m sab entry {{args}}

ai-brief-scheduled-local *args:
  uv run python -m sab ai-brief-scheduled {{args}}

ai-brief-scheduled-docker *args:
  docker compose -f docker-compose.yml -f docker-compose.scheduler.yml run --rm scheduler uv run python -m sab ai-brief-scheduled {{args}}

ai-brief-source-eval *args:
  uv run python scripts/eval_ai_brief_sources.py {{args}}

ai-brief-eval *args:
  uv run python scripts/eval_ai_brief_recommendations.py {{args}}

ai-brief-source-collect *args:
  uv run python scripts/collect_ai_brief_sources.py {{args}}

ai-brief-source-live-compare *args:
  uv run python scripts/compare_ai_brief_live_sources.py {{args}}

# Python quality gates
ruff:
  uv run ruff check .

format-check:
  uv run ruff format --check .

format:
  uv run ruff format .

mypy:
  uv run mypy --config-file pyproject.toml

test *args:
  uv run python -m pytest -q {{args}}

deadcode-python:
  uv run python scripts/run_vulture.py

quality: ruff format-check mypy test

check: quality

# Pre-commit
precommit *args:
  uv run pre-commit run {{args}}

precommit-all:
  uv run pre-commit run --all-files

precommit-validate:
  uv run pre-commit validate-config

prepush: quality

# Web quality gates
web-clean:
  rm -rf web/coverage

web-install:
  CI=true pnpm --dir web install --frozen-lockfile

web-lint:
  pnpm --dir web run lint

web-format-check:
  pnpm --dir web run format:check

web-typecheck:
  pnpm --dir web run typecheck

web-test:
  pnpm --dir web run test:coverage

deadcode-web:
  pnpm --dir web run deadcode

deadcode: deadcode-python deadcode-web

web-build:
  @SAB_BASIC_AUTH_USER='{{ci_sab_basic_auth_user}}' SAB_BASIC_AUTH_PASS='{{ci_sab_basic_auth_pass}}' SAB_SESSION_SECRET='{{ci_sab_session_secret}}' SUPABASE_URL='{{ci_supabase_url}}' SUPABASE_SECRET_KEY='{{ci_supabase_secret_key}}' GITHUB_OWNER='{{ci_github_owner}}' GITHUB_REPO='{{ci_github_repo}}' GITHUB_PAT='{{ci_github_pat}}' pnpm --dir web run build

ci-python: quality

ci-web: web-clean web-install web-lint web-format-check web-typecheck web-test web-build
  rm -rf web/coverage
