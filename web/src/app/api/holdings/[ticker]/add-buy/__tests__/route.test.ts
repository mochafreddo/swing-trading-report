import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/admin-auth", () => {
  class AdminAuthError extends Error {
    status: number;
    headers?: HeadersInit;

    constructor(message = "Unauthorized", status = 401, headers?: HeadersInit) {
      super(message);
      this.status = status;
      this.headers = headers;
    }
  }

  return {
    AdminAuthError,
    requireAdminAuth: vi.fn(async () => undefined),
  };
});

vi.mock("@/lib/same-origin", () => {
  class SameOriginError extends Error {
    status: number;

    constructor(message = "Cross-site request blocked", status = 403) {
      super(message);
      this.status = status;
    }
  }

  return {
    SameOriginError,
    assertSameOrigin: vi.fn(() => undefined),
  };
});

vi.mock("@/lib/local-request-guard", () => {
  class LocalRequestGuardError extends Error {
    status: number;

    constructor(message = "Local only", status = 403) {
      super(message);
      this.status = status;
    }
  }

  return {
    LocalRequestGuardError,
    assertLocalRequest: vi.fn(() => undefined),
  };
});

vi.mock("@/lib/supabase-admin", () => {
  class SupabaseApiError extends Error {
    status: number;
    code: string | null;

    constructor(
      message: string,
      status: number,
      options?: {
        code?: string | null;
      },
    ) {
      super(message);
      this.status = status;
      this.code = options?.code ?? null;
    }
  }

  return {
    SupabaseApiError,
    addBuyToHolding: vi.fn(),
  };
});

import { POST } from "@/app/api/holdings/[ticker]/add-buy/route";
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { addBuyToHolding, SupabaseApiError } from "@/lib/supabase-admin";

type RouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

function makeRequest(
  payload: object | string,
  options?: { idempotencyKey?: string },
): NextRequest {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload);
  const idempotencyKey =
    options?.idempotencyKey ?? "11111111-1111-4111-8111-111111111111";
  return new NextRequest("http://localhost:55300/api/holdings/005930/add-buy", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
      "idempotency-key": idempotencyKey,
    },
    body,
  });
}

function makeContext(ticker: string): RouteContext {
  return {
    params: { ticker },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/holdings/[ticker]/add-buy route", () => {
  it("maps admin auth failures with status and headers", async () => {
    const authError = new AdminAuthError("Unauthorized");
    (authError as { headers: HeadersInit }).headers = {
      "x-auth-required": "1",
    };
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(authError);

    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(401);
    expect(response.headers.get("x-auth-required")).toBe("1");
    expect(payload.error).toBe("Unauthorized");
    expect(vi.mocked(assertSameOrigin)).not.toHaveBeenCalled();
    expect(vi.mocked(assertLocalRequest)).not.toHaveBeenCalled();
  });

  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
    expect(vi.mocked(assertLocalRequest)).not.toHaveBeenCalled();
  });

  it("maps local-request guard failures to 403", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
  });

  it("returns 400 for invalid ticker", async () => {
    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("AAPL"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid ticker");
    expect(vi.mocked(addBuyToHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid JSON", async () => {
    const response = await POST(makeRequest("{"), makeContext("005930"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Request body must be valid JSON");
    expect(vi.mocked(addBuyToHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid payload", async () => {
    const response = await POST(
      makeRequest({ buy_quantity: 0, buy_price: 10 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { buy_quantity?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid holding add-buy payload");
    expect(payload.details?.fieldErrors?.buy_quantity).toBeDefined();
    expect(vi.mocked(addBuyToHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 when idempotency key header is missing", async () => {
    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }, { idempotencyKey: "" }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Missing Idempotency-Key header");
    expect(vi.mocked(addBuyToHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 when idempotency key header format is invalid", async () => {
    const response = await POST(
      makeRequest(
        { buy_quantity: 1, buy_price: 10 },
        { idempotencyKey: "not-a-uuid" },
      ),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid Idempotency-Key header");
    expect(vi.mocked(addBuyToHolding)).not.toHaveBeenCalled();
  });

  it("returns 404 when holding is not found", async () => {
    vi.mocked(addBuyToHolding).mockResolvedValueOnce(null);

    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(404);
    expect(payload.error).toBe("Holding not found");
  });

  it("maps supabase API errors as-is", async () => {
    vi.mocked(addBuyToHolding).mockRejectedValueOnce(
      new SupabaseApiError("currency mismatch", 409),
    );

    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("AAPL.NAS"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(409);
    expect(payload.error).toBe("currency mismatch");
  });

  it("returns structured code for idempotency payload mismatch conflicts", async () => {
    vi.mocked(addBuyToHolding).mockRejectedValueOnce(
      new SupabaseApiError("conflict", 409, {
        code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
      }),
    );

    const response = await POST(
      makeRequest({ buy_quantity: 1, buy_price: 10 }),
      makeContext("AAPL.NAS"),
    );
    const payload = (await response.json()) as { error: string; code?: string };

    expect(response.status).toBe(409);
    expect(payload.error).toBe("conflict");
    expect(payload.code).toBe(ADD_BUY_IDEMPOTENCY_MISMATCH_CODE);
  });

  it("adds buy and normalizes ticker to uppercase canonical form", async () => {
    vi.mocked(addBuyToHolding).mockResolvedValueOnce({
      ticker: "AAPL.NAS",
      quantity: 2,
      entry_price: 101,
      entry_currency: "USD",
      entry_date: "2026-03-03",
      strategy: null,
      notes: null,
      tags: [],
      stop_override: null,
      target_override: null,
      created_at: "2026-03-03T00:00:00Z",
      updated_at: "2026-03-03T00:00:00Z",
    });

    const response = await POST(
      makeRequest({
        buy_quantity: "1",
        buy_price: "102.5",
        buy_date: "2026-03-03",
      }),
      makeContext("aapl.nasd"),
    );
    const payload = (await response.json()) as {
      ticker: string;
      quantity: number;
      entry_price: number;
    };

    expect(response.status).toBe(200);
    expect(payload).toMatchObject({
      ticker: "AAPL.NAS",
      quantity: 2,
      entry_price: 101,
    });
    expect(vi.mocked(addBuyToHolding)).toHaveBeenCalledWith(
      "AAPL.NAS",
      {
        buy_quantity: 1,
        buy_price: 102.5,
        buy_date: "2026-03-03",
      },
      "11111111-1111-4111-8111-111111111111",
    );
  });
});
