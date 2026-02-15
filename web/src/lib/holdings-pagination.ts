import type { HoldingCursor } from "@/lib/types";

export class HoldingCursorError extends Error {
  readonly status = 400;

  constructor(message: string) {
    super(message);
  }
}

function quotePostgrestValue(value: string): string {
  const escaped = value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return `"${escaped}"`;
}

function isValidCursorPayload(payload: unknown): payload is HoldingCursor {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return false;
  }

  const updatedAt = (payload as { updated_at?: unknown }).updated_at;
  const ticker = (payload as { ticker?: unknown }).ticker;

  if (typeof updatedAt !== "string" || typeof ticker !== "string") {
    return false;
  }

  if (!updatedAt.trim() || !ticker.trim()) {
    return false;
  }

  return Number.isFinite(Date.parse(updatedAt));
}

export function encodeHoldingCursor(cursor: HoldingCursor): string {
  return Buffer.from(JSON.stringify(cursor), "utf-8").toString("base64url");
}

export function decodeHoldingCursor(encoded: string): HoldingCursor {
  try {
    const json = Buffer.from(encoded, "base64url").toString("utf-8");
    const parsed = JSON.parse(json) as unknown;
    if (!isValidCursorPayload(parsed)) {
      throw new HoldingCursorError("Invalid holdings cursor payload");
    }

    return {
      updated_at: parsed.updated_at,
      ticker: parsed.ticker
    };
  } catch (error) {
    if (error instanceof HoldingCursorError) {
      throw error;
    }
    throw new HoldingCursorError("Invalid holdings cursor encoding");
  }
}

export function buildHoldingsKeysetFilter(cursor: HoldingCursor): string {
  const updatedAt = quotePostgrestValue(cursor.updated_at);
  const ticker = quotePostgrestValue(cursor.ticker);
  return `(updated_at.lt.${updatedAt},and(updated_at.eq.${updatedAt},ticker.gt.${ticker}))`;
}
