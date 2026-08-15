import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/admin-auth", () => {
  class AdminAuthError extends Error {
    status: number;
    headers?: HeadersInit;

    constructor(message = "Unauthorized", status = 401) {
      super(message);
      this.status = status;
    }
  }
  return {
    AdminAuthError,
    requireAdminAuth: vi.fn(async () => undefined),
  };
});

vi.mock("@/lib/same-origin", () => ({
  SameOriginError: class SameOriginError extends Error {
    status = 403;
  },
  assertSameOrigin: vi.fn(),
}));

vi.mock("@/lib/local-request-guard", () => ({
  LocalRequestGuardError: class LocalRequestGuardError extends Error {
    status = 403;
  },
  assertLocalRequest: vi.fn(),
}));

vi.mock("@/lib/decision-board-journal.server", () => ({
  readDecisionBoardJournalStatus: vi.fn(),
}));

import { GET } from "@/app/api/reports/decision-board-journal/route";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { readDecisionBoardJournalStatus } from "@/lib/decision-board-journal.server";
import type { DecisionBoardJournalStatus } from "@/lib/types";

const request = () =>
  new NextRequest("http://localhost:55300/api/reports/decision-board-journal");

describe("GET /api/reports/decision-board-journal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is admin-guarded", async () => {
    vi.mocked(requireAdminAuth).mockRejectedValueOnce(
      new AdminAuthError("Unauthorized"),
    );

    const response = await GET(request());

    expect(response.status).toBe(401);
    expect(readDecisionBoardJournalStatus).not.toHaveBeenCalled();
  });

  it("returns only the sanitized no-store journal status", async () => {
    const status: DecisionBoardJournalStatus = {
      state: "AVAILABLE",
      records: [
        {
          schema_version: "decision-board.v0",
          run_id: "entry-slot-001",
          run_kind: "ENTRY",
          status: "STALE_INCOMPLETE",
          expected_at: "2026-08-11T01:00:00Z",
          started_at: "2026-08-11T01:00:01Z",
          terminal_at: "2026-08-11T02:00:00Z",
          grace_seconds: 60,
          stale_seconds: 300,
          issues: [
            {
              code: "STALE_INCOMPLETE",
              message:
                "Started run did not reach a terminal state before its TTL.",
            },
          ],
          report_file: null,
        },
      ],
    };
    vi.mocked(readDecisionBoardJournalStatus).mockResolvedValueOnce(status);

    const response = await GET(request());

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe(
      "private, no-store, max-age=0, must-revalidate",
    );
    await expect(response.json()).resolves.toEqual(status);
  });
});
