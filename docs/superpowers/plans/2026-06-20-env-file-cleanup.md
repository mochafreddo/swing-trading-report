# Environment File Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository root `.env` the single default local environment file for CLI, Docker Compose, and direct web scripts, then retire the ineffective local `web/.env` file.

**Architecture:** Add a small web-side root env loader that reads `/Users/mochafreddo/GitHub/swing-trading-report/.env` before web env validation and before spawning Next.js. Keep `.env.scheduler.local` as the scheduler-only env file and keep `.envrc.local` as an optional direnv export layer, but document that `web/.env` is not part of the supported runtime path.

**Tech Stack:** Node.js ESM scripts, Vitest, Next.js 16, Python pytest documentation contract tests, Docker Compose env interpolation.

---

## Context

The current environment file roles are:

- Root `.env.example`: committed template and test-backed contract.
- Root `.env`: ignored local secrets and runtime values. `sab` loads this file, and Docker Compose reads it for interpolation.
- Root `.env.scheduler.local`: ignored scheduler-only env file used by `docker-compose.scheduler.yml` and launchd wrapper scripts.
- Root `.envrc`: committed direnv entrypoint that sources ignored `.envrc.local`.
- Root `.envrc.local`: ignored direnv personal exports.
- `web/.env`: ignored local file containing a subset of web keys, but the supported `web` scripts run `node scripts/validate-env.mjs` before Next.js gets a chance to load Next-style env files.

Problem:

`web/.env` looks useful but is ineffective for `pnpm --dir web run dev`, `pnpm --dir web run build`, and `pnpm --dir web run start` because `web/scripts/validate-env.mjs` only reads `process.env`. This creates drift risk with root `.env` and `.envrc.local`.

Design choice:

Use root `.env` as the single default local env file. Load it explicitly from the web scripts so direct web commands and Docker Compose use the same source. Do not load `.env.scheduler.local` into web scripts.

Options considered:

- Docs-only cleanup: simple, but direct web commands still fail unless the shell has exported all required variables.
- Root `.env` loader in web scripts: keeps one local file for CLI, Docker Compose, and direct web commands; this is the selected option.
- Move to `web/.env`: aligns with Next.js conventions but splits local env from CLI and Docker Compose, increasing drift.

## File Structure

- Create `web/scripts/root-env-loader.mjs`: parse and load the repository root `.env` into a provided env object, defaulting to `process.env`, without overriding already-exported values.
- Create `web/scripts/root-env-loader.test.mjs`: unit tests for parsing, non-override precedence, quoted values, comments, and missing-file behavior.
- Modify `web/scripts/validate-env.mjs`: call `loadRootEnv()` before checking required web env values.
- Modify `web/scripts/run-next.mjs`: call `loadRootEnv()` before resolving bind host and spawning Next.js.
- Modify `docs/configuration.md`: document that direct web scripts preload root `.env` and that `web/.env` is unsupported.
- Modify `docs/config-reference.md`: mirror the file-role contract for operators.
- Modify `docs/local-development.md`: update local web startup guidance so developers do not create `web/.env`.
- Modify `tests/test_docs_state_contract.py`: add a lightweight contract that the docs state root `.env` is the web env source and `web/.env` is unsupported.
- Local cleanup outside git: move ignored `web/.env` out of the repository after confirming root `.env` has the same key names.

## Task 1: Add Root Env Loader Tests

**Files:**

- Create: `web/scripts/root-env-loader.test.mjs`
- Test: `web/scripts/root-env-loader.test.mjs`

- [ ] **Step 1: Add the failing loader tests**

Create `web/scripts/root-env-loader.test.mjs` with this content:

```js
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { loadRootEnv, parseEnvLine } from "./root-env-loader.mjs";

const tempDirs = [];

function makeEnvFile(content) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sab-root-env-loader-"));
  tempDirs.push(dir);
  const envPath = path.join(dir, ".env");
  fs.writeFileSync(envPath, content, "utf8");
  return envPath;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    const dir = tempDirs.pop();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("parseEnvLine", () => {
  it("parses plain and exported assignments", () => {
    expect(parseEnvLine("SUPABASE_URL=https://example.supabase.co")).toEqual([
      "SUPABASE_URL",
      "https://example.supabase.co",
    ]);
    expect(parseEnvLine("export SAB_BASIC_AUTH_USER=admin")).toEqual([
      "SAB_BASIC_AUTH_USER",
      "admin",
    ]);
  });

  it("ignores blank lines, comments, and invalid keys", () => {
    expect(parseEnvLine("")).toBeNull();
    expect(parseEnvLine("  # comment")).toBeNull();
    expect(parseEnvLine("1_BAD=value")).toBeNull();
    expect(parseEnvLine("NO_EQUALS")).toBeNull();
  });

  it("preserves hash characters inside quotes and removes inline comments", () => {
    expect(parseEnvLine('SAB_SESSION_SECRET="abc#def" # comment')).toEqual([
      "SAB_SESSION_SECRET",
      "abc#def",
    ]);
    expect(parseEnvLine("SAB_BASIC_AUTH_PASS='pass # with hash'")).toEqual([
      "SAB_BASIC_AUTH_PASS",
      "pass # with hash",
    ]);
  });
});

describe("loadRootEnv", () => {
  it("loads root env values into a supplied environment object", () => {
    const sessionSecretKey = "SAB_SESSION_" + "SECRET";
    const envPath = makeEnvFile(`
