import "server-only";

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { isAbsolute, resolve } from "node:path";

import { z } from "zod";

import { runJournalV0Schema } from "@/lib/decision-board-schema";
import type { DecisionBoardJournalStatus } from "@/lib/types";

const execFileAsync = promisify(execFile);
const DEFAULT_RECORD_LIMIT = 20;
const MAX_RECORD_LIMIT = 100;
const DEFAULT_SCAN_LIMIT = 200;
const MAX_SCAN_LIMIT = 1000;
const DEFAULT_RECORD_BYTES = 64 * 1024;
const MAX_RECORD_BYTES = 1024 * 1024;
const DEFAULT_OUTPUT_BYTES = 256 * 1024;
const MAX_OUTPUT_BYTES = 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 1500;
const MAX_TIMEOUT_MS = 10_000;

const helperEnvelopeSchema = z
  .object({
    count: z.number().int().nonnegative().max(MAX_RECORD_LIMIT),
    records: z.array(runJournalV0Schema).max(MAX_RECORD_LIMIT),
  })
  .strict()
  .refine((value) => value.count === value.records.length, {
    path: ["count"],
    message: "count must equal records length",
  });

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
  if (value === undefined || value === "") return fallback;
  if (!/^\d+$/u.test(value)) throw new TypeError("journal bound is invalid");
  const parsed = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > maximum) {
    throw new TypeError("journal bound is invalid");
  }
  return parsed;
}

function exactAbsolutePath(
  value: string | undefined,
  fallback: string,
): string {
  const selected = value ?? fallback;
  if (
    selected === "" ||
    selected !== selected.trim() ||
    !isAbsolute(selected) ||
    resolve(selected) !== selected
  ) {
    throw new TypeError("journal subprocess path is invalid");
  }
  return selected;
}

export async function readDecisionBoardJournalStatus(): Promise<DecisionBoardJournalStatus> {
  const journalDir = process.env.DECISION_BOARD_JOURNAL_DIR;
  if (!journalDir) return unavailable("NOT_CONFIGURED");

  try {
    const repositoryRoot = resolve(process.cwd(), "..");
    const python = exactAbsolutePath(
      process.env.DECISION_BOARD_JOURNAL_PYTHON,
      resolve(repositoryRoot, ".venv/bin/python"),
    );
    const helper = exactAbsolutePath(
      process.env.DECISION_BOARD_JOURNAL_HELPER,
      resolve(repositoryRoot, "sab/decision_board/run_journal_public.py"),
    );
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
    const recordBytes = parseBound(
      process.env.DECISION_BOARD_JOURNAL_MAX_RECORD_BYTES,
      DEFAULT_RECORD_BYTES,
      MAX_RECORD_BYTES,
    );
    const outputBytes = parseBound(
      process.env.DECISION_BOARD_JOURNAL_MAX_OUTPUT_BYTES,
      DEFAULT_OUTPUT_BYTES,
      MAX_OUTPUT_BYTES,
    );
    const timeout = parseBound(
      process.env.DECISION_BOARD_JOURNAL_TIMEOUT_MS,
      DEFAULT_TIMEOUT_MS,
      MAX_TIMEOUT_MS,
    );
    const { stdout } = await execFileAsync(
      python,
      [
        helper,
        "--journal-dir",
        journalDir,
        "--limit",
        String(limit),
        "--scan-limit",
        String(scanLimit),
        "--max-record-bytes",
        String(recordBytes),
        "--max-output-bytes",
        String(outputBytes),
        "--status",
        "MISSED_EXPECTED",
        "--status",
        "STALE_INCOMPLETE",
      ],
      {
        encoding: "utf8",
        timeout,
        maxBuffer: outputBytes,
        windowsHide: true,
        shell: false,
      },
    );
    if (Buffer.byteLength(stdout, "utf8") > outputBytes) {
      throw new TypeError("journal output is oversized");
    }
    const envelope = helperEnvelopeSchema.parse(JSON.parse(stdout) as unknown);
    return { state: "AVAILABLE", records: envelope.records };
  } catch {
    return unavailable("UNSAFE_OR_INVALID");
  }
}
