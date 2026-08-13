import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

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
    downloadStorageBytes: vi.fn(),
    downloadStorageJson: vi.fn(),
    fetchReportIndexEntry: vi.fn(() => Promise.resolve(null)),
  };
});

import { GET } from "@/app/api/reports/detail/route";
import { decisionPayloadHashV0 } from "@/lib/decision-board-schema";
import { parseVerifiedDecisionBoardReport } from "@/lib/decision-board-schema";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import {
  downloadStorageBytes,
  downloadStorageJson,
  fetchReportIndexEntry,
  SupabaseApiError,
} from "@/lib/supabase-admin";

const CACHE_CONTROL_VALUE = "private, no-store, max-age=0, must-revalidate";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/reports/detail${suffix}`);
}

const decisionFixture = () =>
  JSON.parse(
    readFileSync(
      fileURLToPath(
        new URL(
          "../../../../../../../tests/fixtures/decision_board/published-entry.json",
          import.meta.url,
        ),
      ),
      "utf8",
    ),
  ) as Record<string, unknown>;

function mockDecisionBytes(report: Record<string, unknown>): void {
  vi.mocked(downloadStorageBytes).mockResolvedValueOnce(
    new TextEncoder().encode(JSON.stringify(report)),
  );
}

const DECISION_DIGEST = "e".repeat(64);
const DECISION_KEY =
  "2026/08/2026-08-06.decision-board.entry." +
  `entry-2026-08-06T010000Z.${DECISION_DIGEST}.json`;

function mockDecisionIndex(): void {
  vi.mocked(fetchReportIndexEntry).mockResolvedValueOnce({
    bucket_id: "reports",
    report_key: DECISION_KEY,
    report_type: "decision-board",
    report_date: "2026-08-06",
    duplicate_index: 0,
    generated_at: null,
    summary: null,
    tickers: [],
    tickers_hydrated: false,
    run_kind: "ENTRY",
    run_id: "entry-2026-08-06T010000Z",
    idempotency_key: `sha256:${DECISION_DIGEST}`,
    decision_created_at: "2026-08-06T01:00:05Z",
  });
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
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
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
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
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
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("Local only");
  });

  it("returns 400 for invalid query params", async () => {
    const response = await GET(makeRequest());
    const payload = (await response.json()) as {
      error: string;
      details?: { fieldErrors?: { key?: string[] } };
    };

    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("Invalid query parameters");
    expect(payload.details?.fieldErrors?.key).toBeDefined();
    expect(vi.mocked(downloadStorageJson)).not.toHaveBeenCalled();
  });

  it("returns 400 for invalid report key format", async () => {
    const response = await GET(makeRequest("key=not-a-report-key"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
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
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
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
    const key = encodeURIComponent("2026/02/2026-02-14.entry.json");

    const response = await GET(makeRequest(`key=${key}`));
    const payload = (await response.json()) as {
      key: string;
      report: Record<string, unknown>;
    };

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.key).toBe("2026/02/2026-02-14.entry.json");
    expect(payload.report).toEqual(report);
  });

  it("downloads report detail from the requested bucket", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValueOnce({
      bucket_id: "custom-reports",
      report_key: "2026/02/2026-02-14.buy.json",
      report_type: "buy",
      report_date: "2026-02-14",
      duplicate_index: 0,
      generated_at: "2026-02-14T00:00:00Z",
      summary: null,
      tickers: ["AAPL.US"],
      tickers_hydrated: true,
    });
    const report = {
      generated_at: "2026-02-14T00:00:00Z",
      tickers: ["AAPL.US"],
    };
    vi.mocked(downloadStorageJson).mockResolvedValueOnce(report);
    const key = encodeURIComponent("2026/02/2026-02-14.buy.json");

    const response = await GET(makeRequest(`key=${key}&bucket=custom-reports`));

    expect(response.status).toBe(200);
    expect(vi.mocked(fetchReportIndexEntry)).toHaveBeenCalledWith(
      "2026/02/2026-02-14.buy.json",
      "custom-reports",
    );
    expect(vi.mocked(downloadStorageJson)).toHaveBeenCalledWith(
      "custom-reports",
      "2026/02/2026-02-14.buy.json",
    );
  });

  it("rejects explicit bucket detail when the index has no matching row", async () => {
    vi.mocked(fetchReportIndexEntry).mockResolvedValueOnce(null);
    const key = encodeURIComponent("2026/02/2026-02-14.buy.json");

    const response = await GET(makeRequest(`key=${key}&bucket=private-bucket`));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(404);
    expect(payload.error).toBe("Report not found");
    expect(vi.mocked(downloadStorageJson)).not.toHaveBeenCalled();
  });

  it("returns AI brief detail when key is valid", async () => {
    const report = {
      schema: "sab.ai_brief.v1",
      type: "ai_brief",
      recommendations: [{ ticker: "AAPL.NAS" }],
    };
    vi.mocked(downloadStorageJson).mockResolvedValueOnce(report);
    const key = encodeURIComponent("2026/05/2026-05-05.ai-brief.json");

    const response = await GET(makeRequest(`key=${key}`));
    const payload = (await response.json()) as {
      key: string;
      report: Record<string, unknown>;
    };

    expect(response.status).toBe(200);
    expect(payload.key).toBe("2026/05/2026-05-05.ai-brief.json");
    expect(payload.report).toEqual(report);
  });

  it("returns a verified and exact-key-bound Decision Board envelope", async () => {
    const report = decisionFixture();
    mockDecisionIndex();
    mockDecisionBytes(report);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );
    const payload = (await response.json()) as { report: unknown };

    expect(response.status).toBe(200);
    expect(payload.report).toMatchObject({
      schema_version: "decision-board.v0",
      run_id: "entry-2026-08-06T010000Z",
      run_kind: "ENTRY",
      status: "PUBLISHED",
    });
    expect(payload.report).not.toHaveProperty("metadata");
    await expect(
      parseVerifiedDecisionBoardReport(payload.report),
    ).resolves.toEqual(payload.report);
    expect(vi.mocked(downloadStorageJson)).not.toHaveBeenCalled();
  });

  it("rejects a whitespace-normalized Decision Board key", async () => {
    const response = await GET(
      makeRequest(`key=${encodeURIComponent(` ${DECISION_KEY} `)}`),
    );

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: "Invalid report key format",
    });
    expect(vi.mocked(fetchReportIndexEntry)).not.toHaveBeenCalled();
    expect(vi.mocked(downloadStorageJson)).not.toHaveBeenCalled();
  });

  it("returns sanitized 422 for a stale Decision Board payload hash", async () => {
    const report = decisionFixture() as {
      decision_payload: { items: Array<{ action?: string }> };
    };
    report.decision_payload.items[0].action = "AVOID";
    mockDecisionIndex();
    mockDecisionBytes(report);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );
    const payload = (await response.json()) as Record<string, unknown>;

    expect(response.status).toBe(422);
    expect(payload).toEqual({
      error: "Decision Board report failed validation",
      code: "invalid_decision_board_report",
    });
    expect(JSON.stringify(payload)).not.toContain("AVOID");
  });

  it("returns sanitized 422 when envelope identity does not match its key", async () => {
    const report = decisionFixture();
    report.run_id = "forged-run";
    mockDecisionIndex();
    mockDecisionBytes(report);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({
      error: "Decision Board report failed validation",
      code: "invalid_decision_board_report",
    });
  });

  it("returns sanitized 422 for privacy-bearing Decision Board metadata", async () => {
    const report = decisionFixture();
    report.metadata = {
      compiler_version: "fixture-v0",
      account_id: "PRIVATE-SENTINEL",
    };
    mockDecisionIndex();
    mockDecisionBytes(report);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );
    const responseText = await response.text();

    expect(response.status).toBe(422);
    expect(responseText).not.toContain("PRIVATE-SENTINEL");
    expect(JSON.parse(responseText)).toEqual({
      error: "Decision Board report failed validation",
      code: "invalid_decision_board_report",
    });
  });

  it("rejects alternate private field casing in Decision Board metadata", async () => {
    const report = decisionFixture();
    report.metadata = {
      compiler_version: "fixture-v0",
      providerException: "PRIVATE-PROVIDER-SENTINEL",
    };
    mockDecisionIndex();
    mockDecisionBytes(report);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );
    const responseText = await response.text();

    expect(response.status).toBe(422);
    expect(responseText).not.toContain("PRIVATE-PROVIDER-SENTINEL");
  });

  it.each([
    "PRIVATE-VALUE-SENTINEL",
    "/Users/example/private/report.json",
    "Traceback (most recent call last): provider failed",
    "OpenAI provider error: upstream token rejected",
  ])("returns sanitized 422 for private value %s", async (privateValue) => {
    const report = decisionFixture();
    report.metadata = { diagnostic: privateValue };
    mockDecisionIndex();
    mockDecisionBytes(report);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );
    const responseText = await response.text();

    expect(response.status).toBe(422);
    expect(responseText).not.toContain(privateValue);
    expect(JSON.parse(responseText)).toEqual({
      error: "Decision Board report failed validation",
      code: "invalid_decision_board_report",
    });
  });

  it("reconstructs public issue messages and drops issue path/metadata", async () => {
    const report = decisionFixture() as {
      decision_payload: {
        items: Array<{ issues: Array<Record<string, unknown>> }>;
      };
    };
    report.decision_payload.items[2].issues = [
      {
        code: "EVIDENCE_UNCLEAR",
        message: "Producer-owned issue wording.",
        path: ["validated_claims"],
        metadata: { source: "compiler" },
      },
    ];
    (report as Record<string, unknown>).decision_payload_hash =
      await decisionPayloadHashV0(report.decision_payload);
    mockDecisionIndex();
    mockDecisionBytes(report as Record<string, unknown>);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );
    const payload = (await response.json()) as {
      report: {
        decision_payload: { items: Array<{ issues: unknown[] }> };
      };
    };

    expect(response.status).toBe(200);
    expect(payload.report.decision_payload.items[2].issues).toEqual([
      {
        code: "EVIDENCE_UNCLEAR",
        message: "Decision Board issue EVIDENCE_UNCLEAR.",
      },
    ]);
    expect(JSON.stringify(payload)).not.toContain(
      "Producer-owned issue wording",
    );
    expect(JSON.stringify(payload)).not.toContain("validated_claims");
  });

  it("returns sanitized 422 for duplicate-key Decision Board JSON", async () => {
    mockDecisionIndex();
    vi.mocked(downloadStorageBytes).mockResolvedValueOnce(
      new TextEncoder().encode(
        '{"schema_version":"decision-board.v0","schema_version":"decision-board.v0"}',
      ),
    );

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({
      error: "Decision Board report failed validation",
      code: "invalid_decision_board_report",
    });
  });

  it.each([
    { name: "array", bytes: new TextEncoder().encode("[]") },
    { name: "malformed JSON", bytes: new TextEncoder().encode("{bad}") },
    { name: "invalid UTF-8", bytes: new Uint8Array([0x7b, 0xff, 0x7d]) },
  ])("returns sanitized 422 for $name content", async ({ bytes }) => {
    mockDecisionIndex();
    vi.mocked(downloadStorageBytes).mockResolvedValueOnce(bytes);

    const response = await GET(
      makeRequest(`key=${encodeURIComponent(DECISION_KEY)}`),
    );

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({
      error: "Decision Board report failed validation",
      code: "invalid_decision_board_report",
    });
  });

  it("returns 500 for unknown errors", async () => {
    vi.mocked(downloadStorageJson).mockRejectedValueOnce(new Error("boom"));
    const key = encodeURIComponent("2026/02/2026-02-14.buy.json");

    const response = await GET(makeRequest(`key=${key}`));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(500);
    expect(response.headers.get("cache-control")).toBe(CACHE_CONTROL_VALUE);
    expect(payload.error).toBe("boom");
  });
});