SUPABASE_URL=https://example.supabase.co
SUPABASE_SECRET_KEY=sb_secret_test
SAB_BASIC_AUTH_USER=admin
SAB_BASIC_AUTH_PASS="secret pass"
${sessionSecretKey}=session-secret-for-loader-test-only
`);
    const env = {};

    const result = loadRootEnv({ envPath, env });

    expect(result).toEqual({
      loaded: true,
      path: envPath,
      keys: [
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SAB_BASIC_AUTH_USER",
        "SAB_BASIC_AUTH_PASS",
        sessionSecretKey,
      ],
    });
    expect(env.SUPABASE_URL).toBe("https://example.supabase.co");
    expect(env.SAB_BASIC_AUTH_PASS).toBe("secret pass");
  });

  it("does not override already exported values by default", () => {
    const envPath = makeEnvFile("SUPABASE_URL=https://from-file.example\n");
    const env = { SUPABASE_URL: "https://from-shell.example" };

    loadRootEnv({ envPath, env });

    expect(env.SUPABASE_URL).toBe("https://from-shell.example");
  });

  it("overrides already exported values only when requested", () => {
    const envPath = makeEnvFile("SUPABASE_URL=https://from-file.example\n");
    const env = { SUPABASE_URL: "https://from-shell.example" };

    loadRootEnv({ envPath, env, override: true });

    expect(env.SUPABASE_URL).toBe("https://from-file.example");
  });

  it("is a no-op when the env file is missing", () => {
    const env = {};
    const missingPath = path.join(os.tmpdir(), "sab-root-env-loader-missing.env");

    const result = loadRootEnv({ envPath: missingPath, env });

    expect(result).toEqual({
      loaded: false,
      path: missingPath,
      keys: [],
    });
    expect(env).toEqual({});
  });
});
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
pnpm --dir web run test -- scripts/root-env-loader.test.mjs
```

Expected: FAIL with an import error for `./root-env-loader.mjs`.

## Task 2: Implement Root Env Loader

**Files:**

- Create: `web/scripts/root-env-loader.mjs`
- Test: `web/scripts/root-env-loader.test.mjs`

- [ ] **Step 1: Add the loader implementation**

Create `web/scripts/root-env-loader.mjs` with this content:

```js
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const defaultRootEnvPath = path.resolve(scriptDir, "../..", ".env");

export function loadRootEnv(options = {}) {
  const envPath = options.envPath ?? defaultRootEnvPath;
  const env = options.env ?? process.env;
  const override = options.override === true;

  let contents;
  try {
    contents = fs.readFileSync(envPath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") {
      return { loaded: false, path: envPath, keys: [] };
    }
    throw error;
  }

  const keys = [];
  for (const line of contents.split(/\r?\n/)) {
    const parsed = parseEnvLine(line);
    if (!parsed) {
      continue;
    }
    const [key, value] = parsed;
    keys.push(key);
    if (override || env[key] === undefined) {
      env[key] = value;
    }
  }

  return { loaded: true, path: envPath, keys };
}

export function parseEnvLine(rawLine) {
  let line = rawLine.trim();
  if (!line || line.startsWith("#")) {
    return null;
  }
  if (line.startsWith("export ")) {
    line = line.slice("export ".length).trimStart();
  }

  const separatorIndex = line.indexOf("=");
  if (separatorIndex < 1) {
    return null;
  }

  const key = line.slice(0, separatorIndex).trim();
  if (!isValidEnvKey(key)) {
    return null;
  }

  const rawValue = stripInlineComment(line.slice(separatorIndex + 1)).trim();
  return [key, unquoteValue(rawValue)];
}

function isValidEnvKey(key) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(key);
}

function stripInlineComment(value) {
  let inSingle = false;
  let inDouble = false;
  let escaped = false;

  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];

    if (escaped) {
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      continue;
    }
    if (char === "'" && !inDouble) {
      inSingle = !inSingle;
      continue;
    }
    if (char === '"' && !inSingle) {
      inDouble = !inDouble;
      continue;
    }
    if (
      char === "#" &&
      !inSingle &&
      !inDouble &&
      (index === 0 || /\s/.test(value[index - 1]))
    ) {
      return value.slice(0, index);
    }
  }

  return value;
}

function unquoteValue(value) {
  if (value.length >= 2) {
    const first = value[0];
    const last = value[value.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return value.slice(1, -1);
    }
  }
  return value;
}
```

