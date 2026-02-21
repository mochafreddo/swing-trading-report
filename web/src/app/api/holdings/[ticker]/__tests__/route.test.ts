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
    updateHolding: vi.fn(),
    deleteHolding: vi.fn(),
  };
});

import { DELETE, PATCH } from "@/app/api/holdings/[ticker]/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import {
  deleteHolding,
  SupabaseApiError,
  updateHolding,
} from "@/lib/supabase-admin";

type RouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

function makePatchRequest(payload: object | string): NextRequest {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload);
  return new NextRequest("http://localhost:55300/api/holdings/005930", {
    method: "PATCH",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
    },
    body,
  });
}

function makeDeleteRequest(): NextRequest {
  return new NextRequest("http://localhost:55300/api/holdings/005930", {
    method: "DELETE",
    headers: {
      origin: "http://localhost:55300",
    },
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

describe("PATCH /api/holdings/[ticker] route", () => {
  it("maps admin auth failures with status and headers", async () => {
    const authError = new AdminAuthError("Unauthorized");
    (authError as { headers: HeadersInit }).headers = {
      "x-auth-required": "1",
    };
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(authError);

    const response = await PATCH(
      makePatchRequest({ quantity: 1 }),
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

    const response = await PATCH(
      makePatchRequest({ quantity: 1 }),
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

    const response = await PATCH(
      makePatchRequest({ quantity: 1 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
  });

  it("returns 400 for invalid ticker", async () => {
    const response = await PATCH(
      makePatchRequest({ quantity: 1 }),
      makeContext("%20"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid ticker");
    expect(vi.mocked(updateHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 when ticker format is unsupported", async () => {
    const response = await PATCH(
      makePatchRequest({ quantity: 1 }),
      makeContext("AAPL"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid ticker");
    expect(vi.mocked(updateHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid JSON", async () => {
    const response = await PATCH(makePatchRequest("{"), makeContext("005930"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Request body must be valid JSON");
    expect(vi.mocked(updateHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid payload", async () => {
    const response = await PATCH(
      makePatchRequest({ quantity: -1 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { quantity?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid holding patch payload");
    expect(payload.details?.fieldErrors?.quantity).toBeDefined();
    expect(vi.mocked(updateHolding)).not.toHaveBeenCalled();
  });

  it("returns 404 when holding is not found", async () => {
    vi.mocked(updateHolding).mockResolvedValueOnce(null);

    const response = await PATCH(
      makePatchRequest({ quantity: 3 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(404);
    expect(payload.error).toBe("Holding not found");
  });

  it("maps supabase API errors as-is", async () => {
    vi.mocked(updateHolding).mockRejectedValueOnce(
      new SupabaseApiError("write failed", 503),
    );

    const response = await PATCH(
      makePatchRequest({ quantity: 3 }),
      makeContext("005930"),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(503);
    expect(payload.error).toBe("write failed");
  });

  it("updates and normalizes ticker to uppercase", async () => {
    vi.mocked(updateHolding).mockResolvedValueOnce({
      ticker: "005930",
      quantity: 3,
      entry_price: 0,
      entry_currency: null,
      entry_date: null,
      strategy: null,
      notes: null,
      tags: [],
      stop_override: null,
      target_override: null,
      created_at: "2026-02-20T00:00:00Z",
      updated_at: "2026-02-20T00:00:00Z",
    });

    const response = await PATCH(
      makePatchRequest({ quantity: 3 }),
      makeContext("aapl.us"),
    );
    const payload = (await response.json()) as {
      ticker: string;
      quantity: number;
    };

    expect(response.status).toBe(200);
    expect(payload).toMatchObject({
      ticker: "005930",
      quantity: 3,
    });
    expect(vi.mocked(updateHolding)).toHaveBeenCalledWith("AAPL.US", {
      quantity: 3,
    });
  });
});

describe("DELETE /api/holdings/[ticker] route", () => {
  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await DELETE(makeDeleteRequest(), makeContext("005930"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
    expect(vi.mocked(deleteHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid ticker", async () => {
    const response = await DELETE(makeDeleteRequest(), makeContext("%20"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid ticker");
    expect(vi.mocked(deleteHolding)).not.toHaveBeenCalled();
  });

  it("returns 400 when ticker format is unsupported", async () => {
    const response = await DELETE(makeDeleteRequest(), makeContext("AAPL"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid ticker");
    expect(vi.mocked(deleteHolding)).not.toHaveBeenCalled();
  });

  it("returns 404 when holding is not found", async () => {
    vi.mocked(deleteHolding).mockResolvedValueOnce(false);

    const response = await DELETE(makeDeleteRequest(), makeContext("005930"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(404);
    expect(payload.error).toBe("Holding not found");
  });

  it("maps supabase API errors as-is", async () => {
    vi.mocked(deleteHolding).mockRejectedValueOnce(
      new SupabaseApiError("delete failed", 503),
    );

    const response = await DELETE(makeDeleteRequest(), makeContext("005930"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(503);
    expect(payload.error).toBe("delete failed");
  });

  it("returns deleted response with normalized ticker", async () => {
    vi.mocked(deleteHolding).mockResolvedValueOnce(true);

    const response = await DELETE(makeDeleteRequest(), makeContext("aapl.us"));
    const payload = (await response.json()) as {
      deleted: boolean;
      ticker: string;
    };

    expect(response.status).toBe(200);
    expect(payload).toEqual({ deleted: true, ticker: "AAPL.US" });
    expect(vi.mocked(deleteHolding)).toHaveBeenCalledWith("AAPL.US");
  });
});
