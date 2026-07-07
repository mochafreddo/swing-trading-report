import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

import {
  HOLDING_ENTRY_PATTERN_VALUES,
  isHoldingEntryPattern,
} from "@/lib/holding-entry-pattern";
import {
  KR_TICKER_PATTERN,
  normalizeHoldingTickerForMutation,
  US_TICKER_PATTERN,
} from "@/lib/holding-ticker";
import {
  buildHoldingsReconciliationSummary,
  HoldingsReconciliationError,
  toHoldingSnapshot,
} from "@/lib/holdings-reconciliation";
import { isValidIsoCalendarDate } from "@/lib/iso-calendar-date";
import { hasOwn } from "@/lib/object-utils";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";

const SUPPORTED_ENTRY_CURRENCIES = new Set(["KRW", "USD"]);
const NUMERIC_TEXT_PATTERN = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;
export const MAX_HOLDINGS_YAML_DOCUMENT_BYTES = 1_048_576;
export const MAX_HOLDINGS_YAML_ROW_COUNT = 1_000;

interface HoldingsYamlSettings {
  default_currency: string | null;
  default_strategy: string | null;
  default_tags: string[];
}

interface HoldingsYamlDocumentShape {
  version: 1;
  holdings: HoldingSnapshot[];
}

type RootRecord = Record<string, unknown>;

export class HoldingsYamlError extends Error {}

function asRecord(value: unknown): RootRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as RootRecord;
}

function sortHoldingsByTicker<T extends { ticker: string }>(
  rows: readonly T[],
): T[] {
  return [...rows].sort((left, right) =>
    left.ticker.localeCompare(right.ticker),
  );
}

function normalizeStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry).trim()).filter(Boolean);
  }
  if (value == null) {
    return [];
  }
  const text = String(value).trim();
  return text ? [text] : [];
}

function parseNonNegativeNumber(
  value: unknown,
  fieldName: string,
  context: string,
): number {
  if (typeof value === "boolean") {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be a finite number >= 0.`,
    );
  }

  let parsed: number;
  if (typeof value === "number") {
    parsed = value;
  } else if (typeof value === "string") {
    const text = value.trim();
    if (!NUMERIC_TEXT_PATTERN.test(text)) {
      throw new HoldingsYamlError(
        `${context}: '${fieldName}' must be a finite number >= 0.`,
      );
    }
    parsed = Number(text);
  } else {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be a finite number >= 0.`,
    );
  }

  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be a finite number >= 0.`,
    );
  }

  return parsed;
}

function parseOptionalNonNegativeNumber(
  value: unknown,
  fieldName: string,
  context: string,
): number | null {
  if (value == null) {
    return null;
  }
  return parseNonNegativeNumber(value, fieldName, context);
}

function parseOptionalText(value: unknown): string | null {
  if (value == null) {
    return null;
  }
  const text = String(value).trim();
  if (!text) {
    return null;
  }
  return text;
}

function parseOptionalEntryPattern(
  value: unknown,
  fieldName: string,
  context: string,
): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be a string or null.`,
    );
  }
  const text = value.trim();
  if (!text) {
    return null;
  }
  if (text.length > 120) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be <= 120 chars.`,
    );
  }
  if (!isHoldingEntryPattern(text)) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be one of ${HOLDING_ENTRY_PATTERN_VALUES.join(", ")}.`,
    );
  }
  return text;
}

function parseOptionalCurrency(
  value: unknown,
  fieldName: string,
  context: string,
): string | null {
  if (value == null) {
    return null;
  }
  if (typeof value === "boolean") {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be one of KRW, USD.`,
    );
  }
  const text = String(value).trim().toUpperCase();
  if (!text) {
    return null;
  }
  if (!SUPPORTED_ENTRY_CURRENCIES.has(text)) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be one of KRW, USD.`,
    );
  }
  return text;
}

function parseOptionalDate(
  value: unknown,
  fieldName: string,
  context: string,
): string | null {
  if (value == null) {
    return null;
  }

  let text = "";
  if (value instanceof Date) {
    text = value.toISOString().slice(0, 10);
  } else {
    text = String(value).trim();
  }

  if (!text) {
    return null;
  }
  if (!isValidIsoCalendarDate(text)) {
    throw new HoldingsYamlError(
      `${context}: '${fieldName}' must be a valid YYYY-MM-DD date.`,
    );
  }
  return text;
}

