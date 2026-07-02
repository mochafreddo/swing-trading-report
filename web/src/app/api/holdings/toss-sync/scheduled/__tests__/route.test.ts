import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

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

const MOCK_RUNTIME_DEPS = { qa: "runtime-deps" };

vi.mock("@/lib/toss/holdings-sync-service", () => ({
  buildTossHoldingsSyncDependenciesFromEnv: vi.fn(() => MOCK_RUNTIME_DEPS),
  runScheduledTossAutoApply: vi.fn(async () => ({
    mode: "auto-apply",
    status: "unchanged",
    diffHash:
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    applyBlocked: false,
    summary: {
      incomingCount: 1,
      createCount: 0,
      updateCount: 0,
      deleteCount: 0,
      unchangedCount: 1,
      createTickers: [],
      updateTickers: [],
      deleteTickers: [],
    },
    changes: { create: [], update: [], delete: [], unchanged: [] },
    blockedRows: [],
    targetRows: [],
  })),
}));

import { POST } from "@/app/api/holdings/toss-sync/scheduled/route";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import {
  buildTossHoldingsSyncDependenciesFromEnv,
  runScheduledTossAutoApply,
} from "@/lib/toss/holdings-sync-service";

const ORIGINAL_ENV = { ...process.env };

function makePostRequest(
  body: object,
  headers: Record<string, string> = {},
): NextRequest {
  return new NextRequest(
    "http://localhost:55300/api/holdings/toss-sync/scheduled",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://localhost:55300",
        host: "localhost:55300",
        ...headers,
      },
      body: JSON.stringify(body),
    },
  );
}

describe("/api/holdings/toss-sync/scheduled route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    process.env = {
      ...ORIGINAL_ENV,
      TOSS_SYNC_JOB_TOKEN: "job-token",
      TOSS_SYNC_AUTO_APPLY_ENABLED: "1",
    };
  });

  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("rejects missing bearer token", async () => {
    const response = await POST(makePostRequest({ mode: "auto-apply" }));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(401);
    expect(payload.error).toBe("Unauthorized Toss sync job");
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("rejects invalid bearer token", async () => {
    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer wrong-token" },
      ),
    );

    expect(response.status).toBe(401);
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("rejects invalid payloads with the scheduled route contract", async () => {
    const response = await POST(
      makePostRequest(
        { mode: "dry-run" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: Record<string, string[]> };
    };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid scheduled Toss holdings sync payload");
    expect(payload.details?.fieldErrors?.mode).toBeDefined();
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("rejects non-local requests before running sync", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Local only");
    expect(runScheduledTossAutoApply).not.toHaveBeenCalled();
  });

  it("passes disabled flag through when auto apply is not enabled", async () => {
    process.env.TOSS_SYNC_AUTO_APPLY_ENABLED = "0";
    vi.mocked(runScheduledTossAutoApply).mockResolvedValueOnce({
      mode: "auto-apply",
      status: "disabled",
      diffHash: "",
      applyBlocked: false,
      summary: {
        incomingCount: 0,
        createCount: 0,
        updateCount: 0,
        deleteCount: 0,
        unchangedCount: 0,
        createTickers: [],
        updateTickers: [],
        deleteTickers: [],
      },
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
    });

    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as {
      status: string;
      applyBlocked: boolean;
    };

    expect(response.status).toBe(200);
    expect(payload.status).toBe("disabled");
    expect(payload.applyBlocked).toBe(false);
    expect(runScheduledTossAutoApply).toHaveBeenCalledWith(
      {
        autoApplyEnabled: false,
      },
      MOCK_RUNTIME_DEPS,
    );
  });

  it("returns bounded auto-sync result for valid local job requests", async () => {
    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as {
      status: string;
      diffHash: string;
      accessToken?: string;
      account?: string;
    };

    expect(response.status).toBe(200);
    expect(payload.status).toBe("unchanged");
    expect(payload.diffHash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(payload).not.toHaveProperty("accessToken");
    expect(payload).not.toHaveProperty("account");
    expect(buildTossHoldingsSyncDependenciesFromEnv).toHaveBeenCalledTimes(1);
    expect(runScheduledTossAutoApply).toHaveBeenCalledWith(
      {
        autoApplyEnabled: true,
      },
      MOCK_RUNTIME_DEPS,
    );
  });

  it("returns a stable scheduled error result when the sync service throws", async () => {
    vi.mocked(runScheduledTossAutoApply).mockRejectedValueOnce(
      new Error("boom"),
    );

    const response = await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );
    const payload = (await response.json()) as {
      mode: string;
      status: string;
      error: string;
      diffHash: string;
      applyBlocked: boolean;
      blockedRows: unknown[];
      targetRows: unknown[];
      summary: {
        incomingCount: number;
        createCount: number;
        updateCount: number;
        deleteCount: number;
        unchangedCount: number;
        createTickers: string[];
        updateTickers: string[];
        deleteTickers: string[];
      };
      changes: {
        create: unknown[];
        update: unknown[];
        delete: unknown[];
        unchanged: unknown[];
      };
    };

    expect(response.status).toBe(500);
    expect(payload).toEqual({
      mode: "auto-apply",
      status: "error",
      error: "Scheduled Toss holdings sync failed",
      diffHash: "",
      applyBlocked: false,
      summary: {
        incomingCount: 0,
        createCount: 0,
        updateCount: 0,
        deleteCount: 0,
        unchangedCount: 0,
        createTickers: [],
        updateTickers: [],
        deleteTickers: [],
      },
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
    });
  });

  it("logs only a stable scheduled failure category when the sync service throws", async () => {
    const consoleErrorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    vi.mocked(runScheduledTossAutoApply).mockRejectedValueOnce(
      new Error("Toss accountSeq 1234567890 upstream failure"),
    );

    await POST(
      makePostRequest(
        { mode: "auto-apply" },
        { authorization: "Bearer job-token" },
      ),
    );

    const logged = JSON.stringify(consoleErrorSpy.mock.calls);
    expect(logged).toContain("scheduled_toss_holdings_sync");
    expect(logged).not.toContain("accountSeq");
    expect(logged).not.toContain("1234567890");
  });
});
