import "server-only";

import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, opendir } from "node:fs/promises";
import { isAbsolute, join, parse, resolve, sep } from "node:path";

import { runJournalV0Schema } from "@/lib/decision-board-schema";
import type { DecisionBoardJournalStatus } from "@/lib/types";

const JOURNAL_NAME_PATTERN =
  /^(entry|holding)-(\d{8}T\d{6}Z)-([A-Za-z0-9][A-Za-z0-9_-]{0,127})-([0-9a-f]{16})\.json$/;
const DEFAULT_RECORD_LIMIT = 20;
const MAX_RECORD_LIMIT = 100;
const DEFAULT_SCAN_LIMIT = 200;
const MAX_SCAN_LIMIT = 1000;
const MAX_RECORD_BYTES = 64 * 1024;

function unavailable(
  reason: "NOT_CONFIGURED" | "UNSAFE_OR_INVALID",
): DecisionBoardJournalStatus {
  return { state: "UNAVAILABLE", reason, records: [] };
}

function parseBound(
  value: string | undefined,
  fallback: number,
  maximum: number,
): number {
  if (value === undefined || value === "") {
    return fallback;
  }
  if (!/^\d+$/.test(value)) {
    throw new TypeError("journal bound is invalid");
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > maximum) {
    throw new TypeError("journal bound is invalid");
  }
  return parsed;
}

async function validateDirectoryPath(configuredPath: string) {
  if (
    configuredPath !== configuredPath.trim() ||
    !isAbsolute(configuredPath) ||
    resolve(configuredPath) !== configuredPath ||
    configuredPath === parse(configuredPath).root
  ) {
    throw new TypeError("journal directory is unsafe");
  }

  const effectiveUid = process.geteuid?.();
  if (effectiveUid === undefined) {
    throw new TypeError("journal owner policy is unavailable");
  }
  const validateDirectoryOwner = (
    info: Awaited<ReturnType<typeof lstat>>,
  ): void => {
    const uid = Number(info.uid);
    const mode = Number(info.mode);
    if (uid !== 0 && uid !== effectiveUid) {
      throw new TypeError("journal directory owner is unsafe");
    }
    if ((mode & 0o022) !== 0) {
      const trustedRootSticky = uid === 0 && (mode & 0o1000) !== 0;
      if (!trustedRootSticky) {
        throw new TypeError("journal directory permissions are unsafe");
      }
    }
  };

  const root = parse(configuredPath).root;
  const rootInfo = await lstat(root);
  if (rootInfo.isSymbolicLink() || !rootInfo.isDirectory()) {
    throw new TypeError("journal directory is unsafe");
  }
  validateDirectoryOwner(rootInfo);
  const components = configuredPath
    .slice(root.length)
    .split(sep)
    .filter(Boolean);
  let current = root;
  let finalInfo: Awaited<ReturnType<typeof lstat>> | null = null;
  for (const component of components) {
    current = join(current, component);
    const info = await lstat(current);
    if (info.isSymbolicLink() || !info.isDirectory()) {
      throw new TypeError("journal directory is unsafe");
    }
    validateDirectoryOwner(info);
    finalInfo = info;
  }
  if (
    !finalInfo ||
    (Number(finalInfo.uid) !== 0 && Number(finalInfo.uid) !== effectiveUid) ||
    (Number(finalInfo.mode) & 0o077) !== 0
  ) {
    throw new TypeError("journal directory permissions are unsafe");
  }
  return finalInfo;
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

function expectedStamp(expectedAt: string): string {
  return expectedAt.slice(0, 19).replace(/[-:]/g, "") + "Z";
}

function expectedJournalName(record: {
  run_kind: "ENTRY" | "HOLDING";
  expected_at: string;
  run_id: string;
}): string {
  const identity = `${record.run_kind}\0${record.expected_at}\0${record.run_id}`;
  const digest = createHash("sha256").update(identity, "ascii").digest("hex");
  return `${record.run_kind.toLowerCase()}-${expectedStamp(record.expected_at)}-${record.run_id}-${digest.slice(0, 16)}.json`;
}

async function readJournalRecord(directory: string, name: string) {
  if (!JOURNAL_NAME_PATTERN.test(name)) {
    throw new TypeError("journal record name is invalid");
  }
  const path = join(directory, name);
  const before = await lstat(path);
  const effectiveUid = process.geteuid?.();
  if (
    effectiveUid === undefined ||
    before.isSymbolicLink() ||
    !before.isFile() ||
    (Number(before.uid) !== 0 && Number(before.uid) !== effectiveUid) ||
    before.nlink !== 1 ||
    (before.mode & 0o077) !== 0 ||
    before.size < 2 ||
    before.size > MAX_RECORD_BYTES
  ) {
    throw new TypeError("journal record is unsafe");
  }

  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const opened = await handle.stat();
    if (
      !opened.isFile() ||
      opened.nlink !== 1 ||
      opened.dev !== before.dev ||
      opened.ino !== before.ino ||
      opened.size !== before.size
    ) {
      throw new TypeError("journal record changed");
    }
    const bytes = await handle.readFile();
    const after = await handle.stat();
    if (
      after.dev !== opened.dev ||
      after.ino !== opened.ino ||
      after.size !== opened.size
    ) {
      throw new TypeError("journal record changed");
    }
    const text = bytes.toString("utf8");
    const parsed = runJournalV0Schema.parse(JSON.parse(text) as unknown);
    if (
      Buffer.from(text, "utf8").length !== bytes.length ||
      `${canonicalJson(parsed)}\n` !== text ||
      expectedJournalName(parsed) !== name
    ) {
      throw new TypeError("journal record is noncanonical");
    }
    return parsed;
  } finally {
    await handle.close();
  }
}