- [ ] **Step 2: Run the loader tests**

Run:

```bash
pnpm --dir web run test -- scripts/root-env-loader.test.mjs
```

Expected: PASS.

- [ ] **Step 3: Commit the loader and tests**

Run:

```bash
git add web/scripts/root-env-loader.mjs web/scripts/root-env-loader.test.mjs
git commit -m "fix(web): 루트 env 로더 추가" -m "웹 실행 스크립트가 검증 전에 저장소 루트 .env를 읽을 수 있도록 전용 로더와 단위 테스트를 추가한다."
```

## Task 3: Wire Loader Into Web Runtime Scripts

**Files:**

- Modify: `web/scripts/validate-env.mjs`
- Modify: `web/scripts/run-next.mjs`
- Test: `web/scripts/root-env-loader.test.mjs`

- [ ] **Step 1: Load root `.env` before validation**

Modify the top of `web/scripts/validate-env.mjs` so the file starts with:

```js
import { loadRootEnv } from "./root-env-loader.mjs";

loadRootEnv();

function requireNonEmpty(name) {
```

Leave the existing validation functions unchanged after that insertion.

- [ ] **Step 2: Load root `.env` before spawning Next.js**

Modify the top of `web/scripts/run-next.mjs` so the imports and initial setup are:

```js
import { spawn } from "node:child_process";
import { createRequire } from "node:module";

import {
  hasOption,
  normalizeEnvValue,
  resolveEffectiveBindHost,
} from "./next-args.mjs";
import { loadRootEnv } from "./root-env-loader.mjs";
import { enforceStartupBindGuard } from "./startup-bind-guard.mjs";

loadRootEnv();

const require = createRequire(import.meta.url);
```

Keep the rest of `web/scripts/run-next.mjs` unchanged.

- [ ] **Step 3: Run script-level web tests**

Run:

```bash
pnpm --dir web run test -- scripts/root-env-loader.test.mjs scripts/next-args.test.mjs scripts/startup-bind-guard.test.mjs
```

Expected: PASS.

- [ ] **Step 4: Verify direct web validation can use root `.env`**

Run:

```bash
pnpm --dir web run build
```

Expected: build no longer fails at `Missing required env var` when root `.env` contains `SAB_BASIC_AUTH_USER`, `SAB_BASIC_AUTH_PASS`, `SAB_SESSION_SECRET`, `SUPABASE_URL`, and one of `SUPABASE_SECRET_KEY` or `SUPABASE_SERVICE_ROLE_KEY`.

If this command fails for an unrelated Next.js build error, capture the first failing file and run:

```bash
pnpm --dir web run test -- scripts/root-env-loader.test.mjs scripts/next-args.test.mjs scripts/startup-bind-guard.test.mjs
```

Expected: PASS; record the unrelated build failure in the final implementation report.

- [ ] **Step 5: Commit the web script wiring**

Run:

```bash
git add web/scripts/validate-env.mjs web/scripts/run-next.mjs
git commit -m "fix(web): 루트 env를 웹 실행에 사용" -m "검증 스크립트와 Next 실행 래퍼가 저장소 루트 .env를 먼저 읽도록 연결해 web/.env 중복 의존을 제거한다."
```

## Task 4: Document Supported Env File Roles

**Files:**

- Modify: `docs/configuration.md`
- Modify: `docs/config-reference.md`
- Modify: `docs/local-development.md`
- Modify: `tests/test_docs_state_contract.py`

- [ ] **Step 1: Add a docs contract test**

Append this test to `tests/test_docs_state_contract.py`:

```python
def test_web_env_docs_use_root_env_and_reject_web_env_file() -> None:
    configuration_text = _read(Path("docs/configuration.md"))
    config_reference_text = _read(Path("docs/config-reference.md"))
    local_development_text = _read(Path("docs/local-development.md"))

    required_phrases = (
        "Direct web scripts preload the repository root `.env` before validation.",
        "`web/.env` is not a supported env file for this project.",
    )
    for phrase in required_phrases:
        assert phrase in configuration_text
        assert phrase in config_reference_text
        assert phrase in local_development_text
```

- [ ] **Step 2: Run the docs contract test to verify it fails**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py::test_web_env_docs_use_root_env_and_reject_web_env_file -q
```

Expected: FAIL because the new documentation phrases are not present yet.

- [ ] **Step 3: Update `docs/configuration.md`**

In `docs/configuration.md`, under `## 기본 원칙`, add these two bullets after the existing `.env` and direnv bullet:

