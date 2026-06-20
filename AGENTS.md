# AGENTS.md

Make the smallest safe change that fully solves the problem.
Default loop: **understand -> scope -> change -> test -> review -> refactor if needed**.

## Project Overview

`swing-trading-report` — KR/US 시장용 on-demand 스윙 트레이딩 시그널 스캐너 및 리포트 생성기. Python `sab` 패키지가 스캔을 실행해 JSON 리포트를 쓰고, 로컬 Next.js UI가 이를 열람하며, Supabase가 보유목록/리포트/실행이력을 저장하고, GitHub Actions가 스케줄 스캔 + 텔레그램/슬랙 알림을 수행. 툴체인 버전은 `mise.toml`에 고정(Python 3.14, uv, node, pnpm, just, direnv).

```
sab/         # Python 패키지; 엔트리포인트 `python -m sab` (scan | sell | entry | ai-brief | ai-brief-scheduled)
             #   signals/ screener/ report/ data/ scheduler/ utils/ + scan/sell/entry/ai_brief 모듈
web/         # 로컬 UI: Next.js 16 + React 19 + TypeScript (`docker compose up -d --build web`로 기동)
tests/       # pytest 스위트 (~83개 테스트 파일)
scripts/     # 유지보수/평가 스크립트 (`uv run python scripts/...`로 실행)
docs/        # STRATEGY.md(전략 로직), ARCHITECTURE.md(컴포넌트 흐름), PRD.md, runbook.md, adr/
reports/     # 생성 산출물: YYYY-MM-DD(-n).{buy|sell|entry|ai-brief}.json
config.yaml, holdings.yaml   # 런타임 설정(config.yaml은 저장소에 기본값 포함) + 보유목록(holdings.yaml은 gitignore, holdings.example.yaml에서 복사)
```

이 파일은 `AGENTS.md`이며 `CLAUDE.md`는 이를 가리키는 심링크(다른 에이전트와 공유). `AGENTS.md`를 제자리에서 편집할 것 — 새 파일로 교체하면 심링크가 깨짐.

Shared-agent note: tool-specific rules are marked when they depend on Codex
or a particular sandbox. Other agents should preserve the intent and use the
closest safe equivalent instead of assuming the exact tool or permission model
exists.

Instruction budget: keep this file focused and comfortably below Codex's
default project instruction budget. Move directory-specific rules to nested
`AGENTS.md` files when they only matter inside that subtree.

## Rule Priority

Follow higher-priority system, developer, and user instructions first. Within
this file, when rules conflict, follow this priority:

1. **Safety, security, privacy, and permissions**
2. **Correctness**
3. **Repository conventions**
4. **Clarity**
5. **Simplicity**

Safety, honesty, privacy, and permission constraints do not yield. Prefer the
repository's existing architecture, naming, error handling, and test patterns
over generic style rules unless doing so would weaken safety, correctness,
security, or maintainability.

## MUST

### Understand Before Changing

- For small, low-risk changes, proceed after reading enough local context to act safely.
- For non-trivial, multi-file, or risky changes, leave a short problem brief covering **Context**, **Problem**, **Goal**, **Constraints**, and relevant **Non-Goals** when useful.
- For architectural or high-risk changes, expand the brief into a one-page plan and compare viable options when practical.
- Before editing non-trivial work, state the intended scope, likely impact, and planned validation in 1-3 lines.
- Read files you will edit end to end when practical. For generated, very large, or repetitive files, inspect the full relevant structure and all sections touched by the change.
- Trace related definitions, references, call paths, tests, configuration, feature flags, and docs when they could affect behavior or reviewability.
- Do not edit a symbol until you understand its inputs, outputs, invariants, and side effects.

### Scope Control

- Keep tasks, commits, and PRs small and focused.
- Do not mix unrelated refactors, renames, dependency upgrades, or formatting-only changes into functional changes.
- Preserve existing public behavior unless the requested change explicitly says otherwise.
- If behavior, APIs, schemas, configuration, or UX changes, document it clearly in the diff, PR, ADR, or docs as appropriate.

### Code Quality

