import type { ReportListItem } from "@/lib/types";

import type { ReportJson, ReportsFilterType } from "./types";

export { readApiError } from "@/lib/error-utils";

export function parseReportType(value: string | null): ReportsFilterType {
  if (
    value === "buy" ||
    value === "sell" ||
    value === "entry" ||
    value === "ai-brief"
  ) {
    return value;
  }
  return "all";
}

export function asRecord(value: unknown): ReportJson | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as ReportJson;
}

export function asRecordArray(value: unknown): ReportJson[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => asRecord(entry))
    .filter((entry): entry is ReportJson => Boolean(entry));
}

export function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  return null;
}

export function readNumberLike(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

export function readString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function formatPnlPercent(value: unknown): string {
  const pnl = readNumber(value);
  if (pnl === null) {
    return "-";
  }
  const pct = pnl * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

export function formatDateLabel(item: ReportListItem): string {
  return item.duplicateIndex > 0
    ? `${item.reportDate} #${item.duplicateIndex}`
    : item.reportDate;
}
