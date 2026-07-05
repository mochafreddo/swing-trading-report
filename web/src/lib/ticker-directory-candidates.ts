import "server-only";

import { isHoldingEntryPattern } from "@/lib/holding-entry-pattern";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";

export interface TickerDirectoryCandidate {
  ticker: string;
  name: string | null;
}

export interface RecentBuyCandidate extends TickerDirectoryCandidate {
  pattern: string | null;
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

function normalizeCandidatePattern(value: unknown): string | null {
  const text = toCleanString(value);
  return isHoldingEntryPattern(text) ? text : null;
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

function extractRecentBuyCandidateFromRow(
  row: unknown,
): RecentBuyCandidate | null {
  const candidate = extractBuyCandidateFromRow(row);
  if (!candidate || !row || typeof row !== "object" || Array.isArray(row)) {
    return null;
  }
  const raw = row as { pattern?: unknown };
  return {
    ...candidate,
    pattern: normalizeCandidatePattern(raw.pattern),
  };
}

export function extractRecentBuyCandidatesFromRows(
  rows: unknown[],
): RecentBuyCandidate[] {
  const seen = new Map<string, RecentBuyCandidate>();
  const results: RecentBuyCandidate[] = [];
  for (const row of rows) {
    const candidate = extractRecentBuyCandidateFromRow(row);
    if (!candidate) {
      continue;
    }

    const existing = seen.get(candidate.ticker);
    if (existing) {
      if (!existing.name && candidate.name) {
        existing.name = candidate.name;
      }
      if (!existing.pattern && candidate.pattern) {
        existing.pattern = candidate.pattern;
      }
      continue;
    }

    seen.set(candidate.ticker, candidate);
    results.push(candidate);
  }
  return results;
}
