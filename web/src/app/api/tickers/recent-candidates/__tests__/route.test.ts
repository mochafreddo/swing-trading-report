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
  listRecentBuyCandidates: vi.fn(),
}));

import { GET } from "@/app/api/tickers/recent-candidates/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { listRecentBuyCandidates } from "@/lib/ticker-directory";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(
    `http://localhost:55300/api/tickers/recent-candidates${suffix}`,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GET /api/tickers/recent-candidates", () => {
  it("maps admin auth failures with status and headers", async () => {
    const authError = new AdminAuthError("Unauthorized");
    (authError as { headers: HeadersInit }).headers = {
      "x-auth-required": "1",
    };
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(authError);

    const response = await GET(makeRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(401);
    expect(response.headers.get("x-auth-required")).toBe("1");
    expect(payload.error).toBe("Unauthorized");
  });

  it("maps local-request guard failures to 403", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await GET(makeRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
  });

  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await GET(makeRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
  });

  it("returns 400 for invalid query params", async () => {
    const response = await GET(makeRequest("limitCandidates=0"));
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { limitCandidates?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid query parameters");
    expect(payload.details?.fieldErrors?.limitCandidates).toBeDefined();
    expect(vi.mocked(listRecentBuyCandidates)).not.toHaveBeenCalled();
  });

  it("returns recent buy candidates", async () => {
    vi.mocked(listRecentBuyCandidates).mockResolvedValueOnce({
      report: {
        key: "2026/02/2026-02-27.buy.json",
        bucketId: "reports",
        reportDate: "2026-02-27",
      },
      candidates: [
        {
          ticker: "COST.NAS",
          name: "코스트코 홀세일",
          pattern: null,
        },
        {
          ticker: "ETN.NYS",
          name: "이튼",
          pattern: null,
        },
      ],
    });

    const response = await GET(
      makeRequest("limitReports=3&limitCandidates=20"),
    );
    const payload = (await response.json()) as {
      report: {
        key: string;
        bucketId: string;
        reportDate: string | null;
      } | null;
      candidates: Array<{
        ticker: string;
        name: string | null;
        pattern: string | null;
      }>;
    };

    expect(response.status).toBe(200);
    expect(vi.mocked(listRecentBuyCandidates)).toHaveBeenCalledWith({
      limitReports: 3,
      limitCandidates: 20,
    });
    expect(payload.report?.key).toBe("2026/02/2026-02-27.buy.json");
    expect(payload.candidates.map((candidate) => candidate.ticker)).toEqual([
      "COST.NAS",
      "ETN.NYS",
    ]);
  });
});
