import "server-only";

import { createHash } from "node:crypto";

import { parseDecisionBoardJsonBytes } from "@/lib/decision-board-json";
import { parseHoldingTickerForMutation } from "@/lib/holding-ticker";
import type { TossTickerDirectoryCandidate } from "@/lib/toss/holdings-sync";

const SCHEMA_VERSION = "toss-sync-reviewed-mapping.v1";
const SHA256_PATTERN = /^sha256:[0-9a-f]{64}$/;
const EXPLICIT_US_SUFFIX_PATTERN = /^(.+)\.(NAS|NYS|AMS)$/;
const MIC_TO_SUFFIX = {
  XNAS: "NAS",
  XNYS: "NYS",
  XASE: "AMS",
} as const;
const ROOT_FIELDS = new Set([
  "schema_version",
  "review_state",
  "approved_by",
  "approved_at",
  "mappings",
]);
const ROW_FIELDS = new Set([
  "symbol",
  "repo_ticker",
  "source",
  "primary_exchange_mic",
]);

interface MappingRow {
  symbol?: unknown;
  repo_ticker?: unknown;
  source?: unknown;
  primary_exchange_mic?: unknown;
}

interface MappingPayload {
  schema_version?: unknown;
  review_state?: unknown;
  approved_by?: unknown;
  approved_at?: unknown;
  mappings?: unknown;
}

class TossTickerMappingRegistryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TossTickerMappingRegistryError";
  }
}

function normalizeUsBaseSymbol(value: string): string {
  const normalized = parseHoldingTickerForMutation(`${value.trim()}.NAS`);
  if (normalized === null) {
    return "";
  }
  return EXPLICIT_US_SUFFIX_PATTERN.exec(normalized)?.[1] ?? "";
}

function decodePayload(
  encoded: string,
  expectedSha256: string,
): MappingPayload {
  if (!SHA256_PATTERN.test(expectedSha256)) {
    throw new TossTickerMappingRegistryError(
      "TOSS_SYNC_REVIEWED_MAPPING_SHA256 must be a sha256 digest.",
    );
  }
  const bytes = Buffer.from(encoded, "base64");
  const actualSha256 = `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
  if (actualSha256 !== expectedSha256) {
    throw new TossTickerMappingRegistryError(
      "Reviewed Toss ticker mapping digest mismatch.",
    );
  }

  let parsed: unknown;
  try {
    parsed = parseDecisionBoardJsonBytes(bytes);
  } catch {
    throw new TossTickerMappingRegistryError(
      "Reviewed Toss ticker mapping must be valid strict JSON.",
    );
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new TossTickerMappingRegistryError(
      "Reviewed Toss ticker mapping must be an object.",
    );
  }
  return parsed as MappingPayload;
}

function parseMappings(payload: MappingPayload): Map<string, string> {
  if (Object.keys(payload).some((field) => !ROOT_FIELDS.has(field))) {
    throw new TossTickerMappingRegistryError(
      "Reviewed Toss ticker mapping contains an unsupported field.",
    );
  }
  if (
    payload.schema_version !== SCHEMA_VERSION ||
    payload.review_state !== "APPROVED" ||
    payload.approved_by !== "user" ||
    typeof payload.approved_at !== "string" ||
    !Number.isFinite(Date.parse(payload.approved_at)) ||
    !Array.isArray(payload.mappings)
  ) {
    throw new TossTickerMappingRegistryError(
      "Reviewed Toss ticker mapping approval metadata is invalid.",
    );
  }

  const mappings = new Map<string, string>();
  for (const value of payload.mappings) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping row must be an object.",
      );
    }
    const row = value as MappingRow;
    if (Object.keys(row).some((field) => !ROW_FIELDS.has(field))) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping row contains an unsupported field.",
      );
    }
    if (
      typeof row.symbol !== "string" ||
      typeof row.repo_ticker !== "string" ||
      typeof row.source !== "string"
    ) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping row is incomplete.",
      );
    }
    const symbol = normalizeUsBaseSymbol(row.symbol);
    const ticker = parseHoldingTickerForMutation(row.repo_ticker);
    if (ticker === null) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping symbol and ticker do not match.",
      );
    }
    const match = EXPLICIT_US_SUFFIX_PATTERN.exec(ticker);
    if (!symbol || !match || match[1] !== symbol) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping symbol and ticker do not match.",
      );
    }
    if (
      row.source !== "local_buy_reports" &&
      row.source !== "polygon_reference"
    ) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping has an unsupported evidence source.",
      );
    }
    const mic = row.primary_exchange_mic;
    if (mic !== undefined) {
      if (
        typeof mic !== "string" ||
        MIC_TO_SUFFIX[mic as keyof typeof MIC_TO_SUFFIX] !== match[2]
      ) {
        throw new TossTickerMappingRegistryError(
          "Reviewed Polygon ticker mapping MIC and suffix do not match.",
        );
      }
    }
    if (row.source === "polygon_reference" && mic === undefined) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Polygon ticker mapping MIC and suffix do not match.",
      );
    }
    if (mappings.has(symbol)) {
      throw new TossTickerMappingRegistryError(
        "Reviewed Toss ticker mapping contains a duplicate symbol.",
      );
    }
    mappings.set(symbol, ticker);
  }
  return mappings;
}

export function loadReviewedTossTickerMappingsFromEnv(
  symbols: readonly string[],
): TossTickerDirectoryCandidate[] {
  const encoded = process.env.TOSS_SYNC_REVIEWED_MAPPING_B64?.trim() ?? "";
  const expectedSha256 =
    process.env.TOSS_SYNC_REVIEWED_MAPPING_SHA256?.trim() ?? "";
  if (!encoded && !expectedSha256) {
    return [];
  }
  if (!encoded || !expectedSha256) {
    throw new TossTickerMappingRegistryError(
      "Reviewed Toss ticker mapping payload and digest must be configured together.",
    );
  }

  const mappings = parseMappings(decodePayload(encoded, expectedSha256));
  return Array.from(
    new Set(
      symbols
        .map(normalizeUsBaseSymbol)
        .filter(Boolean)
        .map((symbol) => mappings.get(symbol))
        .filter((ticker): ticker is string => ticker !== undefined),
    ),
  )
    .sort((left, right) => left.localeCompare(right))
    .map((ticker) => ({ ticker }));
}
