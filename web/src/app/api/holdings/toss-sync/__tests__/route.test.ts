import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

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
    fetchAllHoldings: vi.fn(async () => []),
    replaceAllHoldings: vi.fn(async () => ({
      insertedCount: 0,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
    })),
  };
});

vi.mock("@/lib/toss/client", () => {
  class TossInvestApiError extends Error {
    status: number;

    constructor(message: string, status = 502) {
      super(message);
      this.status = status;
    }
  }

  class TossInvestConfigError extends Error {}

  return {
    TossInvestApiError,
    TossInvestConfigError,
    fetchDefaultTossHoldingsItems: vi.fn(async () => []),
  };
});

vi.mock("@/lib/ticker-directory", () => ({
  listTickerDirectoryExactBaseCandidates: vi.fn(async () => ({
    candidates: [],
    directory: { builtAtMs: 0, sourceReports: 0, usableForAutoMapping: false },
  })),
}));

import { POST } from "@/app/api/holdings/toss-sync/route";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { fetchAllHoldings, replaceAllHoldings } from "@/lib/supabase-admin";
import { listTickerDirectoryExactBaseCandidates } from "@/lib/ticker-directory";
import { fetchDefaultTossHoldingsItems } from "@/lib/toss/client";

function makePostRequest(body: object | string): NextRequest {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  return new NextRequest("http://localhost:55300/api/holdings/toss-sync", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
      "x-request-id": "toss-sync-route-test-request",
    },
    body: payload,
  });
}

