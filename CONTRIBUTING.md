# Contributing

This root guide is intentionally short. Use [docs/contributing.md](docs/contributing.md) as the source of truth for setup, validation, commit, PR, documentation, and security rules.

## Quick Start

```bash
mise install
UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups
cp .env.example .env
```

## Main Gates

```bash
just quality
just ci-web
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q
```

Do not commit secrets, `.env*`, `.envrc.local`, `holdings.yaml`, `data/`, or `reports/`. Mark skipped validation as `NOT_RUN` and unverifiable operational policy as `NEEDS_CONFIRMATION`.
