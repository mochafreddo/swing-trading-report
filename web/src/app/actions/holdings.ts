"use server";

import { requireAdminActionSession } from "@/lib/admin-action-auth";
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import { isValidIdempotencyKey } from "@/lib/idempotency-key";
import {
  holdingAddBuySchema,
  holdingCreateSchema,
  holdingPatchSchema,
  holdingTickerSchema,
} from "@/lib/schemas";
import {
  addBuyToHolding,
  createHolding,
  deleteHolding,
  SupabaseApiError,
  updateHolding,
} from "@/lib/supabase-admin";

export type HoldingsActionResult =
  | {
      ok: true;
    }
  | {
      ok: false;
      error: string;
      code?: string;
    };

export interface SaveHoldingActionInput {
  editingTicker: string | null;
  payload: unknown;
}

export interface AddBuyToHoldingActionInput {
  ticker: string;
  idempotencyKey: string;
  payload: unknown;
}

function parseTicker(ticker: string): string | null {
  const parsed = holdingTickerSchema.safeParse(ticker);
  return parsed.success ? normalizeHoldingTickerForMutation(parsed.data) : null;
}

function toUnknownError(error: unknown): HoldingsActionResult {
  return {
    ok: false,
    error: error instanceof Error ? error.message : "Unknown error",
  };
}

export async function saveHoldingAction(
  input: SaveHoldingActionInput,
): Promise<HoldingsActionResult> {
  try {
    await requireAdminActionSession();
  } catch (error) {
    return toUnknownError(error);
  }

  if (input.editingTicker) {
    const ticker = parseTicker(input.editingTicker);
    if (!ticker) {
      return { ok: false, error: "Invalid ticker" };
    }

    const parsed = holdingPatchSchema.safeParse(input.payload);
    if (!parsed.success) {
      return { ok: false, error: "Invalid holding patch payload" };
    }

    try {
      const updated = await updateHolding(ticker, parsed.data);
      if (!updated) {
        return { ok: false, error: "Holding not found" };
      }
      return { ok: true };
    } catch (error) {
      if (error instanceof SupabaseApiError) {
        return { ok: false, error: error.message };
      }
      return toUnknownError(error);
    }
  }

  const parsed = holdingCreateSchema.safeParse(input.payload);
  if (!parsed.success) {
    return { ok: false, error: "Invalid holding payload" };
  }

  try {
    await createHolding(parsed.data);
    return { ok: true };
  } catch (error) {
    if (error instanceof SupabaseApiError) {
      return { ok: false, error: error.message };
    }
    return toUnknownError(error);
  }
}

export async function deleteHoldingAction(
  tickerInput: string,
): Promise<HoldingsActionResult> {
  try {
    await requireAdminActionSession();
  } catch (error) {
    return toUnknownError(error);
  }

  const ticker = parseTicker(tickerInput);
  if (!ticker) {
    return { ok: false, error: "Invalid ticker" };
  }

  try {
    const deleted = await deleteHolding(ticker);
    if (!deleted) {
      return { ok: false, error: "Holding not found" };
    }
    return { ok: true };
  } catch (error) {
    if (error instanceof SupabaseApiError) {
      return { ok: false, error: error.message };
    }
    return toUnknownError(error);
  }
}

export async function addBuyToHoldingAction(
  input: AddBuyToHoldingActionInput,
): Promise<HoldingsActionResult> {
  try {
    await requireAdminActionSession();
  } catch (error) {
    return toUnknownError(error);
  }

  const ticker = parseTicker(input.ticker);
  if (!ticker) {
    return { ok: false, error: "Invalid ticker" };
  }

  const idempotencyKey = input.idempotencyKey.trim();
  if (!idempotencyKey) {
    return { ok: false, error: "Missing Idempotency-Key header" };
  }
  if (!isValidIdempotencyKey(idempotencyKey)) {
    return { ok: false, error: "Invalid Idempotency-Key header" };
  }

  const parsed = holdingAddBuySchema.safeParse(input.payload);
  if (!parsed.success) {
    return { ok: false, error: "Invalid holding add-buy payload" };
  }

  try {
    const updated = await addBuyToHolding(ticker, parsed.data, idempotencyKey);
    if (!updated) {
      return { ok: false, error: "Holding not found" };
    }
    return { ok: true };
  } catch (error) {
    if (error instanceof SupabaseApiError) {
      if (
        error.status === 409 &&
        error.code === ADD_BUY_IDEMPOTENCY_MISMATCH_CODE
      ) {
        return {
          ok: false,
          error: error.message,
          code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
        };
      }

      return { ok: false, error: error.message };
    }

    return toUnknownError(error);
  }
}
