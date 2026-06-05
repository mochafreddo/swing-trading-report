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

    constructor(
      message = "Holdings API is only available from local host",
      status = 403,
    ) {
      super(message);
      this.status = status;
    }
  }

  return {
    LocalRequestGuardError,
    assertLocalRequest: vi.fn(() => undefined),
  };
});

vi.mock("@/lib/github-actions", () => {
  class GitHubDispatchError extends Error {
    status: number;

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }

  return {
    GitHubDispatchError,
    dispatchWorkflow: vi.fn(),
  };
});

import { POST } from "@/app/api/run/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { dispatchWorkflow, GitHubDispatchError } from "@/lib/github-actions";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

function makeRequest(payload: object | string): NextRequest {
  const body = typeof payload === "string" ? payload : JSON.stringify(payload);
  return new NextRequest("http://localhost:55300/api/run", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
      "x-request-id": "run-route-test-request",
    },
    body,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/run route", () => {
  it("returns 400 for invalid JSON", async () => {
    const response = await POST(makeRequest("{"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Request body must be valid JSON");
    expect(vi.mocked(dispatchWorkflow)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid payload", async () => {
    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "pykrx",
        universe: "both",
      }),
    );
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { universe?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toContain("pykrx");
    expect(payload.details?.fieldErrors?.universe?.[0]).toContain("pykrx");
  });

  it("maps admin auth error status and headers", async () => {
    const authError = new AdminAuthError("Unauthorized");
    (authError as { headers: HeadersInit }).headers = {
      "x-auth-required": "1",
    };
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(authError);

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "KR",
      }),
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

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "KR",
      }),
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

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "KR",
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
  });

  it("logs successful workflow dispatch with request correlation", async () => {
    const infoSpy = vi
      .spyOn(console, "info")
      .mockImplementation(() => undefined);
    vi.mocked(dispatchWorkflow).mockResolvedValueOnce({
      dispatched: true,
      workflow: "scan",
      workflowFile: "scan.yml",
      workflowUrl: "https://github.com/example/repo/actions/workflows/scan.yml",
      actionsUrl: "https://github.com/example/repo/actions",
      ref: "main",
    });

    try {
      const response = await POST(
        makeRequest({
          workflow: "scan",
          provider: "kis",
          universe: "US",
        }),
      );

      expect(response.status).toBe(202);
      expect(response.headers.get("x-request-id")).toBe(
        "run-route-test-request",
      );
      expect(infoSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "web_api_request_completed",
          component: "web",
          request_id: "run-route-test-request",
          route: "/api/run",
          method: "POST",
          operation: "dispatch_workflow",
          status: "success",
          status_code: 202,
          dependency: "github_actions",
          workflow: "scan",
          provider: "kis",
          universe: "US",
        }),
      );
    } finally {
      infoSpy.mockRestore();
    }
  });

  it("logs GitHub dispatch failures with dependency context", async () => {
    const errorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    vi.mocked(dispatchWorkflow).mockRejectedValueOnce(
      new GitHubDispatchError("GitHub API unavailable", 503),
    );

    try {
      const response = await POST(
        makeRequest({
          workflow: "scan",
          provider: "kis",
          universe: "US",
        }),
      );

      expect(response.status).toBe(503);
      expect(response.headers.get("x-request-id")).toBe(
        "run-route-test-request",
      );
      expect(errorSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          event: "web_api_request_failed",
          component: "web",
          request_id: "run-route-test-request",
          route: "/api/run",
          method: "POST",
          operation: "dispatch_workflow",
          status: "failed",
          status_code: 503,
          dependency: "github_actions",
          workflow: "scan",
          provider: "kis",
          universe: "US",
          error_type: "GitHubDispatchError",
          retryable: true,
        }),
      );
    } finally {
      errorSpy.mockRestore();
    }
  });

  it("maps GitHub 4xx errors as-is", async () => {
    vi.mocked(dispatchWorkflow).mockRejectedValueOnce(
      new GitHubDispatchError("Invalid workflow ref", 422),
    );

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "US",
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(422);
    expect(payload.error).toBe("Invalid workflow ref");
  });

  it("maps GitHub 5xx errors as-is", async () => {
    vi.mocked(dispatchWorkflow).mockRejectedValueOnce(
      new GitHubDispatchError("GitHub API unavailable", 503),
    );

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "US",
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(503);
    expect(payload.error).toBe("GitHub API unavailable");
  });
});
