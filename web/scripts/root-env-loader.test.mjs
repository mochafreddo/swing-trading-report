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
    const missingPath = path.join(
      os.tmpdir(),
      "sab-root-env-loader-missing.env",
    );

    const result = loadRootEnv({ envPath: missingPath, env });

    expect(result).toEqual({
      loaded: false,
      path: missingPath,
      keys: [],
    });
    expect(env).toEqual({});
  });
});