- Use names that reveal intent.
- Prefer explicit code over hidden magic.
- Keep functions focused on one responsibility.
- Push side effects such as I/O, network access, filesystem access, and global state to boundaries.
- Prefer guard clauses and simple control flow.
- Replace hardcoded values with constants only when it improves clarity.
- Keep code in an **Input -> Process -> Return** shape when practical.

### Errors, Logging, and Safety

- Catch specific exceptions.
- Provide actionable error messages to users.
- Use structured logging when the codebase supports it.
- Do not log secrets or sensitive data.
- Validate, normalize, and encode inputs appropriately.
- Use parameterized operations for database or query-like work.
- Apply least privilege to permissions, credentials, and access scope.

### Testing

- Match tests and validation to behavioral risk and blast radius.
- New code that changes runtime behavior, public contracts, risk judgment, or data processing results must include tests.
- Bug fixes require regression tests unless reproducing the bug is impractical; record why when skipping one.
- Prefer a Red/Green/Refactor cycle for feature additions and bug fixes when practical. Do not force it for documentation-only, metadata-only, or purely static changes.
- Tests must be deterministic and independent. Replace external systems with fakes, mocks, or contract tests.
- When behavior changes, include related tests and docs in the same change.
- Documentation, configuration descriptions, skill/plugin metadata, and static manifests usually need structure, schema, link, or diff validation rather than runtime tests.
- For strategy logic, APIs, schemas, risk boundaries, or build/deploy paths, pass the relevant full gate before finishing.
- Validation matrix:
  - Python-only changes: prefer `just quality`; fallback to targeted pytest plus `ruff` and `mypy`.
  - Web-only changes: prefer `just ci-web`; fallback to the affected `just web-*` checks.
  - Python + web changes: run both relevant gates or explain the narrower validation.
  - Docs/static-only changes: run the cheapest check that catches formatting, syntax, links, schema, or whitespace issues.
- If validation cannot be run or a full gate is skipped, state why and describe the next best check.

## SHOULD

### Decision-Making

- For complex or risky changes, compare at least two viable options when practical.
- For each option, leave one-line **pros**, **cons**, and **risks**.
- Choose the simplest solution that safely satisfies the goal.

### Design and Maintainability

- Prefer small files and small functions.
- Avoid premature abstraction.
- Apply DRY only when duplication is real, repeated, and stable.
- Keep interfaces simple and explicit.
- Prefer composition over hidden coupling.

### Size Targets

These are default targets, not hard blockers.

- file: **~300 LOC or less**
- function: **~50 LOC or less**
- parameters: **~5 or fewer**
- cyclomatic complexity: **~10 or lower**

If exceeding these targets is clearer or better aligned with repository conventions, keep it and leave a short reason.

### Review Mindset

- Review from a senior engineer's perspective.
- Do not act on guesses.
- Do not stop at "it works"; check understandability, testability, and safety.
- Refactor only when it reduces risk or meaningfully improves clarity within the changed scope.

## WHEN APPLICABLE

### Time

- Consider time zones, DST, locale, date boundaries, and market open/close boundaries.

### Concurrency / Reliability

- Review concurrency, locking, retries, idempotency, duplicate execution, race conditions, and deadlock risk.

### Distributed Systems / Observability

- Propagate request IDs, trace IDs, and correlation IDs when the system supports them.
- Preserve useful metrics, logs, and tracing hooks.

### End-to-End Tests

- Include at least one happy path and one failure path when practical.

### Security-Sensitive Paths

- Pay special attention to auth, authz, secret handling, token flow, redirects, deserialization, file access, and external input boundaries.

## ANTI-PATTERNS

- Do not change code before reading enough related context.
- Do not make speculative changes.
- Do not expose secrets in code, logs, tests, tickets, or screenshots.
- Do not ignore warnings, failing tests, or flaky behavior.
- Do not use broad exceptions without a documented reason.
- Do not introduce abstractions, indirection, or optimization without a good reason.
- Do not silently change behavior, contracts, or defaults.
- Do not leave TODOs for core correctness, security, or data integrity issues.

## CHANGE CHECKLIST

- The problem is clearly defined.
- The change is the smallest safe solution.
- Relevant context was read, and edited files were reviewed carefully.
- Related references and call paths were checked.
- Assumptions were recorded.
- Tests cover the change.
- Required docs, configuration, and messages were updated.
- No secrets were added.
- The diff is focused and reviewable.