function parseTicker(value: unknown, context: string): string {
  if (typeof value !== "string") {
    if (typeof value === "number" && Number.isInteger(value)) {
      throw new HoldingsYamlError(
        `${context}: 'ticker' must be a quoted string. Quote numeric KR codes to preserve leading zeros.`,
      );
    }
    throw new HoldingsYamlError(
      `${context}: 'ticker' must be a non-empty string.`,
    );
  }

  const normalized = normalizeHoldingTickerForMutation(
    value.trim().toUpperCase(),
  );
  if (
    KR_TICKER_PATTERN.test(normalized) ||
    US_TICKER_PATTERN.test(normalized)
  ) {
    return normalized;
  }
  if (/^[A-Z][A-Z0-9]*(?:[/.][A-Z0-9]+)?\.US$/i.test(value.trim())) {
    throw new HoldingsYamlError(
      `${context}: 'ticker' must use an explicit US exchange suffix (NAS, NYS, AMS).`,
    );
  }
  throw new HoldingsYamlError(
    `${context}: 'ticker' must be a KR 6-digit code or a US symbol with exchange suffix.`,
  );
}

function resolveMarket(ticker: string): "KR" | "US" {
  return KR_TICKER_PATTERN.test(ticker) ? "KR" : "US";
}

function resolveExplicitExportCurrency(snapshot: HoldingSnapshot): string {
  if (snapshot.entry_currency) {
    return snapshot.entry_currency;
  }
  return resolveMarket(snapshot.ticker) === "US" ? "USD" : "KRW";
}

function normalizeSettings(root: RootRecord): HoldingsYamlSettings {
  const settingsValue = root.settings;
  if (settingsValue == null) {
    return {
      default_currency: null,
      default_strategy: null,
      default_tags: [],
    };
  }

  const settings = asRecord(settingsValue);
  if (!settings) {
    throw new HoldingsYamlError("'settings' must be a mapping object.");
  }

  return {
    default_currency: parseOptionalCurrency(
      settings.default_currency,
      "settings.default_currency",
      "settings",
    ),
    default_strategy: parseOptionalText(settings.default_strategy),
    default_tags: normalizeStringList(settings.default_tags),
  };
}

function buildYamlRow(snapshot: HoldingSnapshot): RootRecord {
  const row: RootRecord = {
    ticker: snapshot.ticker,
    quantity: snapshot.quantity,
    entry_price: snapshot.entry_price,
    entry_currency: resolveExplicitExportCurrency(snapshot),
  };
  if (snapshot.entry_date) {
    row.entry_date = snapshot.entry_date;
  }
  if (snapshot.strategy) {
    row.strategy = snapshot.strategy;
  }
  row.entry_pattern = snapshot.entry_pattern ?? null;
  if (snapshot.notes) {
    row.notes = snapshot.notes;
  }
  if (snapshot.tags.length > 0) {
    row.tags = [...snapshot.tags];
  }
  if (snapshot.stop_override != null) {
    row.stop_override = snapshot.stop_override;
  }
  if (snapshot.target_override != null) {
    row.target_override = snapshot.target_override;
  }

  return row;
}

export function buildHoldingsYamlDocument(
  holdings: readonly HoldingSnapshot[],
): string {
  const payload: HoldingsYamlDocumentShape = {
    version: 1,
    holdings: sortHoldingsByTicker(holdings).map((row) =>
      toHoldingSnapshot(row),
    ),
  };

  return stringifyYaml(
    {
      version: payload.version,
      holdings: payload.holdings.map((row) => buildYamlRow(row)),
    },
    {
      lineWidth: 0,
    },
  );
}

