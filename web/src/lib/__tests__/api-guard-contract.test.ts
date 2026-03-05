import fs from "node:fs";
import path from "node:path";

import { describe, it } from "vitest";

const API_ROOT = path.resolve(process.cwd(), "src/app/api");
const PUBLIC_ROUTES = new Set(["auth/login/route.ts", "auth/logout/route.ts"]);
const ADMIN_GUARD_CALL = "enforceAdminApiGuard(";
const GUARDED_PASSTHROUGH_ROUTES = new Map<string, string>([
  ["holdings/[...ticker]/route.ts", 'from "../[ticker]/route"'],
  [
    "holdings/add-buy/[...ticker]/route.ts",
    'from "../../[ticker]/add-buy/route"',
  ],
]);

function collectApiRouteFiles(root: string, acc: string[] = []): string[] {
  if (!fs.existsSync(root)) {
    return acc;
  }

  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__") {
        continue;
      }
      collectApiRouteFiles(fullPath, acc);
      continue;
    }
    if (entry.name === "route.ts") {
      acc.push(fullPath);
    }
  }

  return acc;
}

function normalizeRelativePath(filePath: string): string {
  return path.relative(API_ROOT, filePath).split(path.sep).join("/");
}

describe("api guard contract", () => {
  it("requires admin-api-guard for protected API routes", () => {
    const routeFiles = collectApiRouteFiles(API_ROOT);

    for (const filePath of routeFiles) {
      const relative = normalizeRelativePath(filePath);
      if (PUBLIC_ROUTES.has(relative)) {
        continue;
      }
      const source = fs.readFileSync(filePath, "utf8");
      const expectedDelegateImport = GUARDED_PASSTHROUGH_ROUTES.get(relative);
      if (expectedDelegateImport) {
        if (!source.includes(expectedDelegateImport)) {
          throw new Error(
            `${relative} must delegate to guarded route via ${expectedDelegateImport}`,
          );
        }
        continue;
      }
      if (!source.includes(ADMIN_GUARD_CALL)) {
        throw new Error(
          `${relative} must call enforceAdminApiGuard() for /api protection`,
        );
      }
    }
  });
});
