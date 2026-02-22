import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

import { POST } from "@/app/api/run/route";

function makeRequest(payload: object): NextRequest {
  return new NextRequest("http://localhost:55300/api/run", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
    },
    body: JSON.stringify(payload),
  });
}

let previousRunDispatchEnabled: string | undefined;

beforeEach(() => {
  previousRunDispatchEnabled = process.env.RUN_DISPATCH_ENABLED;
  process.env.RUN_DISPATCH_ENABLED = "0";
  vi.restoreAllMocks();
});

afterEach(() => {
  if (typeof previousRunDispatchEnabled === "string") {
    process.env.RUN_DISPATCH_ENABLED = previousRunDispatchEnabled;
    return;
  }
  delete process.env.RUN_DISPATCH_ENABLED;
});

describe("POST /api/run feature flag", () => {
  it("returns 503 when run dispatch is disabled", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "KR",
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(503);
    expect(payload.error).toContain("Run dispatch is disabled");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
