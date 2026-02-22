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

import { DELETE, PATCH } from "@/app/api/holdings/[ticker]/route";

function makePatchRequest(payload: unknown): NextRequest {
  return new NextRequest("http://localhost:55300/api/holdings/aapl.us", {
    method: "PATCH",
    headers: {
      "content-type": "application/json",
      host: "localhost:55300",
      origin: "http://localhost:55300",
    },
    body: JSON.stringify(payload),
  });
}

function makeDeleteRequest(): NextRequest {
  return new NextRequest("http://localhost:55300/api/holdings/AAPL.US", {
    method: "DELETE",
    headers: {
      host: "localhost:55300",
      origin: "http://localhost:55300",
    },
  });
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

describe("/api/holdings/[ticker] integration", () => {
  it("PATCH validates ticker and builds Supabase query with normalized ticker", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([{ ticker: "AAPL.US" }]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await PATCH(makePatchRequest({ quantity: 1 }), {
      params: { ticker: "aapl.us" },
    });
    const payload = (await response.json()) as { ticker: string };

    expect(response.status).toBe(200);
    expect(payload.ticker).toBe("AAPL.US");
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.pathname).toBe("/rest/v1/holdings");
    expect(requestUrl.searchParams.get("ticker")).toBe("eq.AAPL.US");
    expect(requestUrl.searchParams.get("select")).toContain("ticker");
  });

  it("DELETE builds Supabase delete query with normalized ticker", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([{ ticker: "AAPL.US" }]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await DELETE(makeDeleteRequest(), {
      params: { ticker: "AAPL.US" },
    });
    const payload = (await response.json()) as {
      deleted: boolean;
      ticker: string;
    };

    expect(response.status).toBe(200);
    expect(payload).toEqual({ deleted: true, ticker: "AAPL.US" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.pathname).toBe("/rest/v1/holdings");
    expect(requestUrl.searchParams.get("ticker")).toBe("eq.AAPL.US");
    expect(requestUrl.searchParams.get("select")).toBe("ticker");
  });
});
