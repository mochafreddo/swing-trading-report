import {
  buildHoldingsReconciliation,
  type HoldingsReconciliation,
} from "@/lib/holdings-reconciliation";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingSnapshot,
} from "@/lib/types";
import { createHash } from "node:crypto";

type TossMarketCountry = "KR" | "US";
type TossCurrency = "KRW" | "USD";

export interface TossHoldingsItem {
  symbol: string;
  name?: string | null;
  marketCountry: string;
  currency: string;
  quantity: string;
  averagePurchasePrice: string;
}

export interface TossTickerDirectoryCandidate {
  ticker: string;
}

export type TossHoldingsBlockedReason =
  | "unknown_market_country"
  | "unknown_currency"
  | "invalid_decimal"
  | "ticker_exchange_unresolved";

export interface TossHoldingsBlockedRow {
  symbol: string;
  marketCountry: string;
  currency: string;
  reason: TossHoldingsBlockedReason;
  message: string;
}

export interface TossHoldingsDryRunInput {
  currentHoldings: readonly HoldingRecord[];
  items: readonly TossHoldingsItem[];
  tickerDirectoryCandidates?: readonly TossTickerDirectoryCandidate[];
}

export interface TossHoldingsDryRunResult {
  targetRows: HoldingReplaceSnapshot[];
  blockedRows: TossHoldingsBlockedRow[];
  applyBlocked: boolean;
  reconciliation: HoldingsReconciliation;
}

const EXPLICIT_US_SUFFIX_PATTERN = /^(.+)\.(NAS|NYS|AMS)$/;
const DECIMAL_TEXT_PATTERN = /^[+-]?(?:\d+\.?\d*|\.\d+)$/;
const QUANTITY_DECIMAL_DIGITS = 6;
const ENTRY_PRICE_DECIMAL_DIGITS = 4;
const BROKER_DIGEST_PREFIX = "broker-holdings-v0;";

const BROKER_SCALAR_FIELDS_BEFORE_TAGS = [
  "ticker",
  "quantity",
  "entry_price",
  "entry_currency",
  "entry_date",
  "strategy",
  "entry_pattern",
  "notes",
] as const;

const BROKER_SCALAR_FIELDS_AFTER_TAGS = [
  "stop_override",
  "target_override",
  "broker_state",
  "broker_missing_first_seen_date",
  "broker_missing_last_seen_date",
  "broker_missing_count",
  "broker_missing_diff_hash",
] as const;

type UsTickerResolution =
  | { status: "matched"; ticker: string }
  | { status: "ambiguous" }
  | { status: "unresolved" };

function roundTo(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round((value + Number.EPSILON) * factor) / factor;
}

function trimAsciiSpace(value: string): string {
  return value.replace(/^ +| +$/g, "");
}

function normalizeDigestText(
  value: string | null | undefined,
  transform?: (text: string) => string,
): string | null {
  if (value == null) return null;
  const trimmed = trimAsciiSpace(value);
  if (!trimmed) return null;
  return transform ? transform(trimmed) : trimmed;
}

function fixedDigestDecimal(value: number, scale: number): string {
  if (!Number.isFinite(value) || value < 0) {
    throw new TypeError("BrokerSnapshotV0 numeric fields must be non-negative");
  }
  return value.toFixed(scale);
}

function compareUtf8(left: string, right: string): number {
  return Buffer.compare(Buffer.from(left, "utf8"), Buffer.from(right, "utf8"));
}

function normalizeBrokerDigestRow(
  row: HoldingSnapshot | HoldingReplaceSnapshot | HoldingRecord,
) {
  return {
    ticker:
      normalizeDigestText(row.ticker, (value) => value.toUpperCase()) ?? "",
    quantity: fixedDigestDecimal(row.quantity, QUANTITY_DECIMAL_DIGITS),
    entry_price: fixedDigestDecimal(
      row.entry_price,
      ENTRY_PRICE_DECIMAL_DIGITS,
    ),
    entry_currency: normalizeDigestText(row.entry_currency, (value) =>
      value.toUpperCase(),
    ),
    entry_date: normalizeDigestText(row.entry_date),
    strategy: normalizeDigestText(row.strategy),
    entry_pattern: normalizeDigestText(row.entry_pattern),
    notes: normalizeDigestText(row.notes),
    tags: row.tags
      .map((tag) => trimAsciiSpace(tag))
      .filter(Boolean)
      .sort(compareUtf8),
    stop_override:
      row.stop_override == null
        ? null
        : fixedDigestDecimal(row.stop_override, ENTRY_PRICE_DECIMAL_DIGITS),
    target_override:
      row.target_override == null
        ? null
        : fixedDigestDecimal(row.target_override, ENTRY_PRICE_DECIMAL_DIGITS),
    broker_state:
      normalizeDigestText(row.broker_state ?? "confirmed", (value) =>
        value.toLowerCase(),
      ) ?? "confirmed",
    broker_missing_first_seen_date: normalizeDigestText(
      row.broker_missing_first_seen_date,
    ),
    broker_missing_last_seen_date: normalizeDigestText(
      row.broker_missing_last_seen_date,
    ),
    broker_missing_count: row.broker_missing_count ?? 0,
    broker_missing_diff_hash: normalizeDigestText(row.broker_missing_diff_hash),
  };
}

