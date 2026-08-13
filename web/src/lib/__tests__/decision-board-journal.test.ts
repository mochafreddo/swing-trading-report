import { createHash } from "node:crypto";
import {
  chmodSync,
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  renameSync,
  rmSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { readDecisionBoardJournalStatus } from "@/lib/decision-board-journal.server";

const roots: string[] = [];

function createJournalRoot(): string {
  const safeTemporaryParent =
    process.platform === "darwin" ? "/private/tmp" : tmpdir();
  const root = mkdtempSync(
    join(safeTemporaryParent, "decision-board-journal-test-"),
  );
  chmodSync(root, 0o700);
  const resolved = realpathSync(root);
  roots.push(resolved);
  return resolved;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(",")}}`;
}

function journalName(record: Record<string, unknown>): string {
  const expectedAt = String(record.expected_at);
  const stamp = expectedAt.replace(/[-:]/g, "").replace(".000000", "");
  const identity = `${record.run_kind}\0${expectedAt}\0${record.run_id}`;
  const digest = createHash("sha256").update(identity, "ascii").digest("hex");
  return `${String(record.run_kind).toLowerCase()}-${stamp}-${record.run_id}-${digest.slice(0, 16)}.json`;
}

function warningRecord(
  status: "MISSED_EXPECTED" | "STALE_INCOMPLETE",
  expectedAt: string,
  runId: string,
): Record<string, unknown> {
  const stale = status === "STALE_INCOMPLETE";
  return {
    schema_version: "decision-board.v0",
    run_id: runId,
    run_kind: "ENTRY",
    status,
    expected_at: expectedAt,
    started_at: stale ? expectedAt : null,
    terminal_at: "2026-08-11T02:00:00Z",
    grace_seconds: 60,
    stale_seconds: 300,
    issues: [
      {
        code: status,
        message: stale
          ? "Started run did not reach a terminal state before its TTL."
          : "Expected run did not start before its grace deadline.",
      },
    ],
    report_file: null,
  };
}

function writeCanonicalRecord(
  root: string,
  record: Record<string, unknown>,
): string {
  const path = join(root, journalName(record));
  writeFileSync(path, `${canonicalJson(record)}\n`, { mode: 0o600 });
  chmodSync(path, 0o600);
  return path;
}

afterEach(() => {
  vi.unstubAllEnvs();
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("Decision Board local journal reader", () => {
  it("returns an explicit unavailable state when not configured", async () => {
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", "");

    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "NOT_CONFIGURED",
      records: [],
    });
  });

  it("returns only bounded missed/stale records in newest-first order", async () => {
    const root = createJournalRoot();
    const older = warningRecord(
      "MISSED_EXPECTED",
      "2026-08-11T00:00:00Z",
      "entry-slot-old",
    );
    const newer = warningRecord(
      "STALE_INCOMPLETE",
      "2026-08-11T01:00:00Z",
      "entry-slot-new",
    );
    writeCanonicalRecord(root, older);
    writeCanonicalRecord(root, newer);
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);
    vi.stubEnv("DECISION_BOARD_JOURNAL_LIMIT", "1");

    const status = await readDecisionBoardJournalStatus();

    expect(status).toEqual({
      state: "AVAILABLE",
      records: [newer],
    });
    expect(JSON.stringify(status)).not.toContain(root);
  });

  it("fails closed without leaking malformed journal bytes", async () => {
    const root = createJournalRoot();
    const record = warningRecord(
      "MISSED_EXPECTED",
      "2026-08-11T00:00:00Z",
      "entry-slot-private",
    );
    record.account_id = "PRIVATE-SENTINEL";
    writeCanonicalRecord(root, record);
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);

    const status = await readDecisionBoardJournalStatus();

    expect(status).toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
    expect(JSON.stringify(status)).not.toContain("PRIVATE-SENTINEL");
    expect(JSON.stringify(status)).not.toContain(root);
  });

  it("rejects symlinked journal files", async () => {
    const root = createJournalRoot();
    const external = createJournalRoot();
    const record = warningRecord(
      "STALE_INCOMPLETE",
      "2026-08-11T01:00:00Z",
      "entry-slot-link",
    );
    const target = writeCanonicalRecord(external, record);
    symlinkSync(target, join(root, journalName(record)));
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);

    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("rejects a user-owned writable ancestor even when the final directory is private", async () => {
    const ancestor = createJournalRoot();
    const root = join(ancestor, "journal");
    mkdirSync(root, { mode: 0o700 });
    chmodSync(root, 0o700);
    chmodSync(ancestor, 0o770);
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);

    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("rejects a user-owned non-final ancestor even when it is not group writable", async () => {
    const ancestor = createJournalRoot();
    const root = join(ancestor, "journal");
    mkdirSync(root, { mode: 0o700 });
    chmodSync(root, 0o700);
    chmodSync(ancestor, 0o700);
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);

    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("applies the scan cap to all directory entries", async () => {
    const root = createJournalRoot();
    writeFileSync(join(root, "ignored-a.txt"), "a", { mode: 0o600 });
    writeFileSync(join(root, "ignored-b.txt"), "b", { mode: 0o600 });
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);
    vi.stubEnv("DECISION_BOARD_JOURNAL_SCAN_LIMIT", "1");

    await expect(readDecisionBoardJournalStatus()).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("fails closed when the configured directory is swapped during file open", async () => {
    const root = createJournalRoot();
    const replacement = createJournalRoot();
    const displaced = `${root}-displaced`;
    const record = warningRecord(
      "STALE_INCOMPLETE",
      "2026-08-11T01:00:00Z",
      "entry-slot-swap",
    );
    writeCanonicalRecord(root, record);
    writeCanonicalRecord(replacement, record);
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);
    roots.push(displaced);

    const statusPromise = readDecisionBoardJournalStatus();
    renameSync(root, displaced);
    symlinkSync(replacement, root);
    const status = await statusPromise;

    expect(status).toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("fails closed when the configured directory is swapped and restored", async () => {
    const root = createJournalRoot();
    const replacement = createJournalRoot();
    const displaced = `${root}-displaced`;
    for (let index = 0; index < 100; index += 1) {
      const expectedAt = `2026-08-11T01:${String(index).padStart(2, "0")}:00Z`;
      writeCanonicalRecord(
        root,
        warningRecord(
          "STALE_INCOMPLETE",
          expectedAt,
          `entry-slot-swap-back-${index}`,
        ),
      );
    }
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);

    const statusPromise = readDecisionBoardJournalStatus();
    await new Promise<void>((resolvePromise) => setTimeout(resolvePromise, 2));
    renameSync(root, displaced);
    renameSync(replacement, root);
    renameSync(root, replacement);
    renameSync(displaced, root);

    await expect(statusPromise).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });

  it("fails closed when a journal record grows while it is being read", async () => {
    const root = createJournalRoot();
    const record = warningRecord(
      "STALE_INCOMPLETE",
      "2026-08-11T01:00:00Z",
      "entry-slot-growth",
    );
    record.issues = [
      {
        code: "STALE_INCOMPLETE",
        message: "x".repeat(60 * 1024),
      },
    ];
    const path = writeCanonicalRecord(root, record);
    vi.stubEnv("DECISION_BOARD_JOURNAL_DIR", root);

    const statusPromise = readDecisionBoardJournalStatus();
    appendFileSync(path, "x".repeat(8 * 1024));

    await expect(statusPromise).resolves.toEqual({
      state: "UNAVAILABLE",
      reason: "UNSAFE_OR_INVALID",
      records: [],
    });
  });
});
