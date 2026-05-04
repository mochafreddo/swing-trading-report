# AGENTS.md

Make the smallest safe change that fully solves the problem.
Default loop: **understand -> scope -> change -> test -> review -> refactor if needed**.

## Rule Priority

When rules conflict, follow this priority:

1. **Correctness**
2. **Security**
3. **Repository conventions**
4. **Clarity**
5. **Simplicity**

Prefer the repository's existing architecture, naming, error handling, and test patterns over generic style rules. The exception is when doing so would weaken correctness, security, or maintainability.

## MUST

### Understand Before Changing

- Before non-trivial, multi-file, or risky changes, leave a short problem brief.
- The problem brief must include at least **Context**, **Problem**, **Goal**, **Non-Goals**, and **Constraints**.
- Expand the brief into a more detailed one-pager for multi-file, high-risk, or architectural changes.
- Before non-trivial changes, leave a 1-3 line impact note.
- The impact note must include what changes, what might break, and which tests/docs need to change with it.
- Read all affected files from start to finish before editing them.
- Trace related definitions, references, call paths, tests, configuration, feature flags, and docs.
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

- New code that changes runtime behavior, public contracts, risk judgment, or data processing results must include tests.
- Bug fixes require regression tests. When possible, write the failing test first.
- Tests must be deterministic and independent. Replace external systems with fakes, mocks, or contract tests.
- When behavior changes, include related tests and docs in the same change.
- Feature additions and bug fixes should default to a Red/Green/Refactor cycle.
- Red: write the failing test first and confirm it fails before implementing.
- Green: write only the minimum code needed to pass the test.
- Refactor: remove duplication and improve structure only while tests are passing.
- Do not fix a bug before adding a reproduction test. If that is unavoidable, record why.
- Documentation, configuration descriptions, skill/plugin metadata, and static manifests are non-runtime changes and do not always require execution tests. Prefer static validation appropriate to the change, such as link, structure, or schema validation.
- Even for non-runtime changes, first consider adding minimal structure validation if the file is used as a real load path, contract file, or automation input.
- Apply quality gates in proportion to the change. For strategy logic, APIs, schemas, risk boundaries, or build/deploy paths, pass all relevant gates before finishing the cycle.
- Docs/metadata-only changes may be covered by related static validation or targeted tests. If you skip the full gate, record why.
- Recommended: for Python-only changes, run `just quality`; for web changes, run `just ci-web`; for Python+web changes, run both.
- Fallback: for Python, run `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`, `UV_CACHE_DIR=.uv-cache uv run ruff check .`, and `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`; for web, run `just web-lint`, `just web-format-check`, `just web-typecheck`, `just web-test`, and `just web-build` separately.

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
- All affected files were read from start to finish.
- Related references and call paths were checked.
- Assumptions were recorded.
- Tests cover the change.
- Required docs, configuration, and messages were updated.
- No secrets were added.
- The diff is focused and reviewable.

## Repository-Specific Rules

### Execution Priority

- Toolchain sync: `mise install`
- When tool versions change, refresh the lockfile: `mise lock --platform linux-x64,macos-arm64 && mise install`
- `direnv allow .` is a local trust decision, so automation agents must not run it arbitrarily. If needed, ask for user approval and run it once.
- direnv does not auto-load `.env`; it only loads `.envrc.local`.
- Store secrets and private overrides only in `.envrc.local`, and do not commit them.

### Recommended Commands (just)

- Recipe list: `just --list`
- Dependencies/locks: `just sync`, `just lock-upgrade`
- Trading workflows: `just scan`, `just sell`, `just entry`
- Quality gates: for Python-only changes, run `just quality` (`just check` is the same alias); for web changes, run `just ci-web`; for Python+web changes, run both.
- Dead code check: `just deadcode`
- pre-commit: `just precommit-all`
- CI parity: `just ci-python`, `just ci-web` (`ci-web` runs with fixed secret-free CI placeholder env only)

### Direct Execution (uv Fallback)

- `UV_CACHE_DIR=.uv-cache uv sync --all-extras --dev`
- `UV_CACHE_DIR=.uv-cache uv lock --upgrade`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab scan`
- `UV_CACHE_DIR=.uv-cache uv run python -m sab sell`
- `UV_CACHE_DIR=.uv-cache uv run ruff check .`
- `UV_CACHE_DIR=.uv-cache uv run ruff format --check .`
- `UV_CACHE_DIR=.uv-cache uv run mypy --config-file pyproject.toml`
- `UV_CACHE_DIR=.uv-cache uv run python -m pytest -q`
- `UV_CACHE_DIR=.uv-cache uv run python scripts/run_vulture.py`
- `pnpm --dir web run deadcode`

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

### Pre-commit (Sandbox)

- Recommended: `just precommit-all`
- Single hook, recommended: `just precommit mypy --all-files`
- Config validation, recommended: `just precommit-validate`
- Full run: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run --all-files`
- Single hook run: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit run mypy --all-files`
- Hook updates: `PRE_COMMIT_HOME=.pre-commit-cache UV_CACHE_DIR=.uv-cache uv run pre-commit autoupdate`
- Config validation: `UV_CACHE_DIR=.uv-cache uv run pre-commit validate-config`
- The first run may need network access to download hook repositories.
- When committing staged `web/` changes, check `pnpm --dir web run lint` and `pnpm --dir web run format:check`.
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

### Context7 MCP

- Prefer checking Context7 MCP when external library/API docs, code generation, or setup/configuration steps are needed.
- If official docs or another primary source is more appropriate, or if a higher-priority instruction has a separate source rule, follow that rule first.
- When using Context7, first resolve the library ID with `resolve-library-id`, then fetch current docs with `query-docs`.

### Commits

- Use Conventional Commits, and keep one intent per commit.
- Split commits when unrelated concerns are mixed, and avoid ambiguous commit messages.
- Write commit message titles and bodies in Korean.
- The default format is one title line (`type(scope): summary`), one blank line, then a body when needed. Do not split the body sentence by sentence; write it as paragraphs.
- Do not pass `-m` once per sentence in the CLI. The recommended format is `git commit -m "title" -m "entire body"`.
- If the body needs line breaks, do not put `"\n"` inside double quotes. Use zsh `$'...'` quoting or an editor. Example: `git commit -m "chore(ci): ..." -m $'- item 1\n- item 2'`
- Correcting pushed commit messages or rewriting pushed history is human-led work. Check branch policy and collaboration context first. Automation agents should prefer non-interactive git methods and use force-push commands only when the user requests them.
- Run git commands such as `git status`, `git add`, and `git commit` directly, without a shell wrapper like `/bin/zsh -lc`.
- Run `git push` with elevated permissions (`sandbox_permissions="require_escalated"`).
