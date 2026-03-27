import type { ReportListItem, ReportType } from "@/lib/types";

const REPORT_KEY_PATTERN =
  /^(?<year>\d{4})\/(?<month>\d{2})\/(?<date>\d{4}-\d{2}-\d{2})(?:-(?<dup>\d+))?\.(?<type>buy|sell|entry)\.json$/;

export interface ParsedReportStorageKey {
  key: string;
  type: ReportType;
  reportDate: string;
  duplicateIndex: number;
  year: number;
  month: number;
}

function isValidReportDate(year: number, month: number, day: number): boolean {
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day)
  ) {
    return false;
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) {
    return false;
  }
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() + 1 === month &&
    parsed.getUTCDate() === day
  );
}

export function parseReportStorageKey(
  key: string,
): ParsedReportStorageKey | null {
  const normalized = key.trim();
  const match = REPORT_KEY_PATTERN.exec(normalized);
  if (!match?.groups) {
    return null;
  }

  const date = match.groups.date;
  const year = Number.parseInt(match.groups.year, 10);
  const month = Number.parseInt(match.groups.month, 10);
  const [dateYearText, dateMonthText, dateDayText] = date.split("-");
  const dateYear = Number.parseInt(dateYearText ?? "", 10);
  const dateMonth = Number.parseInt(dateMonthText ?? "", 10);
  const dateDay = Number.parseInt(dateDayText ?? "", 10);

  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    year !== dateYear ||
    month !== dateMonth ||
    !isValidReportDate(dateYear, dateMonth, dateDay)
  ) {
    return null;
  }

  const duplicateIndex = match.groups.dup
    ? Number.parseInt(match.groups.dup, 10)
    : 0;
  if (!Number.isFinite(duplicateIndex) || duplicateIndex < 0) {
    return null;
  }

  return {
    key: normalized,
    type: match.groups.type as ReportType,
    reportDate: date,
    duplicateIndex,
    year,
    month,
  };
}

export function compareParsedReportKeys(
  a: ParsedReportStorageKey,
  b: ParsedReportStorageKey,
): number {
  const dateCompare = b.reportDate.localeCompare(a.reportDate);
  if (dateCompare !== 0) {
    return dateCompare;
  }
  return b.duplicateIndex - a.duplicateIndex;
}

export function filterAndSortReportKeys(
  keys: string[],
  type: ReportType | "all" = "all",
): ParsedReportStorageKey[] {
  const parsed = keys
    .map((key) => parseReportStorageKey(key))
    .filter((entry): entry is ParsedReportStorageKey => Boolean(entry))
    .filter((entry) => type === "all" || entry.type === type);

  parsed.sort(compareParsedReportKeys);
  return parsed;
}

export function toReportListItem(
  parsed: ParsedReportStorageKey,
  extras?: Pick<ReportListItem, "generatedAt" | "summary" | "tickers">,
): ReportListItem {
  return {
    key: parsed.key,
    type: parsed.type,
    reportDate: parsed.reportDate,
    duplicateIndex: parsed.duplicateIndex,
    ...extras,
  };
}
