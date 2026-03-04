import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createAddBuyIdempotencyKey,
  resolveAddBuySubmitError,
} from "@/components/holdings/add-buy-idempotency";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("add-buy idempotency helpers", () => {
  it("creates UUID-form idempotency keys", () => {
    const key = createAddBuyIdempotencyKey();
    expect(key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it("requests key rotation for idempotency payload mismatch errors", () => {
    const resolution = resolveAddBuySubmitError(
      new Error(
        "Failed to add buy to holding 'AAPL.NAS': idempotency_key payload mismatch for ticker AAPL.NAS",
      ),
    );

    expect(resolution.shouldRotateIdempotencyKey).toBe(true);
    expect(resolution.message).toContain(
      "새 Idempotency-Key를 자동 발급했습니다",
    );
  });

  it("requests key rotation for structured idempotency mismatch code", () => {
    const codedError = Object.assign(new Error("conflict"), {
      code: "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH",
    });
    const resolution = resolveAddBuySubmitError(codedError);

    expect(resolution.shouldRotateIdempotencyKey).toBe(true);
    expect(resolution.message).toContain(
      "새 Idempotency-Key를 자동 발급했습니다",
    );
  });

  it("keeps key for non-idempotency mismatch errors", () => {
    const resolution = resolveAddBuySubmitError(
      new Error("Failed to add buy to holding 'AAPL.NAS': currency mismatch"),
    );

    expect(resolution.shouldRotateIdempotencyKey).toBe(false);
    expect(resolution.message).toBe(
      "Failed to add buy to holding 'AAPL.NAS': currency mismatch",
    );
  });

  it("uses crypto.getRandomValues fallback when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (array: Uint8Array) => {
        for (let index = 0; index < array.length; index += 1) {
          array[index] = (index * 17 + 13) % 256;
        }
        return array;
      },
    } satisfies Pick<Crypto, "getRandomValues">);

    const key = createAddBuyIdempotencyKey();
    expect(key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it("returns empty string when secure crypto APIs are unavailable", () => {
    vi.stubGlobal("crypto", undefined);
    expect(createAddBuyIdempotencyKey()).toBe("");
  });
});
