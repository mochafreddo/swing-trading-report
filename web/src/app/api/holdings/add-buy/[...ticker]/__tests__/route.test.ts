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

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }

  return {
    SupabaseApiError,
    addBuyToHolding: vi.fn(),
  };
});

import { POST } from "@/app/api/holdings/add-buy/[...ticker]/route";
import { addBuyToHolding } from "@/lib/supabase-admin";

function makeRequest(payload: object): NextRequest {
  return new NextRequest(
    "http://localhost:55300/api/holdings/add-buy/BRK/B.NYS",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://localhost:55300",
      },
      body: JSON.stringify(payload),
    },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("/api/holdings/add-buy/[...ticker] route", () => {
  it("reconstructs segmented ticker path for add-buy", async () => {
    vi.mocked(addBuyToHolding).mockResolvedValueOnce({
      ticker: "BRK.B.NYS",
      quantity: 3,
      entry_price: 452.5,
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
      makeRequest({ buy_quantity: 1, buy_price: 455 }),
      {
        params: { ticker: ["BRK", "B.NYS"] },
      },
    );
    const payload = (await response.json()) as {
      ticker: string;
    };

    expect(response.status).toBe(200);
    expect(payload.ticker).toBe("BRK.B.NYS");
    expect(vi.mocked(addBuyToHolding)).toHaveBeenCalledWith("BRK.B.NYS", {
      buy_quantity: 1,
      buy_price: 455,
    });
  });

  it("decodes percent-encoded slash ticker for add-buy", async () => {
    vi.mocked(addBuyToHolding).mockResolvedValueOnce({
      ticker: "BRK.B.NYS",
      quantity: 3,
      entry_price: 452.5,
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
      makeRequest({ buy_quantity: 1, buy_price: 455 }),
      {
        params: { ticker: ["BRK%2FB.NYS"] },
      },
    );

    expect(response.status).toBe(200);
    expect(vi.mocked(addBuyToHolding)).toHaveBeenCalledWith("BRK.B.NYS", {
      buy_quantity: 1,
      buy_price: 455,
    });
  });
});
