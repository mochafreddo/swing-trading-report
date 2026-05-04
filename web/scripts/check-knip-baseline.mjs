import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const baselinePath = join(projectRoot, "knip-baseline.json");
const issueTypes = [
  "binaries",
  "catalog",
  "dependencies",
  "devDependencies",
  "duplicates",
  "enumMembers",
  "exports",
  "files",
  "namespaceMembers",
  "optionalPeerDependencies",
  "types",
  "unlisted",
  "unresolved",
];

function normalizeIssue(issue, type, item) {
  const name = item.name ?? item.specifier ?? item;
  return `${type}:${issue.file}:${name}`;
}

function normalizeIssues(report) {
  const keys = [];
  for (const issue of report.issues ?? []) {
    for (const type of issueTypes) {
      for (const item of issue[type] ?? []) {
        keys.push(normalizeIssue(issue, type, item));
      }
    }
  }
  return [...new Set(keys)].sort();
}

function readBaseline() {
  const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
  return [...new Set(baseline.knownIssues ?? [])].sort();
}

const result = spawnSync("knip", ["--no-progress", "--reporter", "json"], {
  cwd: projectRoot,
  encoding: "utf8",
});

let report;
try {
  report = JSON.parse(result.stdout);
} catch {
  process.stdout.write(result.stdout);
  process.stderr.write(result.stderr);
  process.stderr.write("Failed to parse knip JSON output.\n");
  process.exit(result.status ?? 1);
}

const baseline = readBaseline();
const baselineSet = new Set(baseline);
const current = normalizeIssues(report);
const newIssues = current.filter((issue) => !baselineSet.has(issue));
const resolvedIssues = baseline.filter((issue) => !current.includes(issue));

if (newIssues.length > 0) {
  console.error(`Knip found ${newIssues.length} new dead-code issue(s):`);
  for (const issue of newIssues) {
    console.error(`  ${issue}`);
  }
  process.exit(1);
}

console.log(
  `Knip baseline OK: ${current.length}/${baseline.length} known issue(s).`,
);
if (resolvedIssues.length > 0) {
  console.log(`${resolvedIssues.length} baseline issue(s) are now resolved.`);
  console.log("Update web/knip-baseline.json to lower the baseline.");
}
