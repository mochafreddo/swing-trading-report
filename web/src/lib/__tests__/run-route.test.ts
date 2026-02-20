import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE } from "@/lib/run-dispatch-policy";
import type { WorkflowDispatchResult } from "@/lib/types";

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
import { requireAdminAuth } from "@/lib/admin-auth";
import { dispatchWorkflow } from "@/lib/github-actions";
import { assertLocalRequest } from "@/lib/local-request-guard";
import { assertSameOrigin } from "@/lib/same-origin";

function makeRequest(body: unknown): NextRequest {
  return new NextRequest("http://localhost:55300/api/run", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
    },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/run", () => {
  it("returns policy violation message for pykrx + both scan payload", async () => {
    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "pykrx",
        universe: "both",
      }),
    );
    const payload = (await response.json()) as {
      error: string;
      details?: {
        fieldErrors?: {
          universe?: string[];
        };
      };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe(PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE);
    expect(payload.details?.fieldErrors?.universe).toContain(
      PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
    );
    expect(vi.mocked(dispatchWorkflow)).not.toHaveBeenCalled();
    expect(vi.mocked(requireAdminAuth)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(assertSameOrigin)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(assertLocalRequest)).toHaveBeenCalledTimes(1);
  });

  it("dispatches workflow for valid pykrx scan payload", async () => {
    const dispatchMock = vi.mocked(dispatchWorkflow);
    const dispatchResult: WorkflowDispatchResult = {
      dispatched: true,
      workflow: "scan",
      workflowFile: "scan.yml",
      workflowUrl: "https://github.com/owner/repo/actions/workflows/scan.yml",
      actionsUrl: "https://github.com/owner/repo/actions",
      ref: "main",
    };
    dispatchMock.mockResolvedValue(dispatchResult);

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "pykrx",
        universe: "KR",
      }),
    );
    const payload = (await response.json()) as WorkflowDispatchResult;

    expect(response.status).toBe(202);
    expect(payload).toEqual(dispatchResult);
    expect(dispatchMock).toHaveBeenCalledWith({
      workflow: "scan",
      provider: "pykrx",
      universe: "KR",
    });
  });
});
