import {
  accessSync,
  chmodSync,
  constants,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { execFileSync } from "node:child_process";

import { afterEach, describe, expect, it, vi } from "vitest";

import { readDecisionBoardJournalStatus } from "@/lib/decision-board-journal.server";

const roots: string[] = [];
const repositoryRoot = resolve(process.cwd(), "..");

function resolvePythonExecutable(): string {
  const name = process.platform === "win32" ? "python.exe" : "python";
  for (const directory of process.env.PATH?.split(delimiter) ?? []) {
    if (!directory) continue;
    const candidate = resolve(directory, name);
    try {
      accessSync(candidate, constants.X_OK);
      return candidate;
    } catch {
      continue;
    }
  }
  throw new Error("python executable is unavailable on PATH");
}

const pythonExecutable = resolvePythonExecutable();
const journalHelper = resolve(
  repositoryRoot,
  "sab/decision_board/run_journal_public.py",
);

function createRoot(): string {
  const parent = process.platform === "darwin" ? "/private/tmp" : tmpdir();
  const root = mkdtempSync(join(parent, "decision-board-journal-bridge-"));
  chmodSync(root, 0o700);
  roots.push(root);
  return root;
}

function configure(
  root: string,
  helper = journalHelper,
  executable = pythonExecutable,
): void {
  vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);
  vi.stubEnv("DECISION_BOARD_JOURNAL_PYTHON", executable);
  vi.stubEnv("DECISION_BOARD_JOURNAL_HELPER", helper);
}

function writeWithT9(root: string): void {
  execFileSync(
    pythonExecutable,
    [
      "-c",
      [
        "from datetime import UTC, datetime",
        "from sab.decision_board.run_journal import RunJournalStoreV0",
        "from sab.decision_board.runner import RunKindV0",
        `RunJournalStoreV0(${JSON.stringify(root)}).claim(`,
        "run_kind=RunKindV0.ENTRY,",
        "expected_at=datetime(2026, 8, 11, 1, 0, tzinfo=UTC),",
        "run_id='entry-t9-web-compat',",
        "observed_at=datetime(2026, 8, 11, 1, 2, tzinfo=UTC),",
        "grace_seconds=60, stale_seconds=300)",
      ].join("\n"),
    ],
    {
      cwd: repositoryRoot,
      env: { ...process.env, PYTHONPATH: repositoryRoot },
    },
  );
}

function fakeHelper(source: string): string {
  const root = createRoot();
  const path = join(root, "helper.mjs");
  writeFileSync(path, source, { mode: 0o700 });
  chmodSync(path, 0o700);
  return path;
}

afterEach(() => {
  vi.unstubAllEnvs();
  for (const root of roots.splice(0))
    rmSync(root, { recursive: true, force: true });
});

describe("Decision Board T9 journal subprocess bridge", () => {
  it("returns an explicit unavailable state when not configured", async () => {
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", "");
    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "NOT_CONFIGURED",
      records: [],
    });
  });

  it("reads a warning written by the authoritative T9 writer", async () => {
    const root = createRoot();
    writeWithT9(root);
    configure(root);

    await expect(readDecisionBoardJournalStatus()).resolves.toMatchObject({
      state: "AVAILABLE",
      records: [{ run_id: "entry-t9-web-compat", status: "MISSED_EXPECTED" }],
    });
  });

  it("fails closed on subprocess failure without leaking stderr", async () => {
    const helper = fakeHelper(
      "process.stderr.write('PRIVATE-PATH-TOKEN'); process.exit(2);",
    );
    configure(dirname(helper), helper, process.execPath);
    expect(
      JSON.stringify(await readDecisionBoardJournalStatus()),
    ).not.toContain("PRIVATE-PATH-TOKEN");
    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("fails closed on timeout", async () => {
    const helper = fakeHelper("setInterval(() => {}, 1000);");
    configure(dirname(helper), helper, process.execPath);
    vi.stubEnv("DECISION_BOARD_JOURNAL_TIMEOUT_MS", "50");
    await expect(readDecisionBoardJournalStatus()).resolves.toMatchObject({
      state: "UNAVAILABLE",
    });
  });

  it("fails closed on oversized or invalid stdout", async () => {
    const helper = fakeHelper("process.stdout.write('x'.repeat(300000));");
    configure(dirname(helper), helper, process.execPath);
    vi.stubEnv("DECISION_BOARD_JOURNAL_MAX_OUTPUT_BYTES", "1024");
    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });
});
