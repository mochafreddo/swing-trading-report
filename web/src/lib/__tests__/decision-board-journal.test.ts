import { createHash } from "node:crypto";
import {
  chmodSync,
  mkdtempSync,
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
  const root = mkdtempSync(join(tmpdir(), "decision-board-journal-test-"));
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
});
