import type { HoldingRecord } from "@/lib/types";

import type { HoldingFormState } from "./form-state";

export const HOLDINGS_PAGE_SIZE = 100;

function numberOrUndefined(value: string): number | undefined {
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : undefined;
}

function requiredNumber(value: string, label: string): number {
  const parsed = numberOrUndefined(value);
  if (parsed == null) {
    throw new Error(`${label} 값이 올바르지 않습니다.`);
  }
  return parsed;
}

function numberOrNull(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

function stringOrNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

export function recordToForm(record: HoldingRecord): HoldingFormState {
  return {
    ticker: record.ticker,
    quantity: String(record.quantity),
    entry_price: String(record.entry_price),
    entry_currency: record.entry_currency ?? "",
    entry_date: record.entry_date ?? "",
    strategy: record.strategy ?? "",
    notes: record.notes ?? "",
    tags: record.tags.join(", "),
    stop_override:
      record.stop_override == null ? "" : String(record.stop_override),
    target_override:
      record.target_override == null ? "" : String(record.target_override),
  };
}

export function buildCreatePayload(form: HoldingFormState) {
  return {
    ticker: form.ticker,
    quantity: requiredNumber(form.quantity, "Quantity"),
    entry_price: requiredNumber(form.entry_price, "Entry Price"),
    entry_currency: stringOrNull(form.entry_currency),
    entry_date: stringOrNull(form.entry_date),
    strategy: stringOrNull(form.strategy),
    notes: stringOrNull(form.notes),
    tags: form.tags,
    stop_override: numberOrNull(form.stop_override),
    target_override: numberOrNull(form.target_override),
  };
}

export function buildPatchPayload(form: HoldingFormState) {
  return {
    quantity: requiredNumber(form.quantity, "Quantity"),
    entry_price: requiredNumber(form.entry_price, "Entry Price"),
    entry_currency: stringOrNull(form.entry_currency),
    entry_date: stringOrNull(form.entry_date),
    strategy: stringOrNull(form.strategy),
    notes: stringOrNull(form.notes),
    tags: form.tags,
    stop_override: numberOrNull(form.stop_override),
    target_override: numberOrNull(form.target_override),
  };
}

export function readApiError(payload: unknown): string | undefined {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  const value = (payload as { error?: unknown }).error;
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function mergeHoldingsByTicker(
  current: HoldingRecord[],
  incoming: HoldingRecord[],
): HoldingRecord[] {
  const merged = [...current, ...incoming];
  const seen = new Set<string>();
  return merged.filter((item) => {
    if (seen.has(item.ticker)) {
      return false;
    }
    seen.add(item.ticker);
    return true;
  });
}
