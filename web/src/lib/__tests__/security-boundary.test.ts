import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const CLIENT_ROOTS = [
  path.resolve(process.cwd(), "src/components"),
  path.resolve(process.cwd(), "src/app"),
];

const DISALLOWED_TOKENS = [
  "SUPABASE_SECRET_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "GITHUB_PAT",
  "@/lib/env.server",
];

function collectFiles(root: string, acc: string[] = []): string[] {
  if (!fs.existsSync(root)) {
    return acc;
  }

  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      if (fullPath.includes(`${path.sep}api`)) {
        continue;
      }
      collectFiles(fullPath, acc);
      continue;
    }
    if (entry.name.endsWith(".tsx") || entry.name.endsWith(".ts")) {
      if (entry.name === "route.ts") {
        continue;
      }
      acc.push(fullPath);
    }
  }

  return acc;
}

describe("client/server boundary", () => {
  it("does not reference server secrets from client-oriented modules", () => {
    const files = CLIENT_ROOTS.flatMap((root) => collectFiles(root));

    for (const filePath of files) {
      const source = fs.readFileSync(filePath, "utf-8");
      for (const token of DISALLOWED_TOKENS) {
        expect(source).not.toContain(token);
      }
    }
  });
});
