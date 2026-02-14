const DEFAULT_REPORT_SEARCH_WINDOW = 100;
const MIN_REPORT_SEARCH_WINDOW = 10;
const MAX_REPORT_SEARCH_WINDOW = 1000;

function clamp(value: number): number {
  if (value < MIN_REPORT_SEARCH_WINDOW) {
    return MIN_REPORT_SEARCH_WINDOW;
  }
  if (value > MAX_REPORT_SEARCH_WINDOW) {
    return MAX_REPORT_SEARCH_WINDOW;
  }
  return value;
}

export function resolveReportSearchWindow(raw?: string): number {
  if (typeof raw !== "string") {
    return DEFAULT_REPORT_SEARCH_WINDOW;
  }

  const trimmed = raw.trim();
  if (!trimmed) {
    return DEFAULT_REPORT_SEARCH_WINDOW;
  }

  if (!/^\d+$/.test(trimmed)) {
    return DEFAULT_REPORT_SEARCH_WINDOW;
  }

  const parsed = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_REPORT_SEARCH_WINDOW;
  }

  return clamp(parsed);
}
