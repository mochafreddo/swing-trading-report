import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  buildWorkflowDispatchRequest,
  dispatchWorkflow,
  GitHubDispatchError,
} from "@/lib/github-actions";

beforeAll(() => {
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_SECRET_KEY = "sb_secret_server_key";
  process.env.RUN_DISPATCH_ENABLED = "1";
  process.env.GITHUB_OWNER = "owner";
  process.env.GITHUB_REPO = "repo";
  process.env.GITHUB_PAT = "ghp_test_token";
});

afterEach(() => {
  vi.restoreAllMocks();
});

beforeEach(() => {
  process.env.RUN_DISPATCH_ENABLED = "1";
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
  it("returns 503 when run dispatch feature is disabled", async () => {
    process.env.RUN_DISPATCH_ENABLED = "0";
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(
      dispatchWorkflow({
        workflow: "scan",
        provider: "kis",
        universe: "both",
      }),
    ).rejects.toMatchObject({
      status: 503,
    });

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("enables run dispatch in legacy mode when flag is unset and github env exists", async () => {
    delete process.env.RUN_DISPATCH_ENABLED;
    const mockFetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));

    const result = await dispatchWorkflow({
      workflow: "scan",
      provider: "kis",
      universe: "both",
    });

    expect(result.dispatched).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("throws when RUN_DISPATCH_ENABLED has an invalid value", async () => {
    process.env.RUN_DISPATCH_ENABLED = "true";
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    await expect(
      dispatchWorkflow({
        workflow: "scan",
        provider: "kis",
        universe: "both",
      }),
    ).rejects.toMatchObject({
      status: 500,
    });

    expect(fetchSpy).not.toHaveBeenCalled();
  });

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
