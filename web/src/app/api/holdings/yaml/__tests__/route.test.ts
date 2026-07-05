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

vi.mock("@/lib/holdings-yaml", () => {
  class HoldingsYamlError extends Error {}

  return {
    HoldingsYamlError,
    buildHoldingsYamlDocument: vi.fn(() => "version: 1\nholdings: []\n"),
    buildHoldingsYamlImportSummary: vi.fn(() => ({
      incomingCount: 1,
      createCount: 1,
      updateCount: 0,
      deleteCount: 0,
      unchangedCount: 0,
      createTickers: ["TSLA.NAS"],
      updateTickers: [],
      deleteTickers: [],
    })),
    parseHoldingsYamlDocument: vi.fn(() => [
      {
        ticker: "TSLA.NAS",
        quantity: 1,
        entry_price: 250,
        entry_currency: "USD",
        entry_date: null,
        strategy: null,
        entry_pattern: null,
        notes: null,
        tags: [],
        stop_override: null,
        target_override: null,
      },
    ]),
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
      insertedCount: 1,
      updatedCount: 0,
      deletedCount: 0,
      unchangedCount: 0,
    })),
  };
});

import { GET, POST } from "@/app/api/holdings/yaml/route";
import {
  buildHoldingsYamlDocument,
  buildHoldingsYamlImportSummary,
  HoldingsYamlError,
  parseHoldingsYamlDocument,
} from "@/lib/holdings-yaml";
import {
  fetchAllHoldings,
  replaceAllHoldings,
  SupabaseApiError,
} from "@/lib/supabase-admin";

function makePostRequest(body: object | string): NextRequest {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  return new NextRequest("http://localhost:55300/api/holdings/yaml", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://localhost:55300",
    },
    body: payload,
  });
}

describe("/api/holdings/yaml route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exports holdings as downloadable YAML", async () => {
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce([
      {
        ticker: "005930",
        quantity: 1,
        entry_price: 70000,
        entry_currency: null,
        entry_date: null,
        strategy: null,
        entry_pattern: null,
        notes: null,
        tags: [],
        stop_override: null,
        target_override: null,
        created_at: "2026-03-28T00:00:00Z",
        updated_at: "2026-03-28T00:00:00Z",
      },
    ]);

    const response = await GET(
      new NextRequest("http://localhost:55300/api/holdings/yaml"),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("content-disposition")).toContain(
      "holdings.yaml",
    );
    expect(await response.text()).toBe("version: 1\nholdings: []\n");
    expect(vi.mocked(buildHoldingsYamlDocument)).toHaveBeenCalledTimes(1);
  });

  it("returns 400 for invalid JSON body", async () => {
    const response = await POST(makePostRequest("{"));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Request body must be valid JSON");
  });

  it("returns 400 for invalid request payload", async () => {
    const response = await POST(makePostRequest({ apply: false }));
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("Invalid holdings YAML import payload");
  });

  it("returns 400 for YAML validation failures", async () => {
    vi.mocked(parseHoldingsYamlDocument).mockImplementationOnce(() => {
      throw new HoldingsYamlError("invalid holdings yaml");
    });

    const response = await POST(
      makePostRequest({
        document: "holdings: []",
        apply: false,
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(400);
    expect(payload.error).toBe("invalid holdings yaml");
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
  });

  it("returns dry-run diff summary without applying", async () => {
    const response = await POST(
      makePostRequest({
        document: "holdings: []",
        apply: false,
      }),
    );
    const payload = (await response.json()) as {
      mode: string;
      summary: { createCount: number };
    };

    expect(response.status).toBe(200);
    expect(payload.mode).toBe("dry-run");
    expect(payload.summary.createCount).toBe(1);
    expect(vi.mocked(replaceAllHoldings)).not.toHaveBeenCalled();
    expect(vi.mocked(buildHoldingsYamlImportSummary)).toHaveBeenCalledTimes(1);
  });

  it("applies replace-all import when apply=true", async () => {
    const currentHoldings = [
      {
        ticker: "AAPL.NAS",
        quantity: 2,
        entry_price: 190,
        entry_currency: "USD",
        entry_date: null,
        strategy: null,
        entry_pattern: null,
        notes: null,
        tags: [],
        stop_override: null,
        target_override: null,
        created_at: "2026-03-01T00:00:00Z",
        updated_at: "2026-03-02T00:00:00Z",
      },
    ];
    vi.mocked(fetchAllHoldings).mockResolvedValueOnce(currentHoldings);

    const response = await POST(
      makePostRequest({
        document: "holdings: []",
        apply: true,
      }),
    );
    const payload = (await response.json()) as {
      mode: string;
      summary: { createCount: number };
    };

    expect(response.status).toBe(200);
    expect(payload.mode).toBe("apply");
    expect(payload.summary.createCount).toBe(1);
    expect(vi.mocked(replaceAllHoldings)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(replaceAllHoldings)).toHaveBeenCalledWith(
      [
        {
          ticker: "TSLA.NAS",
          quantity: 1,
          entry_price: 250,
          entry_currency: "USD",
          entry_date: null,
          strategy: null,
          entry_pattern: null,
          notes: null,
          tags: [],
          stop_override: null,
          target_override: null,
        },
      ],
      { expectedCurrentHoldings: currentHoldings },
    );
  });

  it("maps upstream Supabase failures during apply", async () => {
    vi.mocked(replaceAllHoldings).mockRejectedValueOnce(
      new SupabaseApiError("replace failed", 503),
    );

    const response = await POST(
      makePostRequest({
        document: "holdings: []",
        apply: true,
      }),
    );
    const payload = (await response.json()) as { error: string };

    expect(response.status).toBe(503);
    expect(payload.error).toBe("replace failed");
  });
});
