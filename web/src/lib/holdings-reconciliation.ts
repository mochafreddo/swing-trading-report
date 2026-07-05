import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";

const hasOwn = (value: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(value, key);

export type HoldingReconciliationField =
  | "quantity"
  | "entry_price"
  | "entry_currency"
  | "entry_date"
  | "strategy"
  | "entry_pattern"
  | "notes"
  | "tags"
  | "stop_override"
  | "target_override";

interface HoldingCreateChange {
  ticker: string;
  after: HoldingReplaceSnapshot;
}

interface HoldingUpdateChange {
  ticker: string;
  before: HoldingSnapshot;
  after: HoldingReplaceSnapshot;
  changedFields: HoldingReconciliationField[];
}

interface HoldingDeleteChange {
  ticker: string;
  before: HoldingSnapshot;
}

interface HoldingUnchangedChange {
  ticker: string;
  before: HoldingSnapshot;
  after: HoldingReplaceSnapshot;
}

export interface HoldingsReconciliation {
  summary: HoldingsYamlImportSummary;
  changes: {
    create: HoldingCreateChange[];
    update: HoldingUpdateChange[];
    delete: HoldingDeleteChange[];
    unchanged: HoldingUnchangedChange[];
  };
}

export class HoldingsReconciliationError extends Error {}

function sortHoldingsByTicker<T extends { ticker: string }>(
  rows: readonly T[],
): T[] {
  return [...rows].sort((left, right) =>
    left.ticker.localeCompare(right.ticker),
  );
}

export function toHoldingSnapshot(
  record: HoldingRecord | HoldingSnapshot,
): HoldingSnapshot {
  return {
    ticker: record.ticker,
    quantity: record.quantity,
    entry_price: record.entry_price,
    entry_currency: record.entry_currency ?? null,
    entry_date: record.entry_date ?? null,
    strategy: record.strategy ?? null,
    entry_pattern: record.entry_pattern ?? null,
    notes: record.notes ?? null,
    tags: [...record.tags],
    stop_override: record.stop_override ?? null,
    target_override: record.target_override ?? null,
  };
}

function resolveRightEntryPattern(
  current: HoldingSnapshot,
  incoming: HoldingReplaceSnapshot,
): string | null {
  if (incoming.quantity === 0) {
    return null;
  }
  if (hasOwn(incoming, "entry_pattern")) {
    return incoming.entry_pattern ?? null;
  }
  return current.entry_pattern;
}

function changedFields(
  current: HoldingSnapshot,
  incoming: HoldingReplaceSnapshot,
): HoldingReconciliationField[] {
  const fields: HoldingReconciliationField[] = [];
  if (current.quantity !== incoming.quantity) fields.push("quantity");
  if (current.entry_price !== incoming.entry_price) fields.push("entry_price");
  if (current.entry_currency !== incoming.entry_currency) {
    fields.push("entry_currency");
  }
  if (current.entry_date !== incoming.entry_date) fields.push("entry_date");
  if (current.strategy !== incoming.strategy) fields.push("strategy");
  if (current.entry_pattern !== resolveRightEntryPattern(current, incoming)) {
    fields.push("entry_pattern");
  }
  if (current.notes !== incoming.notes) fields.push("notes");
  if (
    current.tags.length !== incoming.tags.length ||
    current.tags.some((value, index) => value !== incoming.tags[index])
  ) {
    fields.push("tags");
  }
  if (current.stop_override !== incoming.stop_override) {
    fields.push("stop_override");
  }
  if (current.target_override !== incoming.target_override) {
    fields.push("target_override");
  }
  return fields;
}

function assertEntryPatternOwnedForEntryChange(
  current: HoldingSnapshot,
  incoming: HoldingReplaceSnapshot,
): void {
  if (
    current.entry_pattern == null ||
    current.quantity <= 0 ||
    incoming.quantity <= 0 ||
    hasOwn(incoming, "entry_pattern")
  ) {
    return;
  }

  if (
    current.entry_price !== incoming.entry_price ||
    current.entry_date !== incoming.entry_date ||
    current.strategy !== incoming.strategy
  ) {
    throw new HoldingsReconciliationError(
      `${incoming.ticker}: entry_pattern must be explicit when entry identity or strategy changes.`,
    );
  }
}

export function buildHoldingsReconciliation(
  currentHoldings: readonly HoldingRecord[],
  incomingHoldings: readonly HoldingReplaceSnapshot[],
): HoldingsReconciliation {
  const currentByTicker = new Map(
    currentHoldings.map((row) => [row.ticker, toHoldingSnapshot(row)]),
  );
  const incomingByTicker = new Map(
    incomingHoldings.map((row) => [row.ticker, row]),
  );

  const create: HoldingCreateChange[] = [];
  const update: HoldingUpdateChange[] = [];
  const deleted: HoldingDeleteChange[] = [];
  const unchanged: HoldingUnchangedChange[] = [];

  for (const incoming of sortHoldingsByTicker(incomingHoldings)) {
    const current = currentByTicker.get(incoming.ticker);
    if (!current) {
      create.push({ ticker: incoming.ticker, after: incoming });
      continue;
    }
    assertEntryPatternOwnedForEntryChange(current, incoming);
    const fields = changedFields(current, incoming);
    if (fields.length === 0) {
      unchanged.push({
        ticker: incoming.ticker,
        before: current,
        after: incoming,
      });
      continue;
    }
    update.push({
      ticker: incoming.ticker,
      before: current,
      after: incoming,
      changedFields: fields,
    });
  }

  for (const current of sortHoldingsByTicker(currentHoldings)) {
    if (!incomingByTicker.has(current.ticker)) {
      deleted.push({
        ticker: current.ticker,
        before: toHoldingSnapshot(current),
      });
    }
  }

  return {
    summary: {
      incomingCount: incomingHoldings.length,
      createCount: create.length,
      updateCount: update.length,
      deleteCount: deleted.length,
      unchangedCount: unchanged.length,
      createTickers: create.map((row) => row.ticker),
      updateTickers: update.map((row) => row.ticker),
      deleteTickers: deleted.map((row) => row.ticker),
    },
    changes: {
      create,
      update,
      delete: deleted,
      unchanged,
    },
  };
}

export function buildHoldingsReconciliationSummary(
  currentHoldings: readonly HoldingRecord[],
  incomingHoldings: readonly HoldingReplaceSnapshot[],
): HoldingsYamlImportSummary {
  return buildHoldingsReconciliation(currentHoldings, incomingHoldings).summary;
}