describe("/api/holdings/toss-sync route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTickerDirectoryExactBaseCandidates).mockResolvedValue({
      candidates: [],
      directory: {
        builtAtMs: 0,
        sourceReports: 0,
        usableForAutoMapping: false,
      },
    });
  });

  it("maps local-request guard failures to 403", async () => {
    vi.mocked(assertLocalRequest).mockImplementationOnce(() => {
      throw new LocalRequestGuardError("Local only");
    });

    const response = await POST(makePostRequest({ mode: "dry-run" }));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe(
      "private, no-store, max-age=0, must-revalidate",
    );
    expect(payload.error).toBe("Local only");
    expect(vi.mocked(fetchDefaultTossHoldingsItems)).not.toHaveBeenCalled();
  });

  it("returns a Toss holdings dry-run without applying Supabase changes", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce([
      {
        ticker: "AAPL.NAS",
        quantity: 2,
        entry_price: 190,
        entry_currency: "USD",
        entry_date: null,
        strategy: "swing",
        entry_pattern: "swing_high_breakout",
        notes: "core",
        tags: ["leader"],
        stop_override: null,
        target_override: null,
        created_at: "2026-06-19T00:00:00Z",
        updated_at: "2026-06-19T00:00:00Z",
      },
    ]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValueOnce([
      {
        symbol: "AAPL",
        marketCountry: "US",
        currency: "USD",
        quantity: "3",
        averagePurchasePrice: "188.50",
      },
      {
        symbol: "MSFT",
        marketCountry: "US",
        currency: "USD",
        quantity: "1",
        averagePurchasePrice: "400",
      },
    ]);

    const response = await POST(makePostRequest({ mode: "dry-run" }));
    const payload = (await response.json()) as {
      mode: string;
      diffHash: string;
      applyBlocked: boolean;
      summary: { updateCount: number };
      blockedRows: Array<{ symbol: string; reason: string }>;
    };

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe(
      "private, no-store, max-age=0, must-revalidate",
    );
    expect(payload.mode).toBe("dry-run");
    expect(payload.applyBlocked).toBe(true);
    expect(payload.summary.updateCount).toBe(1);
    expect(payload).toEqual(
      expect.objectContaining({ diffHash: expect.any(String) }),
    );
    expect(payload.diffHash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(payload.blockedRows).toEqual([
      expect.objectContaining({
        symbol: "MSFT",
        reason: "ticker_exchange_unresolved",
      }),
    ]);
    expect(response.headers.get("x-request-id")).toBe(
      "toss-sync-route-test-request",
    );
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
  });

  it("uses one ticker directory match to create a new US Toss holding in dry-run", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce([]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValueOnce([
      {
        symbol: "HOOD",
        marketCountry: "US",
        currency: "USD",
        quantity: "2",
        averagePurchasePrice: "81.25",
      },
    ]);
    vi.mocked(listTickerDirectoryExactBaseCandidates).mockResolvedValueOnce({
      candidates: [{ ticker: "HOOD.NAS", name: "Robinhood Markets" }],
      directory: {
        builtAtMs: 1,
        sourceReports: 10,
        usableForAutoMapping: true,
      },
    });

    const response = await POST(makePostRequest({ mode: "dry-run" }));
    const payload = (await response.json()) as {
      applyBlocked: boolean;
      summary: { createCount: number };
      blockedRows: Array<{ reason: string }>;
      targetRows: Array<{ ticker: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.applyBlocked).toBe(false);
    expect(payload.summary.createCount).toBe(1);
    expect(payload.blockedRows).toEqual([]);
    expect(payload.targetRows).toEqual([
      expect.objectContaining({ ticker: "HOOD.NAS" }),
    ]);
    expect(
      vi.mocked(listTickerDirectoryExactBaseCandidates),
    ).toHaveBeenCalledWith(["HOOD"]);
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
  });

  it("keeps unresolved US Toss rows blocked when ticker directory lookup fails", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce([]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValueOnce([
      {
        symbol: "HOOD",
        marketCountry: "US",
        currency: "USD",
        quantity: "2",
        averagePurchasePrice: "81.25",
      },
    ]);
    vi.mocked(listTickerDirectoryExactBaseCandidates).mockRejectedValueOnce(
      new Error("directory unavailable"),
    );

    const response = await POST(makePostRequest({ mode: "dry-run" }));
    const payload = (await response.json()) as {
      applyBlocked: boolean;
      blockedRows: Array<{ reason: string }>;
      targetRows: Array<{ ticker: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.applyBlocked).toBe(true);
    expect(payload.targetRows).toEqual([]);
    expect(payload.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
  });

  it("applies a reviewed Toss holdings diff when the server recomputed hash still matches", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValue([
      {
        ticker: "AAPL.NAS",
        quantity: 2,
        entry_price: 190,
        entry_currency: "USD",
        entry_date: null,
        strategy: "swing",
        entry_pattern: "swing_high_breakout",
        notes: "core",
        tags: ["leader"],
        stop_override: null,
        target_override: null,
        created_at: "2026-06-19T00:00:00Z",
        updated_at: "2026-06-19T00:00:00Z",
      },
    ]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValue([
      {
        symbol: "AAPL",
        marketCountry: "US",
        currency: "USD",
        quantity: "3",
        averagePurchasePrice: "188.50",
      },
    ]);
    vi.mocked(replaceAllHoldings).mockResolvedValueOnce({
      insertedCount: 0,
      updatedCount: 1,
      deletedCount: 0,
      unchangedCount: 0,
    });

    const dryRunResponse = await POST(makePostRequest({ mode: "dry-run" }));
    const dryRunPayload = (await dryRunResponse.json()) as {
      diffHash: string;
    };

    const applyResponse = await POST(
      makePostRequest({
        mode: "apply",
        diffHash: dryRunPayload.diffHash,
      }),
    );
    const applyPayload = (await applyResponse.json()) as {
      mode: string;
      summary: { updateCount: number };
      diffHash: string;
    };

    expect(applyResponse.status).toBe(200);
    expect(applyPayload.mode).toBe("apply");
    expect(applyPayload.diffHash).toBe(dryRunPayload.diffHash);
    expect(applyPayload.summary.updateCount).toBe(1);
    expect(vi.mocked(replaceAllHoldings)).toHaveBeenCalledWith(
      [
        expect.objectContaining({
          ticker: "AAPL.NAS",
          quantity: 3,
          entry_price: 188.5,
          entry_currency: "USD",
          entry_pattern: "swing_high_breakout",
          notes: "core",
        }),
      ],
      {
        expectedCurrentHoldings: [
          expect.objectContaining({ ticker: "AAPL.NAS", quantity: 2 }),
        ],
      },
    );
  });

  it("applies Toss holdings without confirmation text before writing Supabase", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValue([]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValue([
      {
        symbol: "005930",
        marketCountry: "KR",
        currency: "KRW",
        quantity: "1",
        averagePurchasePrice: "70000",
      },
    ]);
    vi.mocked(replaceAllHoldings).mockResolvedValueOnce({
      insertedCount: 1,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
    });

    const dryRunResponse = await POST(makePostRequest({ mode: "dry-run" }));
    const dryRunPayload = (await dryRunResponse.json()) as {
      diffHash: string;
    };

    const applyResponse = await POST(
      makePostRequest({
        mode: "apply",
        diffHash: dryRunPayload.diffHash,
      }),
    );
    const payload = (await applyResponse.json()) as { mode: string };

    expect(applyResponse.status).toBe(200);
    expect(payload.mode).toBe("apply");
    expect(vi.mocked(replaceAllHoldings)).toHaveBeenCalledWith(
      [expect.objectContaining({ ticker: "005930" })],
      { expectedCurrentHoldings: [] },
    );
  });

  it("rejects stale Toss holdings apply hashes before writing Supabase", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce([]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValueOnce([
      {
        symbol: "005930",
        marketCountry: "KR",
        currency: "KRW",
        quantity: "1",
        averagePurchasePrice: "70000",
      },
    ]);

    const response = await POST(
      makePostRequest({
        mode: "apply",
        diffHash:
          "sha256:0000000000000000000000000000000000000000000000000000000000000000",
      }),
    );
    const payload = (await response.json()) as {
      error: string;
      diffHash: string;
    };

    expect(response.status).toBe(409);
    expect(payload.error).toContain("changed");
    expect(payload.diffHash).toMatch(/^sha256:[a-f0-9]{64}$/);
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
  });

  it("rejects Toss holdings apply when normalization has blocked rows", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce([]);
    vi.mocked(fetchDefaultTossHoldingsItems).mockResolvedValueOnce([
      {
        symbol: "MSFT",
        marketCountry: "US",
        currency: "USD",
        quantity: "1",
        averagePurchasePrice: "400",
      },
    ]);

    const response = await POST(
      makePostRequest({
        mode: "apply",
        diffHash:
          "sha256:0000000000000000000000000000000000000000000000000000000000000000",
      }),
    );
    const payload = (await response.json()) as {
      error: string;
      blockedRows: Array<{ reason: string }>;
    };

    expect(response.status).toBe(409);
    expect(payload.error).toContain("blocked");
    expect(payload.blockedRows).toEqual([
      expect.objectContaining({ reason: "ticker_exchange_unresolved" }),
    ]);
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
  });
});
