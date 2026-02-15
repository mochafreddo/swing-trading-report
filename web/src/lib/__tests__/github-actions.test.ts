import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  buildWorkflowDispatchRequest,
  dispatchWorkflow,
  GitHubDispatchError,
} from "@/lib/github-actions";

beforeAll(() => {
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_SECRET_KEY = "sb_secret_server_key";
  process.env.GITHUB_OWNER = "owner";
  process.env.GITHUB_REPO = "repo";
  process.env.GITHUB_PAT = "ghp_test_token";
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("buildWorkflowDispatchRequest", () => {
  it("builds scan dispatch request", () => {
    const request = buildWorkflowDispatchRequest({
      workflow: "scan",
      provider: "kis",
      universe: "KR",
    });

    expect(request.workflowFile).toBe("scan.yml");
    expect(request.body).toEqual({
      ref: "main",
      inputs: {
        provider: "kis",
        universe: "KR",
      },
    });
  });

  it("builds sell dispatch request", () => {
    const request = buildWorkflowDispatchRequest({
      workflow: "sell",
      provider: "pykrx",
    });

    expect(request.workflowFile).toBe("sell.yml");
    expect(request.body).toEqual({
      ref: "main",
      inputs: {
        provider: "pykrx",
      },
    });
  });
});

describe("dispatchWorkflow", () => {
  it("treats 204 as success", async () => {
    const mockFetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    const result = await dispatchWorkflow({
      workflow: "scan",
      provider: "kis",
      universe: "both",
    });

    expect(result.dispatched).toBe(true);
    expect(result.workflowFile).toBe("scan.yml");
    expect(mockFetch).toHaveBeenCalledTimes(1);

    const [url, options] = mockFetch.mock.calls[0];
    expect(String(url)).toContain(
      "/repos/owner/repo/actions/workflows/scan.yml/dispatches",
    );
    expect(options?.method).toBe("POST");
  });

  it("throws when github returns non-204", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ message: "unprocessable" }), {
        status: 422,
      }),
    );

    await expect(
      dispatchWorkflow({
        workflow: "sell",
        provider: "kis",
      }),
    ).rejects.toBeInstanceOf(GitHubDispatchError);
  });
});
