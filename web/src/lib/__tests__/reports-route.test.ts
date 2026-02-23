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

    constructor(message: string, status: number) {
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
    fetchReportIndexPage: vi.fn(),
  };
});

import { GET } from "@/app/api/reports/route";
import { requireAdminAuth } from "@/lib/admin-auth";
import { assertLocalRequest } from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { fetchReportIndexPage, SupabaseApiError } from "@/lib/supabase-admin";

function makeRequest(query = ""): NextRequest {
  const suffix = query ? `?${query}` : "";
  return new NextRequest(`http://localhost:55300/api/reports${suffix}`);
}

const BUY_KEY_14 = "2026/02/2026-02-14.buy.json";
const BUY_KEY_13 = "2026/02/2026-02-13.buy.json";
const BUY_KEY_12 = "2026/02/2026-02-12.buy.json";
const BUY_KEY_11 = "2026/02/2026-02-11.buy.json";

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("REPORT_SEARCH_WINDOW", "100");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GET /api/reports", () => {
  it("returns report list from index without searching when q is empty", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const authMock = vi.mocked(requireAdminAuth);
    const localGuardMock = vi.mocked(assertLocalRequest);

    listMock.mockResolvedValue({
      items: [
        {
          report_key: BUY_KEY_14,
          report_type: "buy",
          report_date: "2026-02-14",
          duplicate_index: 0,
          generated_at: "2026-02-14 09:00 KST",
          summary: { candidate_count: 2 },
          tickers: ["AAPL.US", "MSFT.US"],
          tickers_hydrated: true,
        },
        {
          report_key: BUY_KEY_13,
          report_type: "buy",
          report_date: "2026-02-13",
          duplicate_index: 0,
          generated_at: null,
          summary: null,
          tickers: [],
          tickers_hydrated: true,
        },
      ],
      total: 3,
      fetchedCount: 2,
    });

    const response = await GET(makeRequest("type=buy&limit=2"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; generatedAt?: string }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
      warnings: Array<{ code: string; message: string }>;
    };

    expect(response.status).toBe(200);
    expect(authMock).toHaveBeenCalledTimes(1);
    expect(localGuardMock).toHaveBeenCalledTimes(1);
    expect(listMock).toHaveBeenCalledWith({
      type: "buy",
      limit: 2,
    });
    expect(payload.items.map((item) => item.key)).toEqual([
      BUY_KEY_14,
      BUY_KEY_13,
    ]);
    expect(payload.items[0].generatedAt).toBeUndefined();
    expect(payload.total).toBe(3);
    expect(payload.searched).toBe(0);
    expect(payload.searchWindow).toBe(100);
    expect(payload.truncated).toBe(false);
    expect(payload.warnings).toEqual([]);
  });

  it("returns 403 when same-origin guard rejects request", async () => {
    vi.mocked(assertSameOrigin).mockImplementationOnce(() => {
      throw new SameOriginError("Cross-site blocked");
    });

    const response = await GET(makeRequest("type=buy&limit=2"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(payload.error).toBe("Cross-site blocked");
  });

  it("filters by ticker within searchWindow and keeps index order", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    listMock.mockResolvedValue({
      items: [
        {
          report_key: BUY_KEY_14,
          report_type: "buy",
          report_date: "2026-02-14",
          duplicate_index: 0,
          generated_at: "2026-02-14T00:00:00Z",
          summary: { candidate_count: 1 },
          tickers: ["MSFT.US"],
          tickers_hydrated: true,
        },
        {
          report_key: BUY_KEY_13,
          report_type: "buy",
          report_date: "2026-02-13",
          duplicate_index: 0,
          generated_at: "2026-02-13T00:00:00Z",
          summary: { candidate_count: 2 },
          tickers: ["AAPL.US"],
          tickers_hydrated: true,
        },
        {
          report_key: BUY_KEY_12,
          report_type: "buy",
          report_date: "2026-02-12",
          duplicate_index: 0,
          generated_at: "2026-02-12T00:00:00Z",
          summary: null,
          tickers: ["XAA.US"],
          tickers_hydrated: true,
        },
        {
          report_key: BUY_KEY_11,
          report_type: "buy",
          report_date: "2026-02-11",
          duplicate_index: 0,
          generated_at: "2026-02-11T00:00:00Z",
          summary: null,
          tickers: ["META.US"],
          tickers_hydrated: true,
        },
      ],
      total: 4,
      fetchedCount: 4,
    });

    const response = await GET(makeRequest("type=buy&limit=10&q=aa"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; generatedAt?: string; tickers?: string[] }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
      warnings: Array<{ code: string; message: string }>;
    };

    expect(response.status).toBe(200);
    expect(listMock).toHaveBeenCalledWith({
      type: "buy",
      limit: 10,
      offset: 0,
    });
    expect(payload.items.map((item) => item.key)).toEqual([
      BUY_KEY_13,
      BUY_KEY_12,
    ]);
    expect(payload.items[0].generatedAt).toBe("2026-02-13T00:00:00Z");
    expect(payload.items[0].tickers).toEqual(["AAPL.US"]);
    expect(payload.total).toBe(2);
    expect(payload.searched).toBe(4);
    expect(payload.searchWindow).toBe(10);
    expect(payload.truncated).toBe(false);
    expect(payload.warnings).toEqual([]);
  });

  it("skips non-hydrated index rows and returns warning", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    listMock.mockResolvedValue({
      items: [
        {
          report_key: BUY_KEY_14,
          report_type: "buy",
          report_date: "2026-02-14",
          duplicate_index: 0,
          generated_at: null,
          summary: null,
          tickers: [],
          tickers_hydrated: false,
        },
        {
          report_key: BUY_KEY_13,
          report_type: "buy",
          report_date: "2026-02-13",
          duplicate_index: 0,
          generated_at: "2026-02-13T00:00:00Z",
          summary: { candidate_count: 2 },
          tickers: ["AAPL.US"],
          tickers_hydrated: true,
        },
      ],
      total: 2,
      fetchedCount: 2,
    });

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      warnings: Array<{ code: string; message: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.items.map((item) => item.key)).toEqual([BUY_KEY_13]);
    expect(payload.total).toBe(1);
    expect(payload.warnings).toHaveLength(1);
    expect(payload.warnings[0]?.code).toBe("index_incomplete");
  });

  it("returns partial results with warning when later search page fails", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const firstPage = Array.from({ length: 100 }, (_, index) => ({
      report_key: `2026/02/2026-02-${String(20 - (index % 20)).padStart(2, "0")}.buy.json`,
      report_type: "buy" as const,
      report_date: `2026-02-${String(20 - (index % 20)).padStart(2, "0")}`,
      duplicate_index: index,
      generated_at: "2026-02-20T00:00:00Z",
      summary: null,
      tickers: ["AAPL.US"],
      tickers_hydrated: true,
    }));

    vi.stubEnv("REPORT_SEARCH_WINDOW", "110");
    listMock
      .mockResolvedValueOnce({
        items: firstPage,
        total: 250,
        fetchedCount: 100,
      })
      .mockRejectedValueOnce(new Error("temporary outage"));

    const response = await GET(makeRequest("type=buy&limit=5&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      truncated: boolean;
      warnings: Array<{ code: string; message: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.items).toHaveLength(5);
    expect(payload.total).toBe(100);
    expect(payload.searched).toBe(100);
    expect(payload.truncated).toBe(true);
    expect(payload.warnings).toHaveLength(1);
    expect(payload.warnings[0]?.code).toBe("partial_failure");
    expect(listMock).toHaveBeenNthCalledWith(1, {
      type: "buy",
      limit: 100,
      offset: 0,
    });
    expect(listMock).toHaveBeenNthCalledWith(2, {
      type: "buy",
      limit: 10,
      offset: 100,
    });
  });

  it("advances offset using fetched row count when parsed items are fewer", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "110");
    listMock
      .mockResolvedValueOnce({
        items: [
          {
            report_key: BUY_KEY_14,
            report_type: "buy",
            report_date: "2026-02-14",
            duplicate_index: 0,
            generated_at: "2026-02-14T00:00:00Z",
            summary: null,
            tickers: ["AAPL.US"],
            tickers_hydrated: true,
          },
        ],
        total: 250,
        fetchedCount: 100,
      })
      .mockResolvedValueOnce({
        items: [
          {
            report_key: BUY_KEY_13,
            report_type: "buy",
            report_date: "2026-02-13",
            duplicate_index: 0,
            generated_at: "2026-02-13T00:00:00Z",
            summary: null,
            tickers: ["AAPL.US"],
            tickers_hydrated: true,
          },
        ],
        total: 250,
        fetchedCount: 10,
      });

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      truncated: boolean;
      warnings: Array<{ code: string; message: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.items.map((item) => item.key)).toEqual([
      BUY_KEY_14,
      BUY_KEY_13,
    ]);
    expect(payload.total).toBe(2);
    expect(payload.searched).toBe(110);
    expect(payload.truncated).toBe(true);
    expect(payload.warnings).toEqual([]);
    expect(listMock).toHaveBeenNthCalledWith(1, {
      type: "buy",
      limit: 100,
      offset: 0,
    });
    expect(listMock).toHaveBeenNthCalledWith(2, {
      type: "buy",
      limit: 10,
      offset: 100,
    });
  });

  it("applies searchWindow and marks truncated when candidates exceed window", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const windowRows = Array.from({ length: 10 }, (_, index) => ({
      report_key: `2026/02/2026-02-${String(20 - index).padStart(2, "0")}.buy.json`,
      report_type: "buy" as const,
      report_date: `2026-02-${String(20 - index).padStart(2, "0")}`,
      duplicate_index: 0,
      generated_at: null,
      summary: null,
      tickers: ["AAPL.US"],
      tickers_hydrated: true,
    }));

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    listMock.mockResolvedValue({
      items: windowRows,
      total: 11,
      fetchedCount: 10,
    });

    const response = await GET(makeRequest("type=buy&limit=5&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
      warnings: Array<{ code: string; message: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.items).toHaveLength(5);
    expect(payload.total).toBe(10);
    expect(payload.searched).toBe(10);
    expect(payload.searchWindow).toBe(10);
    expect(payload.truncated).toBe(true);
    expect(payload.warnings).toEqual([]);
  });

  it("returns 500 when first report index query fails", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    listMock.mockRejectedValue(new SupabaseApiError("boom", 500));

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    const payload = (await response.json()) as { error?: string };

    expect(response.status).toBe(500);
    expect(payload.error).toContain("boom");
  });
});
