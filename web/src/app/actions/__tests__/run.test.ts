import { beforeEach, describe, expect, it, vi } from "vitest";

const { requireAdminActionSession, dispatchWorkflow } = vi.hoisted(() => ({
  requireAdminActionSession: vi.fn(),
  dispatchWorkflow: vi.fn(),
}));

vi.mock("@/lib/admin-action-auth", () => ({
  requireAdminActionSession,
}));

vi.mock("@/lib/github-actions", () => ({
  GitHubDispatchError: class GitHubDispatchError extends Error {
    constructor(
      message: string,
      public readonly status: number,
    ) {
      super(message);
    }
  },
  dispatchWorkflow,
}));

import { dispatchRunAction } from "@/app/actions/run";
import { PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE } from "@/lib/run-dispatch-policy";

describe("run actions", () => {
  beforeEach(() => {
    requireAdminActionSession.mockReset();
    dispatchWorkflow.mockReset();
  });

  it("dispatches a valid scan workflow", async () => {
    dispatchWorkflow.mockResolvedValue({
      dispatched: true,
      workflow: "scan",
      workflowFile: "scan.yml",
      workflowUrl: "https://github.com/owner/repo/actions/workflows/scan.yml",
      actionsUrl: "https://github.com/owner/repo/actions",
      ref: "main",
    });

    await expect(
      dispatchRunAction({
        workflow: "scan",
        provider: "pykrx",
        universe: "KR",
      }),
    ).resolves.toEqual({
      ok: true,
      result: {
        dispatched: true,
        workflow: "scan",
        workflowFile: "scan.yml",
        workflowUrl: "https://github.com/owner/repo/actions/workflows/scan.yml",
        actionsUrl: "https://github.com/owner/repo/actions",
        ref: "main",
      },
    });

    expect(dispatchWorkflow).toHaveBeenCalledWith({
      workflow: "scan",
      provider: "pykrx",
      universe: "KR",
    });
  });

  it("returns validation errors for invalid scan universes", async () => {
    await expect(
      dispatchRunAction({
        workflow: "scan",
        provider: "pykrx",
        universe: "US",
      }),
    ).resolves.toEqual({
      ok: false,
      error: PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
    });

    expect(dispatchWorkflow).not.toHaveBeenCalled();
  });
});
