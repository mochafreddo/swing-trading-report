import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  requireAdminActionSession,
  createHolding,
  updateHolding,
  deleteHolding,
  addBuyToHolding,
} = vi.hoisted(() => ({
  requireAdminActionSession: vi.fn(),
  createHolding: vi.fn(),
  updateHolding: vi.fn(),
  deleteHolding: vi.fn(),
  addBuyToHolding: vi.fn(),
}));

vi.mock("@/lib/admin-action-auth", () => ({
  requireAdminActionSession,
}));

vi.mock("@/lib/supabase-admin", () => ({
  SupabaseApiError: class SupabaseApiError extends Error {
    constructor(
      message: string,
      public readonly status: number,
      options?: { code?: string | null },
    ) {
      super(message);
      this.code = options?.code ?? null;
    }

    readonly code: string | null;
  },
  createHolding,
  updateHolding,
  deleteHolding,
  addBuyToHolding,
}));

import {
  addBuyToHoldingAction,
  deleteHoldingAction,
  saveHoldingAction,
} from "@/app/actions/holdings";
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";

const VALID_IDEMPOTENCY_KEY = [
  "123e4567",
  "e89b",
  "42d3",
  "a456",
  "426614174000",
].join("-");

describe("holdings actions", () => {
  beforeEach(() => {
    requireAdminActionSession.mockReset();
    createHolding.mockReset();
    updateHolding.mockReset();
    deleteHolding.mockReset();
    addBuyToHolding.mockReset();
  });

  it("creates a holding from a valid payload", async () => {
    createHolding.mockResolvedValue({
      ticker: "005930",
    });

    await expect(
      saveHoldingAction({
        editingTicker: null,
        payload: {
          ticker: "005930",
          quantity: 1,
          entry_price: 70000,
          tags: [],
        },
      }),
    ).resolves.toEqual({ ok: true });

    expect(createHolding).toHaveBeenCalledWith({
      ticker: "005930",
      quantity: 1,
      entry_price: 70000,
      tags: [],
    });
  });

  it("rejects invalid edit currency against the existing ticker", async () => {
    await expect(
      saveHoldingAction({
        editingTicker: "005930",
        payload: {
          entry_currency: "USD",
        },
      }),
    ).resolves.toEqual({
      ok: false,
      error: "Invalid holding patch payload",
    });

    expect(updateHolding).not.toHaveBeenCalled();
  });

  it("returns not found when deleting a missing holding", async () => {
    deleteHolding.mockResolvedValue(false);

    await expect(deleteHoldingAction("005930")).resolves.toEqual({
      ok: false,
      error: "Holding not found",
    });
  });

  it("returns idempotency mismatch codes for add-buy conflicts", async () => {
    addBuyToHolding.mockRejectedValueOnce(
      new (await import("@/lib/supabase-admin")).SupabaseApiError(
        "Idempotency conflict",
        409,
        {
          code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
        },
      ),
    );

    await expect(
      addBuyToHoldingAction({
        ticker: "005930",
        idempotencyKey: VALID_IDEMPOTENCY_KEY,
        payload: {
          buy_quantity: 1,
          buy_price: 70000,
          buy_date: "2026-03-06",
        },
      }),
    ).resolves.toEqual({
      ok: false,
      error: "Idempotency conflict",
      code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
    });
  });
});
