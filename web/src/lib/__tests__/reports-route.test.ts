import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

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
    downloadStorageJson: vi.fn(),
    upsertReportIndexEntry: vi.fn(),
  };
});

import { GET } from "@/app/api/reports/route";
import { requireAdminAuth } from "@/lib/admin-auth";
import { assertLocalRequest } from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import {
  downloadStorageJson,
  fetchReportIndexPage,
  SupabaseApiError,
  upsertReportIndexEntry,
} from "@/lib/supabase-admin";

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
  it("returns report list from index without loading report JSON when q is empty", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const downloadMock = vi.mocked(downloadStorageJson);
    const upsertMock = vi.mocked(upsertReportIndexEntry);
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
    });

    const response = await GET(makeRequest("type=buy&limit=2"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; generatedAt?: string }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(authMock).toHaveBeenCalledTimes(1);
    expect(localGuardMock).toHaveBeenCalledTimes(1);
    expect(listMock).toHaveBeenCalledWith({
      type: "buy",
      limit: 2,
    });
    expect(downloadMock).not.toHaveBeenCalled();
    expect(upsertMock).not.toHaveBeenCalled();
    expect(payload.items.map((item) => item.key)).toEqual([
      BUY_KEY_14,
      BUY_KEY_13,
    ]);
    expect(payload.items[0].generatedAt).toBeUndefined();
    expect(payload.total).toBe(3);
    expect(payload.searched).toBe(0);
    expect(payload.searchWindow).toBe(100);
    expect(payload.truncated).toBe(false);
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
    const downloadMock = vi.mocked(downloadStorageJson);
    const upsertMock = vi.mocked(upsertReportIndexEntry);

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
    });

    const response = await GET(makeRequest("type=buy&limit=10&q=aa"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; generatedAt?: string; tickers?: string[] }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(listMock).toHaveBeenCalledWith({
      type: "buy",
      limit: 10,
    });
    expect(downloadMock).not.toHaveBeenCalled();
    expect(upsertMock).not.toHaveBeenCalled();
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
  });

  it("falls back to report JSON when index tickers are missing", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const downloadMock = vi.mocked(downloadStorageJson);
    const upsertMock = vi.mocked(upsertReportIndexEntry);

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
      ],
      total: 1,
    });
    downloadMock.mockResolvedValue({
      generated_at: "2026-02-14T00:00:00Z",
      summary: { candidate_count: 1 },
      tickers: ["AAPL.US"],
    });

    const response = await GET(makeRequest("type=buy&limit=5&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string; generatedAt?: string; tickers?: string[] }>;
      total: number;
    };

    expect(response.status).toBe(200);
    expect(payload.total).toBe(1);
    expect(payload.items[0]?.key).toBe(BUY_KEY_14);
    expect(payload.items[0]?.generatedAt).toBe("2026-02-14T00:00:00Z");
    expect(payload.items[0]?.tickers).toEqual(["AAPL.US"]);
    expect(downloadMock).toHaveBeenCalledWith("reports", BUY_KEY_14);
    expect(upsertMock).toHaveBeenCalledWith({
      reportKey: BUY_KEY_14,
      reportType: "buy",
      reportDate: "2026-02-14",
      duplicateIndex: 0,
      generatedAt: "2026-02-14T00:00:00Z",
      summary: { candidate_count: 1 },
      tickers: ["AAPL.US"],
      tickersHydrated: true,
    });
  });

  it("ignores index hydration failures after fallback download", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const downloadMock = vi.mocked(downloadStorageJson);
    const upsertMock = vi.mocked(upsertReportIndexEntry);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    listMock.mockResolvedValue({
      items: [
        {
          report_key: BUY_KEY_13,
          report_type: "buy",
          report_date: "2026-02-13",
          duplicate_index: 0,
          generated_at: null,
          summary: null,
          tickers: [],
          tickers_hydrated: false,
        },
      ],
      total: 1,
    });
    downloadMock.mockResolvedValue({
      tickers: ["AAPL.US"],
    });
    upsertMock.mockRejectedValue(new Error("index down"));

    const response = await GET(makeRequest("type=buy&limit=5&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
    };

    expect(response.status).toBe(200);
    expect(payload.total).toBe(1);
    expect(payload.items[0]?.key).toBe(BUY_KEY_13);
  });

  it("does not re-download when row is already hydrated with empty tickers", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    const downloadMock = vi.mocked(downloadStorageJson);
    const upsertMock = vi.mocked(upsertReportIndexEntry);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    listMock.mockResolvedValue({
      items: [
        {
          report_key: BUY_KEY_11,
          report_type: "buy",
          report_date: "2026-02-11",
          duplicate_index: 0,
          generated_at: "2026-02-11T00:00:00Z",
          summary: { candidate_count: 0 },
          tickers: [],
          tickers_hydrated: true,
        },
      ],
      total: 1,
    });

    const response = await GET(makeRequest("type=buy&limit=5&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
    };

    expect(response.status).toBe(200);
    expect(payload.total).toBe(0);
    expect(payload.searched).toBe(1);
    expect(downloadMock).not.toHaveBeenCalled();
    expect(upsertMock).not.toHaveBeenCalled();
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
    });

    const response = await GET(makeRequest("type=buy&limit=5&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(payload.items).toHaveLength(5);
    expect(payload.total).toBe(10);
    expect(payload.searched).toBe(10);
    expect(payload.searchWindow).toBe(10);
    expect(payload.truncated).toBe(true);
  });

  it("returns 500 when report index query fails", async () => {
    const listMock = vi.mocked(fetchReportIndexPage);
    listMock.mockRejectedValue(new SupabaseApiError("boom", 500));

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    const payload = (await response.json()) as { error?: string };

    expect(response.status).toBe(500);
    expect(payload.error).toContain("boom");
  });
});
