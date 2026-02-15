import type { ReportListItem, ReportType } from "@/lib/types";

const REPORT_KEY_PATTERN =
  /^(?<year>\d{4})\/(?<month>\d{2})\/(?<date>\d{4}-\d{2}-\d{2})(?:-(?<dup>\d+))?\.(?<type>buy|sell)\.json$/;

export interface ParsedReportStorageKey {
  key: string;
  type: ReportType;
  reportDate: string;
  duplicateIndex: number;
  year: number;
  month: number;
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
  const parsedDate = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsedDate.getTime())) {
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
    year: Number.parseInt(match.groups.year, 10),
    month: Number.parseInt(match.groups.month, 10),
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
