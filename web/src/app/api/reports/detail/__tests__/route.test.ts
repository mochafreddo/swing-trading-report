import { beforeEach, describe, expect, it, vi } from "vitest";
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
    downloadStorageJson: vi.fn(),
  };
});

import { GET } from "@/app/api/reports/detail/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { downloadStorageJson, SupabaseApiError } from "@/lib/supabase-admin";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/reports/detail${suffix}`);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GET /api/reports/detail route", () => {
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
    expect(vi.mocked(assertSameOrigin)).not.toHaveBeenCalled();
    expect(vi.mocked(assertLocalRequest)).not.toHaveBeenCalled();
  });

  it("maps same-origin guard failures to 403", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await GET(makeRequest());
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
    expect(vi.mocked(assertLocalRequest)).not.toHaveBeenCalled();
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

  it("returns 400 for invalid query params", async () => {
    const response = await GET(makeRequest());
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { key?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid query parameters");
    expect(payload.details?.fieldErrors?.key).toBeDefined();
    expect(vi.mocked(downloadStorageJson)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid report key format", async () => {
    const response = await GET(makeRequest("key=not-a-report-key"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid report key format");
    expect(vi.mocked(downloadStorageJson)).not.toHaveBeenCalled();
  });

  it("returns 404 when report object is missing", async () => {
    vi.mocked(downloadStorageJson).mockRejectedValueOnce(
      new SupabaseApiError("missing", 404),
    );
    const key = encodeURIComponent("2026/02/2026-02-14.buy.json");

    const response = await GET(makeRequest(`key=${key}`));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(404);
    expect(payload.error).toBe("Report not found");
    expect(vi.mocked(downloadStorageJson)).toHaveBeenCalledWith(
      "reports",
      "2026/02/2026-02-14.buy.json",
    );
  });

  it("returns report detail when key is valid", async () => {
    const report = {
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    };
    vi.mocked(downloadStorageJson).mockResolvedValueOnce(report);
    const key = encodeURIComponent("2026/02/2026-02-14.buy.json");

    const response = await GET(makeRequest(`key=${key}`));
    const payload = (await response.json()) as {
      key: string;
      report: Record<string, unknown>;
    };

    expect(response.status).toBe(200);
    expect(payload.key).toBe("2026/02/2026-02-14.buy.json");
    expect(payload.report).toEqual(report);
  });

  it("returns 500 for unknown errors", async () => {
    vi.mocked(downloadStorageJson).mockRejectedValueOnce(new Error("boom"));
    const key = encodeURIComponent("2026/02/2026-02-14.buy.json");

    const response = await GET(makeRequest(`key=${key}`));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(500);
    expect(payload.error).toBe("boom");
  });
});
