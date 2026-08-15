import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));

function readJson(relativePath) {
  return JSON.parse(readFileSync(join(projectRoot, relativePath), "utf8"));
}

function readYaml(relativePath) {
  return parse(readFileSync(join(projectRoot, relativePath), "utf8"));
}

function compareSemver(a, b) {
  const left = a.split(".").map((part) => Number.parseInt(part, 10));
  const right = b.split(".").map((part) => Number.parseInt(part, 10));
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const delta = (left[index] ?? 0) - (right[index] ?? 0);
    if (delta !== 0) {
      return delta;
    }
  }
  return 0;
}

function versionFromPackageKey(packageKey) {
  const match = packageKey.match(/@(\d+\.\d+\.\d+)$/);
  return match?.[1] ?? null;
}

function packageVersions(lockfile, packageName) {
  return Object.keys(lockfile.packages ?? {})
    .filter((key) => key.startsWith(`${packageName}@`))
    .map(versionFromPackageKey);
}

function expectPackageVersionsAtLeast(lockfile, packageName, minimumVersion) {
  const versions = packageVersions(lockfile, packageName);
  expect(versions.length).toBeGreaterThan(0);
  for (const version of versions) {
    expect(version).not.toBeNull();
    expect(compareSemver(version, minimumVersion)).toBeGreaterThanOrEqual(0);
  }
}

describe("pnpm dependency overrides", () => {
  it("keeps pnpm overrides at the workspace root and patched versions in the lockfile", () => {
    const packageJson = readJson("package.json");
    const workspace = readYaml("pnpm-workspace.yaml");
    const lockfile = readYaml("pnpm-lock.yaml");

    expect(packageJson.pnpm?.overrides).toBeUndefined();
    expect(workspace.overrides).toEqual({
      "nanoid@<3.3.18": "3.3.18",
      "postcss@<8.5.23": "8.5.23",
      "sharp@<0.35.0": "0.35.0",
      vite: "8.0.16",
    });

    expect(lockfile.overrides).toEqual(workspace.overrides);
    expectPackageVersionsAtLeast(lockfile, "brace-expansion", "1.1.15");
    expectPackageVersionsAtLeast(lockfile, "js-yaml", "4.1.2");
    expectPackageVersionsAtLeast(lockfile, "nanoid", "3.3.18");
    expectPackageVersionsAtLeast(lockfile, "next", "16.2.11");
    expectPackageVersionsAtLeast(lockfile, "postcss", "8.5.23");
    expectPackageVersionsAtLeast(lockfile, "sharp", "0.35.0");
    expectPackageVersionsAtLeast(lockfile, "undici", "7.28.0");
    expectPackageVersionsAtLeast(lockfile, "vite", "8.0.16");
  });
});
