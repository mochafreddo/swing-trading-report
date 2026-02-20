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
    listAllStorageKeysCached: vi.fn(),
    downloadStorageJson: vi.fn(),
  };
});

import { GET } from "@/app/api/reports/route";
import { requireAdminAuth } from "@/lib/admin-auth";
import { assertLocalRequest } from "@/lib/local-request-guard";
import {
  downloadStorageJson,
  listAllStorageKeysCached,
  SupabaseApiError,
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
  vi.stubEnv("REPORT_KEYS_CACHE_TTL_SECONDS", "30");
  vi.stubEnv("REPORT_SEARCH_CONCURRENCY", "8");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("GET /api/reports", () => {
  it("returns report list without downloading report JSON when q is empty", async () => {
    const listMock = vi.mocked(listAllStorageKeysCached);
    const downloadMock = vi.mocked(downloadStorageJson);
    const authMock = vi.mocked(requireAdminAuth);
    const localGuardMock = vi.mocked(assertLocalRequest);

    listMock.mockResolvedValue([
      BUY_KEY_12,
      "2026/02/2026-02-12.sell.json",
      BUY_KEY_14,
      BUY_KEY_13,
    ]);

    const response = await GET(makeRequest("type=buy&limit=2"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(authMock).toHaveBeenCalledTimes(1);
    expect(localGuardMock).toHaveBeenCalledTimes(1);
    expect(listMock).toHaveBeenCalledWith("reports", 30);
    expect(downloadMock).not.toHaveBeenCalled();
    expect(payload.items.map((item) => item.key)).toEqual([
      BUY_KEY_14,
      BUY_KEY_13,
    ]);
    expect(payload.total).toBe(3);
    expect(payload.searched).toBe(0);
    expect(payload.searchWindow).toBe(100);
    expect(payload.truncated).toBe(false);
  });

  it("keeps candidate order even when JSON downloads resolve out of order", async () => {
    const listMock = vi.mocked(listAllStorageKeysCached);
    const downloadMock = vi.mocked(downloadStorageJson);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    vi.stubEnv("REPORT_SEARCH_CONCURRENCY", "2");

    listMock.mockResolvedValue([
      BUY_KEY_11,
      BUY_KEY_13,
      BUY_KEY_14,
      BUY_KEY_12,
    ]);

    downloadMock.mockImplementation(async (_bucket, key) => {
      if (key === BUY_KEY_14) {
        await new Promise((resolve) => setTimeout(resolve, 40));
        return { generated_at: "2026-02-14T00:00:00Z", tickers: ["MSFT.US"] };
      }
      if (key === BUY_KEY_13) {
        await new Promise((resolve) => setTimeout(resolve, 30));
        return { generated_at: "2026-02-13T00:00:00Z", tickers: ["AAPL.US"] };
      }
      if (key === BUY_KEY_12) {
        await new Promise((resolve) => setTimeout(resolve, 5));
        return { generated_at: "2026-02-12T00:00:00Z", tickers: ["XAA.US"] };
      }
      return { generated_at: "2026-02-11T00:00:00Z", tickers: ["META.US"] };
    });

    const response = await GET(makeRequest("type=buy&limit=10&q=aa"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      searchWindow: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(payload.items.map((item) => item.key)).toEqual([
      BUY_KEY_13,
      BUY_KEY_12,
    ]);
    expect(payload.total).toBe(2);
    expect(payload.searched).toBe(4);
    expect(payload.searchWindow).toBe(10);
    expect(payload.truncated).toBe(false);

    const downloadedKeys = downloadMock.mock.calls.map((call) => call[1]);
    expect(downloadedKeys).toHaveLength(4);
    expect(downloadedKeys).toEqual(
      expect.arrayContaining([BUY_KEY_14, BUY_KEY_13, BUY_KEY_12, BUY_KEY_11]),
    );
  });

  it("applies searchWindow and marks truncated when candidates exceed window", async () => {
    const listMock = vi.mocked(listAllStorageKeysCached);
    const downloadMock = vi.mocked(downloadStorageJson);
    const allKeys = [
      "2026/02/2026-02-20.buy.json",
      "2026/02/2026-02-19.buy.json",
      "2026/02/2026-02-18.buy.json",
      "2026/02/2026-02-17.buy.json",
      "2026/02/2026-02-16.buy.json",
      "2026/02/2026-02-15.buy.json",
      "2026/02/2026-02-14.buy.json",
      "2026/02/2026-02-13.buy.json",
      "2026/02/2026-02-12.buy.json",
      "2026/02/2026-02-11.buy.json",
      "2026/02/2026-02-10.buy.json",
    ];

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    listMock.mockResolvedValue(allKeys);
    downloadMock.mockResolvedValue({
      generated_at: "2026-02-20T00:00:00Z",
      tickers: ["AAPL.US"],
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
    expect(downloadMock).toHaveBeenCalledTimes(10);
  });

  it("skips missing reports (404) during ticker search", async () => {
    const listMock = vi.mocked(listAllStorageKeysCached);
    const downloadMock = vi.mocked(downloadStorageJson);

    listMock.mockResolvedValue([BUY_KEY_14, BUY_KEY_13]);
    downloadMock.mockImplementation(async (_bucket, key) => {
      if (key === BUY_KEY_14) {
        throw new SupabaseApiError("missing", 404);
      }
      return { generated_at: "2026-02-13T00:00:00Z", tickers: ["AAPL.US"] };
    });

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    const payload = (await response.json()) as {
      items: Array<{ key: string }>;
      total: number;
      searched: number;
      truncated: boolean;
    };

    expect(response.status).toBe(200);
    expect(payload.items.map((item) => item.key)).toEqual([BUY_KEY_13]);
    expect(payload.total).toBe(1);
    expect(payload.searched).toBe(2);
    expect(payload.truncated).toBe(false);
  });

  it("returns 500 when JSON download fails with non-404 error", async () => {
    const listMock = vi.mocked(listAllStorageKeysCached);
    const downloadMock = vi.mocked(downloadStorageJson);

    listMock.mockResolvedValue([BUY_KEY_14]);
    downloadMock.mockRejectedValue(new SupabaseApiError("boom", 500));

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    const payload = (await response.json()) as { error?: string };

    expect(response.status).toBe(500);
    expect(payload.error).toContain("boom");
  });

  it("stops scheduling new downloads after non-404 error", async () => {
    const listMock = vi.mocked(listAllStorageKeysCached);
    const downloadMock = vi.mocked(downloadStorageJson);

    vi.stubEnv("REPORT_SEARCH_WINDOW", "10");
    vi.stubEnv("REPORT_SEARCH_CONCURRENCY", "2");

    listMock.mockResolvedValue([
      BUY_KEY_11,
      BUY_KEY_12,
      BUY_KEY_13,
      BUY_KEY_14,
    ]);
    downloadMock.mockImplementation(async (_bucket, key) => {
      if (key === BUY_KEY_14) {
        throw new SupabaseApiError("boom", 500);
      }

      if (key === BUY_KEY_13) {
        await new Promise((resolve) => setTimeout(resolve, 40));
        return { generated_at: "2026-02-13T00:00:00Z", tickers: ["AAPL.US"] };
      }

      return { generated_at: "2026-02-12T00:00:00Z", tickers: ["AAPL.US"] };
    });

    const response = await GET(makeRequest("type=buy&limit=10&q=aapl"));
    expect(response.status).toBe(500);

    const downloadedKeys = downloadMock.mock.calls.map((call) => call[1]);
    expect(downloadedKeys).toEqual(
      expect.arrayContaining([BUY_KEY_14, BUY_KEY_13]),
    );
    expect(downloadedKeys).not.toContain(BUY_KEY_12);
    expect(downloadedKeys).not.toContain(BUY_KEY_11);
  });
});
