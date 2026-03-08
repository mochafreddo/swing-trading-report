import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/admin-auth", () => {
  class AdminAuthError extends Error {
    status: number;
    headers?: HeadersInit;

    constructor(message: string, status: number, headers?: HeadersInit) {
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

import { POST } from "@/app/api/run/route";

function makeRequest(
  payload: unknown,
  headers?: Record<string, string>,
): NextRequest {
  return new NextRequest("http://localhost:55300/api/run", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      host: "localhost:55300",
      origin: "http://localhost:55300",
      ...headers,
    },
    body: JSON.stringify(payload),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("SAB_ENFORCE_LOCAL_REQUEST", "1");
  vi.stubEnv("RUN_DISPATCH_ENABLED", "1");
  vi.stubEnv("GITHUB_OWNER", "octo");
  vi.stubEnv("GITHUB_REPO", "swing-trading-report");
  vi.stubEnv("GITHUB_PAT", "ghp_test_token");
  vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
  vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test_key");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("/api/run integration", () => {
  it("validates payload and dispatches GitHub workflow with expected body", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = new URL(String(input));
        if (url.pathname.endsWith("/rest/v1/runtime_state")) {
          return new Response("", { status: 201 });
        }
        if (url.pathname.endsWith("/rest/v1/rpc/claim_runtime_state_lock")) {
          return new Response(
            JSON.stringify([
              {
                acquired: true,
                expires_at: "2026-03-08T10:00:30.000Z",
              },
            ]),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }
        if (url.hostname === "api.github.com") {
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${url.toString()}`);
      });

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "kis",
        universe: "both",
      }),
    );
    const payload = (await response.json()) as {
      dispatched: boolean;
      workflow: string;
      workflowFile: string;
      ref: string;
    };

    expect(response.status).toBe(202);
    expect(payload.dispatched).toBe(true);
    expect(payload.workflow).toBe("scan");
    expect(payload.workflowFile).toBe("scan.yml");
    expect(payload.ref).toBe("main");

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const githubCall = fetchSpy.mock.calls.find(([requestUrlRaw]) => {
      const requestUrl = new URL(String(requestUrlRaw));
      return requestUrl.hostname === "api.github.com";
    });
    const [requestUrlRaw, requestInit] = githubCall ?? [];
    const requestUrl = new URL(String(requestUrlRaw));
    expect(requestUrl.hostname).toBe("api.github.com");
    expect(requestUrl.pathname).toBe(
      "/repos/octo/swing-trading-report/actions/workflows/scan.yml/dispatches",
    );

    const body = JSON.parse(String(requestInit?.body)) as {
      ref: string;
      inputs: { provider: string; universe: string };
    };
    expect(body).toEqual({
      ref: "main",
      inputs: {
        provider: "kis",
        universe: "both",
      },
    });
  });

  it("returns 400 before dispatch when schema validation fails", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const response = await POST(
      makeRequest({
        workflow: "scan",
        provider: "pykrx",
        universe: "US",
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toContain("provider=pykrx supports only universe=KR");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("accepts unsafe request with sec-fetch-site same-origin and no origin", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = new URL(String(input));
        if (url.pathname.endsWith("/rest/v1/runtime_state")) {
          return new Response("", { status: 201 });
        }
        if (url.pathname.endsWith("/rest/v1/rpc/claim_runtime_state_lock")) {
          return new Response(
            JSON.stringify([
              {
                acquired: true,
                expires_at: "2026-03-08T10:00:30.000Z",
              },
            ]),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }
        if (url.hostname === "api.github.com") {
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${url.toString()}`);
      });

    const response = await POST(
      makeRequest(
        {
          workflow: "scan",
          provider: "kis",
          universe: "both",
        },
        {
          origin: "",
          "sec-fetch-site": "same-origin",
        },
      ),
    );

    expect(response.status).toBe(202);
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});