```markdown
- Direct web scripts preload the repository root `.env` before validation.
- `web/.env` is not a supported env file for this project.
```

In the file role table, keep the existing rows and add this row after `.env`:

```markdown
| `web/.env` | unsupported local duplicate; do not create | no |
```

- [ ] **Step 4: Update `docs/config-reference.md`**

In `docs/config-reference.md`, under the section that explains `.env` and direnv behavior, add:

```markdown
- Direct web scripts preload the repository root `.env` before validation.
- `web/.env` is not a supported env file for this project.
```

In the file role table, add this row after `.env`:

```markdown
| `web/.env` | unsupported local duplicate; do not create | 커밋 금지 |
```

- [ ] **Step 5: Update `docs/local-development.md`**

Find the local web setup section that tells developers how to prepare env values. Add this paragraph before the first web startup command:

```markdown
Direct web scripts preload the repository root `.env` before validation. `web/.env` is not a supported env file for this project. Keep local web secrets in the root `.env` or export them through `.envrc.local` when direnv is active.
```

- [ ] **Step 6: Run the docs contract test**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py::test_web_env_docs_use_root_env_and_reject_web_env_file -q
```

Expected: PASS.

- [ ] **Step 7: Commit the docs contract**

Run:

```bash
git add docs/configuration.md docs/config-reference.md docs/local-development.md tests/test_docs_state_contract.py
git commit -m "docs(config): env 파일 역할 정리" -m "루트 .env가 웹 직접 실행의 기본 env 파일임을 문서화하고 web/.env는 지원하지 않는 중복 파일로 명시한다."
```

## Task 5: Safely Retire Local `web/.env`

**Files:**

- Local ignored file: `web/.env`
- No committed file changes expected.

- [ ] **Step 1: Confirm `web/.env` is ignored and untracked**

Run:

```bash
git status --ignored --short web/.env
git ls-files web/.env --stage
```

Expected:

```text
!! web/.env
```

The second command prints no output.

- [ ] **Step 2: Compare only key names, not values**

Run:

```bash
awk 'BEGIN{FS="="} /^[[:space:]]*#/ || /^[[:space:]]*$/ {next} /^[A-Za-z_][A-Za-z0-9_]*=/ {print FILENAME ":" $1}' .env web/.env
```

Expected: every key printed for `web/.env` also appears for `.env`. Do not print values.

- [ ] **Step 3: Move the ignored duplicate out of the repository**

Run this only after Step 2 confirms all `web/.env` key names are covered by root `.env`:

```bash
mv web/.env /private/tmp/swing-trading-report-web.env.backup
```

Expected: `web/.env` no longer exists, and `/private/tmp/swing-trading-report-web.env.backup` exists for rollback during the same cleanup session.

- [ ] **Step 4: Verify direct web scripts still pass env validation**

Run:

```bash
pnpm --dir web run test -- scripts/root-env-loader.test.mjs
pnpm --dir web run build
```

Expected: loader test passes; build gets past `web/scripts/validate-env.mjs` using root `.env`.

- [ ] **Step 5: Commit not required**

No commit is required for this task because `web/.env` is ignored and untracked. Mention the local file move in the final implementation report.

## Task 6: Full Validation

**Files:**

- No new files.
- Validates all previous tasks.

- [ ] **Step 1: Run web CI gate**

Run:

```bash
just ci-web
```

Expected: PASS.

If `just ci-web` fails because `pnpm` is not on `PATH`, run:

```bash
mise exec -- just ci-web
```

Expected: PASS.

- [ ] **Step 2: Run targeted Python docs/env tests**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_docs_state_contract.py tests/test_env_example_v11.py -q
```

Expected: PASS.

- [ ] **Step 3: Review focused diff**

Run:

```bash
git diff --stat
git diff -- web/scripts/root-env-loader.mjs web/scripts/validate-env.mjs web/scripts/run-next.mjs web/scripts/root-env-loader.test.mjs docs/configuration.md docs/config-reference.md docs/local-development.md tests/test_docs_state_contract.py
```

Expected: diff is limited to the loader, script wiring, docs, and docs contract test. No secret values appear in the diff.

## Self-Review

Spec coverage:

- Identifies unused or ineffective env-related files: covered by context and Task 5.
- Gives a concrete resolution: root `.env` becomes the single default local env file, with scheduler and direnv roles preserved.
- Prevents future drift: covered by web root env loader tests and documentation contract test.
- Avoids secret exposure: all commands compare key names only; no command prints env values.

Placeholder scan:

- No empty implementation steps are left.
- Every code-changing step includes exact code.
- Every validation step includes exact commands and expected results.

Type and naming consistency:

- Loader file name is consistently `root-env-loader.mjs`.
- Exported functions are consistently `loadRootEnv` and `parseEnvLine`.
- Documentation contract phrases are identical across the test and planned docs edits.