export function parseHoldingsYamlDocument(
  document: string,
): HoldingReplaceSnapshot[] {
  const byteLength = new TextEncoder().encode(document).byteLength;
  if (byteLength > MAX_HOLDINGS_YAML_DOCUMENT_BYTES) {
    throw new HoldingsYamlError(
      `holdings.yaml document must be <= ${MAX_HOLDINGS_YAML_DOCUMENT_BYTES} bytes.`,
    );
  }

  let raw: unknown;
  try {
    raw = parseYaml(document);
  } catch (error) {
    throw new HoldingsYamlError(
      error instanceof Error
        ? `Failed to parse holdings YAML: ${error.message}`
        : "Failed to parse holdings YAML.",
    );
  }

  const root = asRecord(raw);
  if (!root) {
    throw new HoldingsYamlError("holdings.yaml root must be a mapping object.");
  }

  if (root.version != null && root.version !== 1) {
    throw new HoldingsYamlError("'version' must be 1 when provided.");
  }

  const settings = normalizeSettings(root);
  const holdingsValue = root.holdings;
  if (!Array.isArray(holdingsValue)) {
    throw new HoldingsYamlError("'holdings' must be an array.");
  }
  if (holdingsValue.length > MAX_HOLDINGS_YAML_ROW_COUNT) {
    throw new HoldingsYamlError(
      `holdings.yaml supports at most ${MAX_HOLDINGS_YAML_ROW_COUNT} holdings.`,
    );
  }

  const preliminaryRows = holdingsValue.map((value, index) => {
    const context = `holdings[${index}]`;
    const row = asRecord(value);
    if (!row) {
      throw new HoldingsYamlError(`${context} must be an object.`);
    }
    const ticker = parseTicker(row.ticker, context);
    return {
      index,
      context,
      row,
      ticker,
      market: resolveMarket(ticker),
    };
  });

  const hasKrTicker = preliminaryRows.some((entry) => entry.market === "KR");
  const hasUsTicker = preliminaryRows.some((entry) => entry.market === "US");
  const mixedMarkets = hasKrTicker && hasUsTicker;

  if (mixedMarkets && settings.default_currency) {
    throw new HoldingsYamlError(
      "Mixed KR/US holdings cannot use settings.default_currency; set entry_currency per row.",
    );
  }
  if (
    hasUsTicker &&
    !hasKrTicker &&
    settings.default_currency &&
    settings.default_currency !== "USD"
  ) {
    throw new HoldingsYamlError(
      "US-only holdings require settings.default_currency to be USD or unset.",
    );
  }
  if (hasKrTicker && !hasUsTicker && settings.default_currency === "USD") {
    throw new HoldingsYamlError(
      "KR-only holdings cannot set settings.default_currency=USD.",
    );
  }

  const snapshots = preliminaryRows.map(({ context, row, ticker, market }) => {
    const quantity = parseNonNegativeNumber(row.quantity, "quantity", context);
    const entryPrice = parseNonNegativeNumber(
      row.entry_price,
      "entry_price",
      context,
    );
    if (quantity > 0 && entryPrice <= 0) {
      throw new HoldingsYamlError(
        `${context}: 'entry_price' must be > 0 when quantity > 0.`,
      );
    }

    const explicitCurrency = parseOptionalCurrency(
      row.entry_currency,
      "entry_currency",
      context,
    );
    const entryCurrency = explicitCurrency ?? settings.default_currency ?? null;

    if (mixedMarkets && !explicitCurrency) {
      throw new HoldingsYamlError(
        `${context}: mixed KR/US holdings require explicit 'entry_currency' per row.`,
      );
    }
    if (market === "US" && entryCurrency !== "USD") {
      throw new HoldingsYamlError(
        `${context}: US ticker entry_currency must be USD.`,
      );
    }
    if (market === "KR" && entryCurrency === "USD") {
      throw new HoldingsYamlError(
        `${context}: entry_currency USD requires a US ticker.`,
      );
    }

    const normalizedEntryCurrency =
      market === "KR" && entryCurrency === "KRW" ? null : entryCurrency;

    const tags = normalizeStringList(row.tags);
    const ownsEntryPattern = hasOwn(row, "entry_pattern");
    const entryPattern = ownsEntryPattern
      ? parseOptionalEntryPattern(row.entry_pattern, "entry_pattern", context)
      : undefined;
    if (quantity === 0 && entryPattern != null) {
      throw new HoldingsYamlError(
        `${context}: entry_pattern for inactive holdings must be null.`,
      );
    }

    const snapshot: HoldingReplaceSnapshot = {
      ticker,
      quantity,
      entry_price: entryPrice,
      entry_currency: normalizedEntryCurrency,
      entry_date: parseOptionalDate(row.entry_date, "entry_date", context),
      strategy: parseOptionalText(row.strategy) ?? settings.default_strategy,
      notes: parseOptionalText(row.notes),
      tags: tags.length > 0 ? tags : [...settings.default_tags],
      stop_override: parseOptionalNonNegativeNumber(
        row.stop_override,
        "stop_override",
        context,
      ),
      target_override: parseOptionalNonNegativeNumber(
        row.target_override,
        "target_override",
        context,
      ),
    };
    if (ownsEntryPattern) {
      snapshot.entry_pattern = entryPattern ?? null;
    }
    return snapshot;
  });

  const duplicateTickerSet = new Set<string>();
  for (const row of snapshots) {
    if (duplicateTickerSet.has(row.ticker)) {
      throw new HoldingsYamlError(
        `Duplicate ticker '${row.ticker}' is not allowed in holdings.yaml.`,
      );
    }
    duplicateTickerSet.add(row.ticker);
  }

  return sortHoldingsByTicker(snapshots);
}

export function buildHoldingsYamlImportSummary(
  currentHoldings: readonly HoldingRecord[],
  incomingHoldings: readonly HoldingReplaceSnapshot[],
): HoldingsYamlImportSummary {
  try {
    return buildHoldingsReconciliationSummary(
      currentHoldings,
      incomingHoldings,
    );
  } catch (error) {
    if (error instanceof HoldingsReconciliationError) {
      throw new HoldingsYamlError(error.message);
    }
    throw error;
  }
}
