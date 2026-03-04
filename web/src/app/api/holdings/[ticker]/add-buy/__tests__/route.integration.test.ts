import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/admin-auth", () => {
  class AdminAuthError extends Error {
    status: number;
    headers?: HeadersInit;

    constructor(message: string, status: number, headers?: HeadersInit) {
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

import { POST } from "@/app/api/holdings/[ticker]/add-buy/route";

function makeRequest(
  payload: unknown,
  tickerPath = "aapl.nas",
  options?: { idempotencyKey?: string },
): NextRequest {
  const idempotencyKey =
    options?.idempotencyKey ?? "22222222-2222-4222-8222-222222222222";
  return new NextRequest(
    `http://localhost:55300/api/holdings/${tickerPath}/add-buy`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        host: "localhost:55300",
        origin: "http://localhost:55300",
        "idempotency-key": idempotencyKey,
      },
      body: JSON.stringify(payload),
    },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("SAB_ENFORCE_LOCAL_REQUEST", "1");
  vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
  vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test_key");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("POST /api/holdings/[ticker]/add-buy integration", () => {
  it("calls Supabase RPC with normalized ticker", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
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
          },
        ]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const response = await POST(
      makeRequest({
        buy_quantity: 1,
        buy_price: 100,
        buy_date: "2026-03-03",
      }),
      {
        params: { ticker: "aapl.nas" },
      },
    );
    const payload = (await response.json()) as {
      ticker: string;
    };

    expect(response.status).toBe(200);
    expect(payload.ticker).toBe("AAPL.NAS");
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.pathname).toBe("/rest/v1/rpc/holdings_add_buy_v1");

    const requestInit = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    const requestBody = JSON.parse(String(requestInit.body)) as {
      p_ticker: string;
      p_buy_quantity: number;
      p_buy_price: number;
      p_buy_date: string;
      p_idempotency_key: string;
    };
    expect(requestBody).toEqual({
      p_ticker: "AAPL.NAS",
      p_buy_quantity: 1,
      p_buy_price: 100,
      p_buy_date: "2026-03-03",
      p_idempotency_key: "22222222-2222-4222-8222-222222222222",
    });
  });

  it("accepts percent-encoded slash ticker symbol and normalizes to dot ticker", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            ticker: "BRK/B.NYS",
            quantity: 2,
            entry_price: 450,
            entry_currency: "USD",
            entry_date: "2026-03-03",
            strategy: null,
            notes: null,
            tags: [],
            stop_override: null,
            target_override: null,
            created_at: "2026-03-03T00:00:00Z",
            updated_at: "2026-03-03T00:00:00Z",
          },
        ]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const response = await POST(
      makeRequest(
        {
          buy_quantity: 1,
          buy_price: 100,
        },
        "BRK%2FB.NYS",
      ),
      {
        params: { ticker: "brk%2fb.nys" },
      },
    );

    expect(response.status).toBe(200);
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const requestInit = fetchSpy.mock.calls[0]?.[1] as RequestInit;
    const requestBody = JSON.parse(String(requestInit.body)) as {
      p_ticker: string;
    };
    expect(requestBody.p_ticker).toBe("BRK.B.NYS");
  });
});