function updateCanonicalScalar(
  hash: ReturnType<typeof createHash>,
  value: string | number | null,
): void {
  if (value == null) {
    hash.update("N", "utf8");
    return;
  }
  const text = String(value);
  hash.update(`S${Buffer.byteLength(text, "utf8")}:`, "utf8");
  hash.update(text, "utf8");
}

export function buildBrokerHoldingsDigestV0(
  rows: readonly (HoldingSnapshot | HoldingReplaceSnapshot | HoldingRecord)[],
): string {
  const normalizedRows = rows
    .map(normalizeBrokerDigestRow)
    .sort((left, right) => compareUtf8(left.ticker, right.ticker));
  const hash = createHash("sha256");
  hash.update(BROKER_DIGEST_PREFIX, "utf8");
  for (const row of normalizedRows) {
    hash.update("R", "utf8");
    for (const field of BROKER_SCALAR_FIELDS_BEFORE_TAGS) {
      updateCanonicalScalar(hash, row[field]);
    }
    hash.update(`A${row.tags.length}:`, "utf8");
    for (const tag of row.tags) updateCanonicalScalar(hash, tag);
    for (const field of BROKER_SCALAR_FIELDS_AFTER_TAGS) {
      updateCanonicalScalar(hash, row[field]);
    }
  }
  return `sha256:${hash.digest("hex")}`;
}

function sortByTicker<T extends { ticker: string }>(rows: readonly T[]): T[] {
  return [...rows].sort((left, right) =>
    left.ticker.localeCompare(right.ticker),
  );
}

function parseNonNegativeDecimal(value: string): number | null {
  const text = value.trim();
  if (!DECIMAL_TEXT_PATTERN.test(text)) {
    return null;
  }
  const parsed = Number(text);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

function classifyMarketCountry(value: string): TossMarketCountry | null {
  return value === "KR" || value === "US" ? value : null;
}

function classifyCurrency(value: string): TossCurrency | null {
  return value === "KRW" || value === "USD" ? value : null;
}

function normalizeUsSymbol(value: string): string {
  const trimmed = value.trim();
  const normalizedMaybeTicker = normalizeHoldingTickerForMutation(trimmed);
  const maybeMatch = EXPLICIT_US_SUFFIX_PATTERN.exec(normalizedMaybeTicker);
  if (maybeMatch) {
    return maybeMatch[1] ?? "";
  }

  const normalizedTicker = normalizeHoldingTickerForMutation(`${trimmed}.NAS`);
  const match = EXPLICIT_US_SUFFIX_PATTERN.exec(normalizedTicker);
  return match?.[1] ?? trimmed.toUpperCase();
}

function findExistingUsTicker(
  symbol: string,
  currentHoldings: readonly HoldingRecord[],
): UsTickerResolution {
  const normalizedSymbol = normalizeUsSymbol(symbol);
  const matches = currentHoldings
    .map((row) => {
      const match = EXPLICIT_US_SUFFIX_PATTERN.exec(row.ticker);
      return match && match[1] === normalizedSymbol ? row.ticker : null;
    })
    .filter((ticker): ticker is string => ticker !== null);
  const uniqueMatches = Array.from(new Set(matches));

  if (uniqueMatches.length === 1) {
    return { status: "matched", ticker: uniqueMatches[0] };
  }
  return uniqueMatches.length > 1
    ? { status: "ambiguous" }
    : { status: "unresolved" };
}

function findTickerDirectoryUsTicker(
  symbol: string,
  candidates: readonly TossTickerDirectoryCandidate[] = [],
): UsTickerResolution {
  const normalizedSymbol = normalizeUsSymbol(symbol);
  const matches = candidates
    .map((candidate) => {
      const match = EXPLICIT_US_SUFFIX_PATTERN.exec(candidate.ticker);
      return match && match[1] === normalizedSymbol ? candidate.ticker : null;
    })
    .filter((ticker): ticker is string => ticker !== null);
  const uniqueMatches = Array.from(new Set(matches));

  if (uniqueMatches.length === 1) {
    return { status: "matched", ticker: uniqueMatches[0] };
  }
  return uniqueMatches.length > 1
    ? { status: "ambiguous" }
    : { status: "unresolved" };
}

function resolveUsTicker(
  symbol: string,
  currentHoldings: readonly HoldingRecord[],
  tickerDirectoryCandidates: readonly TossTickerDirectoryCandidate[] = [],
): UsTickerResolution {
  const existing = findExistingUsTicker(symbol, currentHoldings);
  if (existing.status !== "unresolved") {
    return existing;
  }
  return findTickerDirectoryUsTicker(symbol, tickerDirectoryCandidates);
}

function preserveAppOwnedMetadata(
  base: HoldingReplaceSnapshot,
  existing: HoldingRecord | undefined,
): HoldingReplaceSnapshot {
  if (!existing) {
    return base;
  }

  return {
    ...base,
    entry_date: existing.entry_date,
    strategy: existing.strategy,
    entry_pattern: existing.entry_pattern,
    notes: existing.notes,
    tags: [...existing.tags],
    stop_override: existing.stop_override,
    target_override: existing.target_override,
  };
}

function blockedRow(
  item: TossHoldingsItem,
  reason: TossHoldingsBlockedReason,
  message: string,
): TossHoldingsBlockedRow {
  return {
    symbol: item.symbol,
    marketCountry: item.marketCountry,
    currency: item.currency,
    reason,
    message,
  };
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value).sort(([left], [right]) =>
      left.localeCompare(right),
    );
    return Object.fromEntries(
      entries.map(([key, entryValue]) => [key, canonicalize(entryValue)]),
    );
  }
  return value;
}

