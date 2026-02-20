const DEFAULT_REPORT_KEYS_CACHE_TTL_SECONDS = 30;
const MIN_REPORT_KEYS_CACHE_TTL_SECONDS = 0;
const MAX_REPORT_KEYS_CACHE_TTL_SECONDS = 600;

const DEFAULT_REPORT_SEARCH_CONCURRENCY = 8;
const MIN_REPORT_SEARCH_CONCURRENCY = 1;
const MAX_REPORT_SEARCH_CONCURRENCY = 16;

function parsePositiveInteger(raw: string | undefined): number | null {
  if (typeof raw !== "string") {
    return null;
  }

  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }

  if (!/^\d+$/.test(trimmed)) {
    return null;
  }

  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed)) {
    return null;
  }

  return parsed;
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) {
    return min;
  }
  if (value > max) {
    return max;
  }
  return value;
}

export function resolveReportKeysCacheTtlSeconds(raw?: string): number {
  const parsed = parsePositiveInteger(raw);
  if (parsed === null) {
    return DEFAULT_REPORT_KEYS_CACHE_TTL_SECONDS;
  }

  return clamp(
    parsed,
    MIN_REPORT_KEYS_CACHE_TTL_SECONDS,
    MAX_REPORT_KEYS_CACHE_TTL_SECONDS,
  );
}

export function resolveReportSearchConcurrency(raw?: string): number {
  const parsed = parsePositiveInteger(raw);
  if (parsed === null) {
    return DEFAULT_REPORT_SEARCH_CONCURRENCY;
  }

  return clamp(
    parsed,
    MIN_REPORT_SEARCH_CONCURRENCY,
    MAX_REPORT_SEARCH_CONCURRENCY,
  );
}