## Repository-Specific Rules

### Execution Priority

- Toolchain sync: run `mise install` only when pinned tools are missing or stale, after `mise.toml` changes, or when a command fails because the pinned tool is unavailable.
- If `just ...` fails because `pnpm` is not on `PATH`, rerun through mise:
  `mise exec -- just ...` (for example, `mise exec -- just ci-web`).
- When tool versions change, refresh the lockfile: `mise lock --platform linux-x64,macos-arm64 && mise install`
- `direnv allow .` is a local trust decision, so automation agents must not run it arbitrarily. If needed, ask for user approval and run it once.
- direnv does not auto-load `.env`; it only loads `.envrc.local`.
- Store secrets and private overrides only in `.envrc.local`, and do not commit them.

### Recommended Commands (just)

- Recipe list: `just --list`
- Dependencies/locks: `just sync`, `just lock-upgrade`
- Dependency audit: `just audit` (`just audit-python-osv` and `just audit-web-prod` for source-specific checks)
- Trading workflows: `just scan`, `just sell`, `just entry`
- AI Brief workflows: `just ai-brief-source-collect`, `just ai-brief-source-eval`, `just ai-brief-source-live-compare`, `just ai-brief-eval`
- Quality gates: for Python-only changes, run `just quality` (`just check` is the same alias); for web changes, run `just ci-web`; for Python+web changes, run both.
- Dead code check: `just deadcode`
- pre-commit: `just precommit-all`
- CI parity: `just ci-python`, `just ci-web` (`ci-web` runs with fixed secret-free CI placeholder env only)

### Direct Execution (uv Fallback)

- `UV_CACHE_DIR=.uv-cache uv sync --all-extras --all-groups`
- `UV_CACHE_DIR=.uv-cache uv lock --upgrade`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab entry`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab ai-brief --entry-report <path>`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`
- `UV_CACHE_DIR=.uv-cache uv run python scripts/run_vulture.py`
- `UV_CACHE_DIR=.uv-cache uv export --quiet --locked --all-extras --all-groups --no-emit-project --output-file /tmp/swing-trading-report-pip-audit-requirements.txt`
- `pip-audit --disable-pip -r /tmp/swing-trading-report-pip-audit-requirements.txt`
- `pnpm --dir web audit --audit-level low`
- `pnpm --dir web run deadcode`

### Dependency Audit Gotchas

- Prefer `just audit` for combined Python + web dependency audits.
- `pip-audit --locked .` does not currently read this project's `uv.lock`; export from `uv.lock` first and audit the generated requirements file.
- Use hash-including `uv export` with `pip-audit --disable-pip`; plain `pip-audit -r ...` may create a temporary venv and fail in sandboxed `ensurepip`.
- Keep pnpm security overrides in `web/pnpm-workspace.yaml`, not `web/package.json`; `web/scripts/dependency-overrides.test.mjs` enforces this.
- If `pnpm why` fails with a pnpm store SQLite permission error, inspect `web/pnpm-lock.yaml` directly for dependency paths.

## Health Stack

- typecheck: just mypy
- typecheck-web: just web-typecheck
- lint: just ruff
- format: just format-check
- lint-web: just web-lint
- format-web: just web-format-check
- test: just test
- test-web: just web-test
- deadcode: just deadcode-python
- deadcode-web: just deadcode-web
- shell: shellcheck scripts/upgrade_deps.sh

### Documentation (Strategy Logic)

- If strategy logic changes, including signals, risk, evaluation criteria, or mode-specific rules, update [STRATEGY.md](docs/STRATEGY.md) with it.
- If logic, flow, or component responsibilities change, evaluate whether [ARCHITECTURE.md](docs/ARCHITECTURE.md) should also be updated.

### Release Automation

- Release Please owns `.release-please-manifest.json`, `CHANGELOG.md`, `pyproject.toml`, and `web/package.json` release bumps after feature PRs land.
- Do not pre-bump Release Please-owned files in feature PRs. If a release is recovered manually, create the matching GitHub release/tag for the manifest version before allowing Release Please to run again.
- When Release Please updates `pyproject.toml`, refresh `uv.lock` with `UV_CACHE_DIR=.uv-cache uv lock` before merging the release PR.

### Pre-commit (Sandbox)

- Recommended: `just precommit-all`
- Single hook, recommended: `just precommit mypy --all-files`
- Config validation, recommended: `just precommit-validate`
- Full run: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- Single hook run: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- Hook updates: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- Config validation: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- The first run may need network access to download hook repositories.
- When committing staged `web/` changes, check `pnpm --dir web run lint` and `pnpm --dir web run format:check`. When staged changes include `web/src/app/`, also check the `web-route-static-check` hook (`uv run python scripts/check_next_app_routes.py`).
- Web typechecking is excluded from pre-commit and enforced in CI with `pnpm run typecheck` in the `web` job of `.github/workflows/ci.yml`.

### Web Smoke Checks

- Priority: because `next dev` port binding can fail with `EPERM` in the sandbox, if the `sab-web` container is running, verify it first at `http://127.0.0.1:${WEB_HOST_PORT}` when `WEB_HOST_PORT` is set, or at the default `http://127.0.0.1:55300` when it is unset.
- `/run` success condition: if `GITHUB_OWNER`, `GITHUB_REPO`, or `GITHUB_PAT` is empty, `/api/run` fails with a 500 from Zod validation.
- Browser automation fallback: Playwright Chrome launch can fail from session conflicts. When that happens, switch to `chrome-devtools` based checks.