async function assertSameDirectory(
  directory: string,
  expected: Awaited<ReturnType<typeof lstat>>,
): Promise<void> {
  const current = await lstat(directory);
  if (
    current.isSymbolicLink() ||
    !current.isDirectory() ||
    current.dev !== expected.dev ||
    current.ino !== expected.ino
  ) {
    throw new TypeError("journal directory changed");
  }
}

export async function readDecisionBoardJournalStatus(): Promise<DecisionBoardJournalStatus> {
  const configuredPath = process.env.DECISION_BOARD_JOURNAL_DIR;
  if (!configuredPath) {
    return unavailable("NOT_CONFIGURED");
  }

  try {
    const limit = parseBound(
      process.env.DECISION_BOARD_JOURNAL_LIMIT,
      DEFAULT_RECORD_LIMIT,
      MAX_RECORD_LIMIT,
    );
    const scanLimit = parseBound(
      process.env.DECISION_BOARD_JOURNAL_SCAN_LIMIT,
      DEFAULT_SCAN_LIMIT,
      MAX_SCAN_LIMIT,
    );
    const before = await validateDirectoryPath(configuredPath);
    const records = [];
    let scannedEntries = 0;
    const directory = await opendir(configuredPath);
    for await (const entry of directory) {
      scannedEntries += 1;
      if (scannedEntries > scanLimit) {
        throw new TypeError("journal scan bound exceeded");
      }
      if (!entry.name.endsWith(".json")) {
        continue;
      }
      if (!entry.isFile() || entry.isSymbolicLink()) {
        throw new TypeError("journal record is unsafe");
      }
      await assertSameDirectory(configuredPath, before);
      records.push(await readJournalRecord(configuredPath, entry.name));
      await assertSameDirectory(configuredPath, before);
    }
    await assertSameDirectory(configuredPath, before);
    const warnings = records
      .filter(
        (record) =>
          record.status === "MISSED_EXPECTED" ||
          record.status === "STALE_INCOMPLETE",
      )
      .sort(
        (left, right) =>
          right.expected_at.localeCompare(left.expected_at) ||
          right.run_kind.localeCompare(left.run_kind) ||
          right.run_id.localeCompare(left.run_id),
      )
      .slice(0, limit);
    return { state: "AVAILABLE", records: warnings };
  } catch {
    return unavailable("UNSAFE_OR_INVALID");
  }
}
