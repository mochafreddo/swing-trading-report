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

vi.mock("@/lib/ticker-directory", () => ({
  searchTickerDirectory: vi.fn(),
}));

import { GET } from "@/app/api/tickers/search/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { searchTickerDirectory } from "@/lib/ticker-directory";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/tickers/search${suffix}`);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GET /api/tickers/search", () => {
  it("maps admin auth failures with status and headers", async () => {
    const authError = new AdminAuthError("Unauthorized");
    (authError as { headers: HeadersInit }).headers = {
      "x-auth-required": "1",
    };
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(authError);

    const response = await GET(makeRequest("q=abbv"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(401);
    expect(response.headers.get("x-auth-required")).toBe("1");
    expect(payload.error).toBe("Unauthorized");
  });

  it("maps local-request guard failures to 403", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await GET(makeRequest("q=abbv"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
  });

  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await GET(makeRequest("q=abbv"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
  });

  it("returns 400 for invalid query params", async () => {
    const response = await GET(makeRequest("q="));
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { q?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid query parameters");
    expect(payload.details?.fieldErrors?.q).toBeDefined();
    expect(vi.mocked(searchTickerDirectory)).not.toHaveBeenCalled();
  });

  it("returns search results", async () => {
    vi.mocked(searchTickerDirectory).mockResolvedValueOnce({
      q: "abbv",
      results: [
        {
          ticker: "ABBV.NYS",
          name: "애브비",
        },
      ],
      directory: {
        builtAtMs: 1740700000000,
        sourceReports: 12,
      },
    });

    const response = await GET(makeRequest("q=abbv&limit=5"));
    const payload = (await response.json()) as {
      q: string;
      results: Array<{ ticker: string; name: string | null }>;
      directory: { builtAtMs: number; sourceReports: number };
    };

    expect(response.status).toBe(200);
    expect(vi.mocked(searchTickerDirectory)).toHaveBeenCalledWith({
      q: "abbv",
      limit: 5,
    });
    expect(payload.q).toBe("abbv");
    expect(payload.results).toEqual([
      {
        ticker: "ABBV.NYS",
        name: "애브비",
      },
    ]);
    expect(payload.directory.sourceReports).toBe(12);
  });
});