### GitHub Actions Lint Tips

- `actionlint` in `workflow_audit` can fail on `shellcheck` style warnings such as `SC2129`.
- In GitHub Actions `run: |` blocks, when using a heredoc such as `cat <<'EOF'`, the closing token (`EOF`) must start at the beginning of the line. Indentation can cause `SC1039`, `SC1072`, and `SC1073` failures.
- Prefer `printf` over heredocs for simple string file creation.
- Local `python` execution can be unstable, so repository work scripts should prefer `uv run python ...`.
- Reproduce workflow syntax and shell lint locally with: `docker run --rm -v "$PWD":/work -w /work rhysd/actionlint:latest`

### Current Documentation

- When current or version-specific external behavior matters, use authoritative current docs instead of memory.
- Prefer official docs or repository-local docs when they are more appropriate than third-party summaries.
- Codex: Prefer checking Context7 MCP for non-OpenAI library/API docs, code generation, or setup/configuration steps when it is available and a good fit.
- Codex: When using Context7, first resolve the library ID with `resolve-library-id`, then fetch current docs with `query-docs`.

### Commits

- Use Conventional Commits, and keep one intent per commit.
- Split commits when unrelated concerns are mixed, and avoid ambiguous commit messages.
- Write commit message titles and bodies in Korean.
- The default format is one title line (`type(scope): summary`), one blank line, then a body when needed. Do not split the body sentence by sentence; write it as paragraphs.
- Do not pass `-m` once per sentence in the CLI. The recommended format is `git commit -m "title" -m "entire body"`.
- If the body needs line breaks, do not put `"\n"` inside double quotes. Use zsh `$'...'` quoting or an editor. Example: `git commit -m "chore(ci): ..." -m $'- item 1\n- item 2'`
- Correcting pushed commit messages or rewriting pushed history is human-led work. Check branch policy and collaboration context first. Automation agents should prefer non-interactive git methods and use force-push commands only when the user requests them.
- Run git commands such as `git status`, `git add`, and `git commit` directly, without a shell wrapper like `/bin/zsh -lc`.
- Codex: run `git push` with elevated permissions (`sandbox_permissions="require_escalated"`).

## Deploy Configuration (configured by /setup-deploy)

- Platform: custom/local Docker + GitHub Actions
- Production URL: `http://127.0.0.1:55300`
- Deploy workflow: local Docker manual deploy; GitHub Actions workflow files deploy by merge to `main`
- Deploy status command: `docker compose ps`
- Merge method: merge
- Project type: local web app + Python CLI automation
- Post-deploy health check: `http://127.0.0.1:55300/login`

### Custom deploy hooks

- Pre-merge: `just quality` and `just ci-web`
- Deploy trigger: `docker compose up -d --build web`
- Deploy status: `docker compose ps`
- Health check: `curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:${WEB_HOST_PORT:-55300}/login`
