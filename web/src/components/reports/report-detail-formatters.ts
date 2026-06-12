import { asRecord, readString } from "./helpers";

function formatIssue(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
  }
  const record = asRecord(value);
  if (!record) {
    return null;
  }

  const ticker = readString(record.ticker);
  const severity = readString(record.severity);
  const code = readString(record.code);
  const message = readString(record.message);
  const prefix = [ticker, severity, code].filter(Boolean).join(" ");
  if (message && prefix) {
    return `${prefix}: ${message}`;
  }
  return message ?? (prefix || null);
}

export function asIssueArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => formatIssue(item))
    .filter((item): item is string => Boolean(item));
}

export function formatSources(value: unknown): string {
  if (!Array.isArray(value)) {
    return "-";
  }
  const sources = value
    .map((source) => {
      const record = asRecord(source);
      if (!record) {
        return null;
      }
      const title = readString(record.title);
      const url = readString(record.url);
      if (title && url) {
        return `${title} (${url})`;
      }
      return title ?? url;
    })
    .filter((item): item is string => Boolean(item));
  return sources.join(" · ") || "-";
}
