import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const CLIENT_ROOTS = [
  path.resolve(process.cwd(), "src/components"),
  path.resolve(process.cwd(), "src/app"),
  path.resolve(process.cwd(), "src/lib"),
];

const SERVER_ONLY_TOKEN = 'import "server-only"';
const LIB_ROOT = path.resolve(process.cwd(), "src/lib");

const DISALLOWED_TOKENS = [
  "SUPABASE_SECRET_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "GITHUB_PAT",
  "SAB_BASIC_AUTH_PASS",
  "SAB_SESSION_SECRET",
  "@/lib/env.server",
];

interface CollectFilesOptions {
  skipApiRoutes?: boolean;
  skipServerOnly?: boolean;
}

function collectTypeScriptFiles(
  root: string,
  options: CollectFilesOptions = {},
  acc: string[] = [],
): string[] {
  if (!fs.existsSync(root)) {
    return acc;
  }

  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      if (
        (options.skipApiRoutes && fullPath.includes(`${path.sep}api`)) ||
        fullPath.includes(`${path.sep}__tests__`)
      ) {
        continue;
      }
      collectTypeScriptFiles(fullPath, options, acc);
      continue;
    }
    if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) {
      if (options.skipApiRoutes && entry.name === "route.ts") {
        continue;
      }
      const source = fs.readFileSync(fullPath, "utf-8");
      if (options.skipServerOnly && source.includes(SERVER_ONLY_TOKEN)) {
        continue;
      }
      acc.push(fullPath);
    }
  }

  return acc;
}

function collectClientOrientedFiles(): string[] {
  return CLIENT_ROOTS.flatMap((root) =>
    collectTypeScriptFiles(root, {
      skipApiRoutes: true,
      skipServerOnly: true,
    }),
  );
}

function toLibSpecifier(filePath: string): string {
  const relative = path.relative(LIB_ROOT, filePath);
  const withoutExtension = relative.replace(/\.(tsx|ts)$/, "");
  return `@/lib/${withoutExtension.split(path.sep).join("/")}`;
}

function resolveLibSpecifier(
  filePath: string,
  specifier: string,
): string | null {
  if (specifier.startsWith("@/lib/")) {
    return specifier;
  }
  if (!specifier.startsWith(".")) {
    return null;
  }

  const resolved = path.resolve(path.dirname(filePath), specifier);
  if (!resolved.startsWith(`${LIB_ROOT}${path.sep}`)) {
    return null;
  }
  return toLibSpecifier(resolved);
}

function extractRuntimeLibImports(source: string): string[] {
  const imports: string[] = [];
  const importPattern =
    /import\s+(?!type\b)(?:[\s\S]*?\s+from\s+)?["']([^"']+)["']/g;
  for (const match of source.matchAll(importPattern)) {
    const specifier = match[1];
    if (specifier) {
      imports.push(specifier);
    }
  }
  return imports;
}

describe("client/server boundary", () => {
  it("does not reference server secrets from client-oriented modules", () => {
    const files = collectClientOrientedFiles();

    for (const filePath of files) {
      const source = fs.readFileSync(filePath, "utf-8");
      for (const token of DISALLOWED_TOKENS) {
        expect(source).not.toContain(token);
      }
    }
  });

  it("includes client-usable lib modules in the scanned file set", () => {
    const files = collectClientOrientedFiles();

    expect(files).toContain(
      path.resolve(process.cwd(), "src/lib/report-key.ts"),
    );
    expect(files).not.toContain(
      path.resolve(process.cwd(), "src/lib/env.server.ts"),
    );
  });

  it("requires lib wrappers around server-only modules to be server-only too", () => {
    const libFiles = collectTypeScriptFiles(LIB_ROOT);
    const serverOnlySpecifiers = new Set(
      libFiles
        .filter((filePath) =>
          fs.readFileSync(filePath, "utf-8").includes(SERVER_ONLY_TOKEN),
        )
        .map(toLibSpecifier),
    );

    for (const filePath of libFiles) {
      const source = fs.readFileSync(filePath, "utf-8");
      if (source.includes(SERVER_ONLY_TOKEN)) {
        continue;
      }

      for (const specifier of extractRuntimeLibImports(source)) {
        const resolved = resolveLibSpecifier(filePath, specifier);
        expect(
          serverOnlySpecifiers.has(resolved ?? ""),
          `${path.relative(process.cwd(), filePath)} imports server-only ${specifier} without ${SERVER_ONLY_TOKEN}`,
        ).toBe(false);
      }
    }
  });
});