export function buildTossHoldingsDiffHash(
  dryRun: TossHoldingsDryRunResult,
): string {
  const canonicalPayload = canonicalize({
    applyBlocked: dryRun.applyBlocked,
    blockedRows: dryRun.blockedRows,
    changes: dryRun.reconciliation.changes,
    summary: dryRun.reconciliation.summary,
    targetRows: dryRun.targetRows,
  });
  return `sha256:${createHash("sha256")
    .update(JSON.stringify(canonicalPayload))
    .digest("hex")}`;
}

export function buildTossHoldingsDryRun(
  input: TossHoldingsDryRunInput,
): TossHoldingsDryRunResult {
  const currentByTicker = new Map(
    input.currentHoldings.map((row) => [row.ticker, row]),
  );
  const targetRows: HoldingReplaceSnapshot[] = [];
  const blockedRows: TossHoldingsBlockedRow[] = [];

  for (const item of input.items) {
    const marketCountry = classifyMarketCountry(item.marketCountry);
    if (!marketCountry) {
      blockedRows.push(
        blockedRow(
          item,
          "unknown_market_country",
          "Toss returned an unsupported marketCountry value.",
        ),
      );
      continue;
    }

    const currency = classifyCurrency(item.currency);
    if (!currency) {
      blockedRows.push(
        blockedRow(
          item,
          "unknown_currency",
          "Toss returned an unsupported currency value.",
        ),
      );
      continue;
    }

    const quantity = parseNonNegativeDecimal(item.quantity);
    const entryPrice = parseNonNegativeDecimal(item.averagePurchasePrice);
    if (quantity === null || entryPrice === null) {
      blockedRows.push(
        blockedRow(
          item,
          "invalid_decimal",
          "Toss returned a quantity or average purchase price that could not be parsed.",
        ),
      );
      continue;
    }

    const tickerResolution =
      marketCountry === "KR"
        ? ({
            status: "matched",
            ticker: item.symbol,
          } satisfies UsTickerResolution)
        : resolveUsTicker(
            item.symbol,
            input.currentHoldings,
            input.tickerDirectoryCandidates,
          );
    if (tickerResolution.status !== "matched") {
      blockedRows.push(
        blockedRow(
          item,
          "ticker_exchange_unresolved",
          "Toss returned a US symbol without a safe existing exchange suffix mapping.",
        ),
      );
      continue;
    }
    const ticker = tickerResolution.ticker;

    targetRows.push(
      preserveAppOwnedMetadata(
        {
          ticker,
          quantity: roundTo(quantity, QUANTITY_DECIMAL_DIGITS),
          entry_price: roundTo(entryPrice, ENTRY_PRICE_DECIMAL_DIGITS),
          entry_currency:
            marketCountry === "KR" && currency === "KRW" ? null : currency,
          entry_date: null,
          strategy: null,
          entry_pattern: null,
          notes: null,
          tags: [],
          stop_override: null,
          target_override: null,
        },
        currentByTicker.get(ticker),
      ),
    );
  }

  const sortedTargetRows = sortByTicker(targetRows);
  return {
    targetRows: sortedTargetRows,
    blockedRows,
    applyBlocked: blockedRows.length > 0,
    reconciliation: buildHoldingsReconciliation(
      input.currentHoldings,
      sortedTargetRows,
    ),
  };
}
