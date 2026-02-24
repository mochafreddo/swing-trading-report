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

vi.mock("@/lib/holdings-pagination", () => {
  class HoldingCursorError extends Error {
    status: number;

    constructor(message: string, status = 400) {
      super(message);
      this.status = status;
    }
  }

  return {
    HoldingCursorError,
    decodeHoldingCursor: vi.fn(),
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
    fetchHoldingsPage: vi.fn(),
    createHolding: vi.fn(),
  };
});

import { GET, POST } from "@/app/api/holdings/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  decodeHoldingCursor,
  HoldingCursorError,
} from "@/lib/holdings-pagination";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import {
  createHolding,
  fetchHoldingsPage,
  SupabaseApiError,
} from "@/lib/supabase-admin";

function makeGetRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/holdings${suffix}`);
}

function makePostRequest(payload: object | string): NextRequest {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload);
  return new NextRequest("http://localhost:55300/api/holdings", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
    },
    body,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GET /api/holdings route", () => {
  it("maps admin auth failures with status and headers", async () => {
    const authError = new AdminAuthError("Unauthorized");
    (authError as { headers: HeadersInit }).headers = {
      "x-auth-required": "1",
    };
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(authError);

    const response = await GET(makeGetRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(401);
    expect(response.headers.get("x-auth-required")).toBe("1");
    expect(payload.error).toBe("Unauthorized");
  });

  it("maps local-request guard failures to 403", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await GET(makeGetRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
  });

  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await GET(makeGetRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
  });

  it("returns 400 for invalid query params", async () => {
    const response = await GET(makeGetRequest("limit=0"));
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { limit?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid query parameters");
    expect(payload.details?.fieldErrors?.limit).toBeDefined();
    expect(vi.mocked(fetchHoldingsPage)).not.toHaveBeenCalled();
  });

  it("maps cursor decode errors to 400", async () => {
    vi.mocked(decodeHoldingCursor).mockImplementationOnce(() => {
      throw new HoldingCursorError("Invalid holdings cursor encoding");
    });

    const response = await GET(makeGetRequest("cursor=bad"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid holdings cursor encoding");
    expect(vi.mocked(fetchHoldingsPage)).not.toHaveBeenCalled();
  });

  it("maps supabase API errors as-is", async () => {
    vi.mocked(fetchHoldingsPage).mockRejectedValueOnce(
      new SupabaseApiError("upstream unavailable", 503),
    );

    const response = await GET(makeGetRequest("limit=10"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(503);
    expect(payload.error).toBe("upstream unavailable");
  });
});

describe("POST /api/holdings route", () => {
  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await POST(makePostRequest({ ticker: "005930" }));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
    expect(vi.mocked(createHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid JSON", async () => {
    const response = await POST(makePostRequest("{"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Request body must be valid JSON");
    expect(vi.mocked(createHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid payload", async () => {
    const response = await POST(
      makePostRequest({
        ticker: "INVALID",
      }),
    );
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { ticker?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid holding payload");
    expect(payload.details?.fieldErrors?.ticker).toBeDefined();
    expect(vi.mocked(createHolding)).not.toHaveBeenCalled();
  });

  it("creates holding with slash ticker symbol", async () => {
    vi.mocked(createHolding).mockResolvedValueOnce({
      ticker: "BRK/B.NYS",
      quantity: 1,
      entry_price: 450,
      entry_currency: null,
      entry_date: null,
      strategy: null,
      notes: null,
      tags: [],
      stop_override: null,
      target_override: null,
      created_at: "2026-02-23T00:00:00Z",
      updated_at: "2026-02-23T00:00:00Z",
    });

    const response = await POST(
      makePostRequest({
        ticker: "brk/b.nys",
        quantity: 1,
        entry_price: 450,
      }),
    );
    const payload = (await response.json()) as { ticker: string };

    expect(response.status).toBe(201);
    expect(payload.ticker).toBe("BRK/B.NYS");
    expect(vi.mocked(createHolding)).toHaveBeenCalledWith(
      expect.objectContaining({
        ticker: "BRK/B.NYS",
        quantity: 1,
        entry_price: 450,
        tags: [],
      }),
    );
  });

  it("normalizes class ticker dot notation to slash on create", async () => {
    vi.mocked(createHolding).mockResolvedValueOnce({
      ticker: "BRK/B.NYS",
      quantity: 1,
      entry_price: 450,
      entry_currency: null,
      entry_date: null,
      strategy: null,
      notes: null,
      tags: [],
      stop_override: null,
      target_override: null,
      created_at: "2026-02-24T00:00:00Z",
      updated_at: "2026-02-24T00:00:00Z",
    });

    const response = await POST(
      makePostRequest({
        ticker: "brk.b.nys",
        quantity: 1,
        entry_price: 450,
      }),
    );
    const payload = (await response.json()) as { ticker: string };

    expect(response.status).toBe(201);
    expect(payload.ticker).toBe("BRK/B.NYS");
    expect(vi.mocked(createHolding)).toHaveBeenCalledWith(
      expect.objectContaining({
        ticker: "BRK/B.NYS",
        quantity: 1,
        entry_price: 450,
        tags: [],
      }),
    );
  });

  it("maps supabase API errors as-is", async () => {
    vi.mocked(createHolding).mockRejectedValueOnce(
      new SupabaseApiError("duplicate holding", 409),
    );

    const response = await POST(
      makePostRequest({
        ticker: "005930",
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(409);
    expect(payload.error).toBe("duplicate holding");
  });
});
