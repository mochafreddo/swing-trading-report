import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/env.server", () => ({
  getSupabaseEnv: vi.fn(() => ({
    SUPABASE_URL: "https://example.supabase.co",
    SUPABASE_API_KEY: "sb_secret_test_key",
    SUPABASE_REPORTS_BUCKET: "reports",
    REPORT_RETENTION_DAYS: 30,
  })),
}));

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
    fetchReportIndexPage: vi.fn(),
    downloadStorageJson: vi.fn(),
    upsertReportIndexEntry: vi.fn(),
  };
});

import { GET } from "@/app/api/reports/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { fetchReportIndexPage, SupabaseApiError } from "@/lib/supabase-admin";

const CACHE_CONTROL_VALUE = "private, no-store, max-age=0, must-revalidate";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/reports${suffix}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("REPORT_SEARCH_WINDOW", "100");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GET /api/reports route", () => {
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
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("Unauthorized");
  });

  it("maps local-request guard failures to 403", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await GET(makeRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("Local only");
  });

  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await GET(makeRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("Cross-site blocked");
  });

  it("returns 400 for invalid query params", async () => {
    const response = await GET(makeRequest("limit=0&type=buy"));
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { limit?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("Invalid query parameters");
    expect(payload.details?.fieldErrors?.limit).toBeDefined();
    expect(vi.mocked(fetchReportIndexPage)).not.toHaveBeenCalled();
  });

  it("requires exact runKind for Decision Board lists", async () => {
    for (const query of [
      "type=decision-board",
      "type=decision-board&runKind=entry",
      "type=decision-board&runKind=SELL",
    ]) {
      const response = await GET(makeRequest(query));
      expect(response.status).toBe(400);
    }
    expect(vi.mocked(fetchReportIndexPage)).not.toHaveBeenCalled();
  });

  it("rejects runKind for legacy report types", async () => {
    const response = await GET(makeRequest("type=buy&runKind=ENTRY"));

    expect(response.status).toBe(400);
    expect(vi.mocked(fetchReportIndexPage)).not.toHaveBeenCalled();
  });

  it("returns 500 when supabase call fails", async () => {
    vi.mocked(fetchReportIndexPage).mockRejectedValueOnce(
      new SupabaseApiError("storage unavailable", 503),
    );

    const response = await GET(makeRequest("type=buy&limit=10"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(500);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toContain("storage unavailable");
  });

  it("returns 500 for unknown errors", async () => {
    vi.mocked(fetchReportIndexPage).mockRejectedValueOnce(new Error("boom"));

    const response = await GET(makeRequest("type=buy&limit=10"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(500);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("boom");
  });
});
