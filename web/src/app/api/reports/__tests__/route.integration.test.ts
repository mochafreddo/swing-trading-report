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

import { GET } from "@/app/api/reports/route";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/reports${suffix}`, {
    headers: {
      host: "localhost:55300",
      origin: "http://localhost:55300",
    },
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("SAB_ENFORCE_LOCAL_REQUEST", "1");
  vi.stubEnv("SAB_TRUST_HOST_HEADER_FOR_LOCAL_REQUESTS", "1");
  vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
  vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test_key");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("/api/reports integration", () => {
  it("uses report_index query builder for list request", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            report_key: "2026/02/2026-02-20.buy.json",
            report_type: "buy",
            report_date: "2026-02-20",
            duplicate_index: 0,
            generated_at: "2026-02-20T00:00:00Z",
            summary: null,
            tickers: ["AAPL.US"],
            tickers_hydrated: true,
          },
        ]),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-range": "0-0/1",
          },
        },
      ),
    );

    const response = await GET(makeRequest("type=buy&limit=2"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; type: string }>;
      total: number;
      searched: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(payload.total).toBeNull();
    expect(payload.items[0]).toEqual({
      key: "2026/02/2026-02-20.buy.json",
      bucketId: "reports",
      type: "buy",
      reportDate: "2026-02-20",
      duplicateIndex: 0,
    });
    expect(payload.searched).toBe(0);
    expect(payload.truncated).toBe(false);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.pathname).toBe("/rest/v1/report_index");
    expect(requestUrl.searchParams.get("report_type")).toBe("eq.buy");
    expect(requestUrl.searchParams.get("order")).toBe(
      "report_date.desc,duplicate_index.desc,report_key.desc,bucket_id.desc",
    );
    expect(requestUrl.searchParams.get("limit")).toBe("3");
  });

  it("accepts entry type and returns entry rows", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            report_key: "2026/02/2026-02-20.entry.json",
            report_type: "entry",
            report_date: "2026-02-20",
            duplicate_index: 0,
            generated_at: "2026-02-20T00:00:00Z",
            summary: { entry_count: 1 },
            tickers: ["AAPL.NASD"],
            tickers_hydrated: true,
          },
        ]),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-range": "0-0/1",
          },
        },
      ),
    );

    const response = await GET(makeRequest("type=entry&limit=1"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; type: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.items[0]).toEqual({
      key: "2026/02/2026-02-20.entry.json",
      bucketId: "reports",
      type: "entry",
      reportDate: "2026-02-20",
      duplicateIndex: 0,
    });

    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.searchParams.get("report_type")).toBe("eq.entry");
  });

  it("accepts AI brief type and returns AI brief rows", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            report_key: "2026/05/2026-05-05.ai-brief.json",
            report_type: "ai-brief",
            report_date: "2026-05-05",
            duplicate_index: 0,
            generated_at: "2026-05-05T00:00:00Z",
            summary: { recommendation_count: 1 },
            tickers: ["AAPL.NAS"],
            tickers_hydrated: true,
          },
        ]),
        {
          status: 200,
          headers: {
            "content-type": "application/json",
            "content-range": "0-0/1",
          },
        },
      ),
    );

    const response = await GET(makeRequest("type=ai-brief&limit=1"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; type: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.items[0]).toEqual({
      key: "2026/05/2026-05-05.ai-brief.json",
      bucketId: "reports",
      type: "ai-brief",
      reportDate: "2026-05-05",
      duplicateIndex: 0,
    });

    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.searchParams.get("report_type")).toBe("eq.ai-brief");
  });

  it("propagates exact Decision Board run kind and public run identity", async () => {
    const digest = "e".repeat(64);
    const reportKey =
      "2026/08/2026-08-06.decision-board.entry.entry-slot-001." +
      `${digest}.json`;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            bucket_id: "reports",
            report_key: reportKey,
            report_type: "decision-board",
            report_date: "2026-08-06",
            duplicate_index: 0,
            generated_at: null,
            summary: null,
            tickers: ["AUR.NAS"],
            tickers_hydrated: true,
            run_kind: "ENTRY",
            run_id: "entry-slot-001",
            idempotency_key: `sha256:${digest}`,
            decision_created_at: "2026-08-06T01:00:05Z",
          },
        ]),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const response = await GET(
      makeRequest("type=decision-board&runKind=ENTRY&limit=1"),
    );
    const payload = (await response.json()) as {
      items: Array<Record<string, unknown>>;
    };

    expect(response.status).toBe(200);
    expect(payload.items).toEqual([
      {
        key: reportKey,
        bucketId: "reports",
        type: "decision-board",
        reportDate: "2026-08-06",
        duplicateIndex: 0,
        runKind: "ENTRY",
        runId: "entry-slot-001",
      },
    ]);
    const requestUrl = new URL(String(fetchSpy.mock.calls[0]?.[0]));
    expect(requestUrl.searchParams.get("report_type")).toBe(
      "eq.decision-board",
    );
    expect(requestUrl.searchParams.get("run_kind")).toBe("eq.ENTRY");
  });

  it("returns 400 before hitting Supabase when query validation fails", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const response = await GET(makeRequest("limit=9999"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid query parameters");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
