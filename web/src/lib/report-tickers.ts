export type ReportJson = Record<string, unknown>;

function normalizeTicker(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function extractStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const results: string[] = [];
  for (const entry of value) {
    const ticker = normalizeTicker(entry);
    if (ticker) {
      results.push(ticker);
    }
  }
  return results;
}

function extractTickersFromRows(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const results: string[] = [];
  for (const entry of value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      continue;
    }
    const ticker = normalizeTicker((entry as { ticker?: unknown }).ticker);
    if (ticker) {
      results.push(ticker);
    }
  }
  return results;
}

function dedupePreserveOrder(values: string[]): string[] {
  const seen = new Set<string>();
  const results: string[] = [];
  for (const value of values) {
    if (seen.has(value)) {
      continue;
    }
    seen.add(value);
    results.push(value);
  }
  return results;
}

// Primary: `tickers` (newer report artifacts).
// Fallback: derive from row arrays (older artifacts or schema drift).
export function extractReportTickers(report: ReportJson): string[] {
  const tickers = extractStringArray(report.tickers);
  if (tickers.length > 0) {
    return dedupePreserveOrder(tickers);
  }

  const fromCandidates = extractTickersFromRows(report.candidates);
  const fromEvaluated = extractTickersFromRows(report.evaluated);
  return dedupePreserveOrder(fromCandidates.concat(fromEvaluated));
}
