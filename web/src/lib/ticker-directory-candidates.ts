import "server-only";

import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";

export interface TickerDirectoryCandidate {
  ticker: string;
  name: string | null;
}

function toCleanString(value: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim();
}

export function normalizeCandidateTicker(value: unknown): string {
  const raw = toCleanString(value).toUpperCase();
  if (!raw) {
    return "";
  }
  return normalizeHoldingTickerForMutation(raw);
}

export function normalizeCandidateName(value: unknown): string | null {
  const text = toCleanString(value);
  return text ? text : null;
}

export function collectTickerAliases(
  ticker: string,
  name: string | null,
): string[] {
  const aliases = new Set<string>();
  const upperTicker = ticker.toUpperCase();
  aliases.add(upperTicker);

  const lastDotIndex = upperTicker.lastIndexOf(".");
  if (lastDotIndex > 0) {
    const symbol = upperTicker.slice(0, lastDotIndex);
    const suffix = upperTicker.slice(lastDotIndex + 1);
    aliases.add(symbol);

    const classMatch = symbol.match(/^([A-Z][A-Z0-9]*)\.([ABC])$/);
    if (classMatch) {
      aliases.add(`${classMatch[1]}/${classMatch[2]}`);
      aliases.add(`${classMatch[1]}/${classMatch[2]}.${suffix}`);
    }
  }

  if (name) {
    aliases.add(name);
    aliases.add(name.replace(/\s+/g, ""));
  }

  return Array.from(aliases);
}

export function extractBuyCandidateFromRow(
  row: unknown,
): TickerDirectoryCandidate | null {
  if (!row || typeof row !== "object" || Array.isArray(row)) {
    return null;
  }
  const raw = row as { ticker?: unknown; name?: unknown };
  const ticker = normalizeCandidateTicker(raw.ticker);
  if (!ticker) {
    return null;
  }
  return {
    ticker,
    name: normalizeCandidateName(raw.name),
  };
}

export function extractBuyCandidatesFromRows(
  rows: unknown[],
): TickerDirectoryCandidate[] {
  const seen = new Set<string>();
  const results: TickerDirectoryCandidate[] = [];
  for (const row of rows) {
    const candidate = extractBuyCandidateFromRow(row);
    if (!candidate || seen.has(candidate.ticker)) {
      continue;
    }
    seen.add(candidate.ticker);
    results.push(candidate);
  }
  return results;
}
