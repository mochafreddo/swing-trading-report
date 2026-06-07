# Contributing

상태: Accepted (기여 가이드)

이 문서는 신규 개발자와 인수인계자가 변경을 준비, 검증, 리뷰, 문서화하는 기준입니다. 에이전트 작업 지침은 [AGENTS.md](../AGENTS.md)를 따르고, 사람/팀 기여자는 이 문서를 기준으로 합니다.

## 문서 상태

### 현재 제공

- 로컬 설정, 검증 명령, 브랜치/커밋/PR 기준, 보안/문서 변경 기준을 제공합니다.

### 실험

- 외부 기여자용 issue template/PR template 자동화는 별도 구성하지 않았습니다.

### 백로그

- 변경 유형별 PR 템플릿과 release checklist.
- 운영 승인자/코드오너 문서화.

### 폐기 후보

- root `CONTRIBUTING.md`에 긴 절차를 중복 유지하는 방식은 줄이고, 상세 기준은 이 파일로 모읍니다.

## Local Setup

```bash
mise install
UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups
cp .env.example .env
```

Do not commit `.env`, `.env.*`, `.envrc.local`, `holdings.yaml`, `data/`, or `reports/`.

## Development Loop

1. Read the affected code, tests, config, and docs before editing.
2. Keep the change focused.
3. Update docs when behavior, config, API, report schema, deployment, or operational procedure changes.
4. Run the smallest relevant verification first, then broader gates for risky changes.
5. Review the diff for secrets and unrelated churn.

## Quality Gates

| Change Type | Preferred Command | Notes |
| --- | --- | --- |
| Python only | `just quality` | Ruff, format check, mypy, pytest. |
| Web only | `just ci-web` | install/lint/format/typecheck/test:coverage/build. |
| Python + web | `just quality` and `just ci-web` | Run both. |
| Docs taxonomy/link change | `UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py -q` | Required for docs index/state changes. |
| Browser smoke / QA | local `sab-web` + browser checks | Required for UI changes, auth/routing changes, or backend/config changes that can affect web flows. |
| Dead code check | `just deadcode` | Use before cleanup PRs. |
| Pre-commit all | `just precommit-all` | May need network on first hook install. |

Fallback commands:

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

## Branch And Commit Rules

- Use small, focused branches or direct `main` updates only when the maintainer workflow allows it.
- Use Conventional Commits.
- Commit titles and bodies are written in Korean for this repository.
- Keep one intent per commit.
- Do not pre-bump Release Please-owned files for feature changes.

Recommended format:

```bash
git commit -m "docs(api): 웹 API 계약 문서 정리" -m "라우트 스키마와 인증 경계를 코드 기준으로 정리해 신규 운영자가 API 표면을 빠르게 확인할 수 있게 한다."
```

## Pull Request Checklist

| Item | Required |
| --- | ---: |
| Purpose and scope are clear | yes |
| Runtime behavior changes are tested | yes |
| Config/env/API/report schema changes are documented | yes |
| Supabase migrations have rollback/recovery notes | yes when applicable |
| Screenshots or browser checks included for UI/auth/routing-affecting changes | yes when applicable |
| Secrets absent from diff, logs, screenshots, PR body | yes |
| `NOT_RUN` explains any skipped validation | yes |

## Documentation Rules

- README stays short and points to `docs/`.
- Current operational docs must have `상태:` metadata and document state sections.
- When docs and code conflict, prefer actual application code, then runtime/deploy config, CI, tests, env examples, current docs, then inference.
- Local QA reports, browser baselines, and screenshots belong under `.gstack/qa-reports/`; keep them local and summarize the result in the PR or handoff instead of committing the artifacts.
- Use `NEEDS_CONFIRMATION` for policy/credential/owner/deployment details not derivable from code.
- Use `NOT_RUN` for commands not executed.
- Do not paste real URLs, tokens, DB strings, customer names, personal emails, phone numbers, cookies, or private keys.

## Interface Change Checklist

Update docs and tests when changing:

- CLI options in `sab/__main__.py`
- Web API schemas in `web/src/lib/schemas.ts`
- Report JSON shape or Storage key format
- Supabase tables/RPC/policies in `supabase/migrations/`
- Environment variables or config keys
- GitHub Actions inputs/schedules
- Docker Compose ports/env
- Strategy logic or risk rules in `sab/signals/` and related modules

## Review Focus

For reviews, prioritize:

- correctness and data integrity
- secret handling
- provider failure behavior
- idempotency and duplicate run prevention
- Supabase RLS/RPC implications
- web auth/same-origin/local guard behavior
- test coverage and reproducibility
- documentation drift

NEEDS_CONFIRMATION: team-specific branch protection, required reviewer count, and release approval chain are not fully derivable from code.
