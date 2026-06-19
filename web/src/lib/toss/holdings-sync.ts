import {
  buildHoldingsReconciliation,
  type HoldingsReconciliation,
} from "@/lib/holdings-reconciliation";
import type { HoldingRecord, HoldingReplaceSnapshot } from "@/lib/types";
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

function roundTo(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round((value + Number.EPSILON) * factor) / factor;
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

function findExistingUsTicker(
  symbol: string,
  currentHoldings: readonly HoldingRecord[],
): string | null {
  const matches = currentHoldings
    .map((row) => {
      const match = EXPLICIT_US_SUFFIX_PATTERN.exec(row.ticker);
      return match && match[1] === symbol ? row.ticker : null;
    })
    .filter((ticker): ticker is string => ticker !== null);

  return matches.length === 1 ? matches[0] : null;
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

    const ticker =
      marketCountry === "KR"
        ? item.symbol
        : findExistingUsTicker(item.symbol, input.currentHoldings);
    if (!ticker) {
      blockedRows.push(
        blockedRow(
          item,
          "ticker_exchange_unresolved",
          "Toss returned a US symbol without a safe existing exchange suffix mapping.",
        ),
      );
      continue;
    }

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
