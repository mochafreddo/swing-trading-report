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

import { DELETE, PATCH } from "@/app/api/holdings/[...ticker]/route";
import { requireAdminAuth } from "@/lib/admin-auth";
import { deleteHolding, updateHolding } from "@/lib/supabase-admin";

function makePatchRequest(payload: object): NextRequest {
  return new NextRequest("http://localhost:55300/api/holdings/BRK/B.NYS", {
    method: "PATCH",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
    },
    body: JSON.stringify(payload),
  });
}

function makeDeleteRequest(): NextRequest {
  return new NextRequest("http://localhost:55300/api/holdings/BRK/B.NYS", {
    method: "DELETE",
    headers: {
      origin: "http://localhost:55300",
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("/api/holdings/[...ticker] route", () => {
  it("reconstructs segmented ticker path for patch", async () => {
    vi.mocked(updateHolding).mockResolvedValueOnce({
      ticker: "BRK.B.NYS",
      quantity: 3,
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

    const response = await PATCH(makePatchRequest({ quantity: 3 }), {
      params: { ticker: ["BRK", "B.NYS"] },
    });
    const payload = (await response.json()) as { ticker: string };

    expect(response.status).toBe(200);
    expect(payload.ticker).toBe("BRK.B.NYS");
    expect(vi.mocked(updateHolding)).toHaveBeenCalledWith("BRK.B.NYS", {
      quantity: 3,
    });
  });

  it("decodes percent-encoded slash ticker for patch", async () => {
    vi.mocked(updateHolding).mockResolvedValueOnce({
      ticker: "BRK.B.NYS",
      quantity: 3,
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

    const response = await PATCH(makePatchRequest({ quantity: 3 }), {
      params: { ticker: ["BRK%2FB.NYS"] },
    });

    expect(response.status).toBe(200);
    expect(vi.mocked(updateHolding)).toHaveBeenCalledWith("BRK.B.NYS", {
      quantity: 3,
    });
  });

  it("reconstructs segmented ticker path for delete", async () => {
    vi.mocked(deleteHolding).mockResolvedValueOnce(true);

    const response = await DELETE(makeDeleteRequest(), {
      params: { ticker: ["BRK", "B.NYS"] },
    });
    const payload = (await response.json()) as {
      deleted: boolean;
      ticker: string;
    };

    expect(response.status).toBe(200);
    expect(payload).toEqual({ deleted: true, ticker: "BRK.B.NYS" });
    expect(vi.mocked(deleteHolding)).toHaveBeenCalledWith("BRK.B.NYS");
  });

  it("decodes percent-encoded slash ticker for delete", async () => {
    vi.mocked(deleteHolding).mockResolvedValueOnce(true);

    const response = await DELETE(makeDeleteRequest(), {
      params: { ticker: ["BRK%2FB.NYS"] },
    });

    expect(response.status).toBe(200);
    expect(vi.mocked(deleteHolding)).toHaveBeenCalledWith("BRK.B.NYS");
  });

  it("applies admin guard once for patch passthrough", async () => {
    vi.mocked(updateHolding).mockResolvedValueOnce({
      ticker: "BRK.B.NYS",
      quantity: 3,
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

    const response = await PATCH(makePatchRequest({ quantity: 3 }), {
      params: { ticker: ["BRK", "B.NYS"] },
    });

    expect(response.status).toBe(200);
    expect(vi.mocked(requireAdminAuth)).toHaveBeenCalledTimes(1);
  });
});
