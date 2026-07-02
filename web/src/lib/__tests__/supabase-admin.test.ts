import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import {
  addBuyToHolding,
  claimRuntimeStateLock,
  downloadStorageJson,
  fetchReportIndexPage,
  fetchAllHoldings,
  createHolding,
  deleteHolding,
  replaceAllHoldings,
  releaseRuntimeStateLock,
  SupabaseApiError,
  updateHolding,
  upsertReportIndexEntry,
} from "@/lib/supabase-admin";
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";
import { parseErrorPayload } from "@/lib/supabase/admin-client";

const REPORT_KEY_A = "2026/02/2026-02-14.buy.json";

function reportIndexResponse(rows: unknown[], total: number): Response {
  return new Response(JSON.stringify(rows), {
    status: 200,
    headers: {
      "content-type": "application/json",
      "content-range": `0-${Math.max(rows.length - 1, 0)}/${total}`,
    },
  });
}

beforeAll(() => {
  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_SECRET_KEY = "sb_secret_test_key";
});

afterAll(() => {
  delete process.env.SUPABASE_URL;
  delete process.env.SUPABASE_SECRET_KEY;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchReportIndexPage", () => {
  it("returns typed rows and parsed total count", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      reportIndexResponse(
        [
          {
            report_key: REPORT_KEY_A,
            report_type: "buy",
            report_date: "2026-02-14",
            duplicate_index: 0,
            generated_at: "2026-02-14T00:00:00Z",
            summary: { candidate_count: 1 },
            tickers: ["AAPL.US"],
            tickers_hydrated: true,
          },
        ],
        12,
      ),
    );

    const result = await fetchReportIndexPage({
      type: "buy",
      limit: 10,
    });

    expect(result.total).toBe(12);
    expect(result.fetchedCount).toBe(1);
    expect(result.hasMore).toBe(false);
    expect(result.nextCursor).toBeNull();
    expect(result.items).toEqual([
      {
        report_key: REPORT_KEY_A,
        report_type: "buy",
        report_date: "2026-02-14",
        duplicate_index: 0,
        generated_at: "2026-02-14T00:00:00Z",
        summary: { candidate_count: 1 },
        tickers: ["AAPL.US"],
        tickers_hydrated: true,
      },
    ]);

    const [requestUrl] = fetchMock.mock.calls[0] ?? [];
    const url = new URL(String(requestUrl));
    expect(url.searchParams.get("limit")).toBe("10");
  });

  it("filters out malformed rows", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      reportIndexResponse(
        [
          {
            report_key: REPORT_KEY_A,
            report_type: "buy",
            report_date: "2026-02-14",
            duplicate_index: 0,
            generated_at: null,
            summary: null,
            tickers: [],
            tickers_hydrated: false,
          },
          {
            report_key: "",
            report_type: "buy",
            report_date: "2026-02-14",
            duplicate_index: 0,
          },
        ],
        2,
      ),
    );

    const result = await fetchReportIndexPage();
    expect(result.items).toHaveLength(1);
    expect(result.total).toBe(2);
    expect(result.fetchedCount).toBe(2);
    expect(result.hasMore).toBe(false);
    expect(result.nextCursor).toBeNull();
  });

  it.each([
    {
      key: "2026/05/2026-05-05.ai-brief.json",
      type: "ai-brief" as const,
      summary: { recommendation_count: 1 },
      tickers: ["AAPL.NAS"],
    },
    {
      key: "2026/05/2026-05-05.ai-brief-skip.json",
      type: "ai-brief-skip" as const,
      summary: { skip_reason: "non_trading_session" },
      tickers: [],
    },
  ])(
    "accepts $type report index rows",
    async ({ key, type, summary, tickers }) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        reportIndexResponse(
          [
            {
              report_key: key,
              report_type: type,
              report_date: "2026-05-05",
              duplicate_index: 0,
              generated_at: "2026-05-05T00:00:00Z",
              summary,
              tickers,
              tickers_hydrated: true,
            },
          ],
          1,
        ),
      );

      const result = await fetchReportIndexPage({
        type,
        limit: 10,
      });

      expect(result.items).toEqual([
        {
          report_key: key,
          report_type: type,
          report_date: "2026-05-05",
          duplicate_index: 0,
          generated_at: "2026-05-05T00:00:00Z",
          summary,
          tickers,
          tickers_hydrated: true,
        },
      ]);
    },
  );

  it("uses keyset pagination without exact count when includeTotal is false", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      reportIndexResponse(
        [
          {
            report_key: "2026/02/2026-02-14.buy.json",
            report_type: "buy",
            report_date: "2026-02-14",
            duplicate_index: 0,
            generated_at: "2026-02-14T00:00:00Z",
            summary: null,
            tickers: ["AAPL.US"],
            tickers_hydrated: true,
          },
          {
            report_key: "2026/02/2026-02-13.buy.json",
            report_type: "buy",
            report_date: "2026-02-13",
            duplicate_index: 0,
            generated_at: "2026-02-13T00:00:00Z",
            summary: null,
            tickers: ["MSFT.US"],
            tickers_hydrated: true,
          },
        ],
        99,
      ),
    );

    const result = await fetchReportIndexPage({
      type: "buy",
      limit: 1,
      cursor: {
        report_date: "2026-02-20",
        duplicate_index: 0,
        report_key: "2026/02/2026-02-20.buy.json",
      },
      includeTotal: false,
      lookahead: true,
    });

    expect(result.total).toBe(1);
    expect(result.fetchedCount).toBe(1);
    expect(result.hasMore).toBe(true);
    expect(result.nextCursor).toEqual({
      report_date: "2026-02-14",
      duplicate_index: 0,
      report_key: "2026/02/2026-02-14.buy.json",
    });

    const [requestUrl, init] = fetchMock.mock.calls[0] ?? [];
    const url = new URL(String(requestUrl));
    expect(url.searchParams.get("limit")).toBe("2");
    expect(url.searchParams.get("report_type")).toBe("eq.buy");
    expect(url.searchParams.get("or")).toContain("report_date.lt.");
    expect(url.searchParams.get("or")).toContain("duplicate_index.lt.");
    expect(url.searchParams.get("or")).toContain("report_key.lt.");

    const headers = init?.headers as Record<string, string>;
    expect(headers.Accept).toBe("application/json");
    expect(headers.Prefer).toBeUndefined();
  });
});

describe("upsertReportIndexEntry", () => {
  it("upserts a report index row", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("", { status: 201 }));

    await upsertReportIndexEntry({
      reportKey: REPORT_KEY_A,
      reportType: "buy",
      reportDate: "2026-02-14",
      duplicateIndex: 0,
      generatedAt: "2026-02-14T00:00:00Z",
      summary: { candidate_count: 1 },
      tickers: [" AAPL.US ", ""],
      tickersHydrated: true,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(init?.method).toBe("POST");
    const body = typeof init?.body === "string" ? init.body : "";
    expect(body).toContain('"report_key":"2026/02/2026-02-14.buy.json"');
    expect(body).toContain('"tickers":["AAPL.US"]');
    expect(body).toContain('"tickers_hydrated":true');
  });
});

describe("parseErrorPayload", () => {
  it.each([
    {
      name: "json message with metadata",
      body: JSON.stringify({
        message: "row missing",
        code: "PGRST116",
        details: "No rows found",
        hint: "Check filter",
      }),
      status: 404,
      expected: {
        message: "row missing",
        code: "PGRST116",
        details: "No rows found",
        hint: "Check filter",
      },
    },
    {
      name: "json error fallback",
      body: JSON.stringify({ error: "bad request" }),
      status: 400,
      expected: {
        message: "bad request",
        code: null,
        details: null,
        hint: null,
      },
    },
    {
      name: "plain text body",
      body: "gateway unavailable",
      status: 503,
      expected: {
        message: "gateway unavailable",
        code: null,
        details: null,
        hint: null,
      },
    },
    {
      name: "empty body",
      body: "",
      status: 500,
      expected: {
        message: "HTTP 500",
        code: null,
        details: null,
        hint: null,
      },
    },
  ])("parses $name", async ({ body, status, expected }) => {
    await expect(
      parseErrorPayload(new Response(body, { status })),
    ).resolves.toEqual(expected);
  });
});

describe("claimRuntimeStateLock", () => {
  it("claims runtime_state lock through RPC", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            acquired: true,
            expires_at: "2026-03-08T10:00:30.000Z",
          },
        ]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const result = await claimRuntimeStateLock({
      key: "run_dispatch:scan:kis:both",
      now: Date.parse("2026-03-08T10:00:00.000Z"),
      ttlSeconds: 30,
      payload: {
        input: { workflow: "scan", provider: "kis", universe: "both" },
      },
    });

    expect(result).toEqual({
      acquired: true,
      expiresAt: "2026-03-08T10:00:30.000Z",
    });
    const [requestUrl, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(requestUrl)).toContain(
      "/rest/v1/rpc/claim_runtime_state_lock",
    );
    expect(init?.method).toBe("POST");
    const body =
      typeof init?.body === "string"
        ? (JSON.parse(init.body) as Record<string, unknown>)
        : null;
    expect(body?.p_now).toBeNull();
  });
});

describe("downloadStorageJson", () => {
  it("rejects JSON arrays because report artifacts must be objects", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(
      downloadStorageJson("reports", "2026/02/2026-02-14.buy.json"),
    ).rejects.toMatchObject({
      status: 500,
      message:
        "Report '2026/02/2026-02-14.buy.json' is not a valid JSON object",
    } satisfies Partial<SupabaseApiError>);
  });
});

describe("releaseRuntimeStateLock", () => {
  it("releases runtime_state lock through RPC", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(true), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await releaseRuntimeStateLock({
      key: "run_dispatch:scan:kis:both",
      ownerToken: "owner-token",
    });

    expect(result).toBe(true);
    const [requestUrl, init] = fetchMock.mock.calls[0] ?? [];
    expect(String(requestUrl)).toContain(
      "/rest/v1/rpc/release_runtime_state_lock",
    );
    expect(init?.method).toBe("POST");
  });
});

function holdingRow(
  overrides: Partial<{
    ticker: string;
    quantity: number;
    entry_price: number;
    entry_pattern: string | null;
  }> = {},
) {
  return {
    ticker: overrides.ticker ?? "AAPL.US",
    quantity: overrides.quantity ?? 1,
    entry_price: overrides.entry_price ?? 100,
    entry_currency: null,
    entry_date: null,
    strategy: null,
    entry_pattern: overrides.entry_pattern ?? null,
    notes: null,
    tags: [],
    stop_override: null,
    target_override: null,
    created_at: "2026-02-24T00:00:00Z",
    updated_at: "2026-02-24T00:00:00Z",
  };
}

describe("fetchAllHoldings", () => {
  it("reads holdings snapshots until the final short page", async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) =>
      holdingRow({ ticker: `A${String(index).padStart(3, "0")}.NAS` }),
    );
    const secondPage = [holdingRow({ ticker: "TSLA.NAS" })];

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(firstPage), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(secondPage), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

    const rows = await fetchAllHoldings();

    expect(rows).toHaveLength(501);
    const firstUrl = new URL(String(fetchMock.mock.calls[0]?.[0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1]?.[0]));
    expect(firstUrl.searchParams.get("select")).toContain("entry_pattern");
    expect(firstUrl.searchParams.get("offset")).toBe("0");
    expect(secondUrl.searchParams.get("offset")).toBe("500");
  });
});

describe("holding mutations alias handling", () => {
  it("createHolding blocks alias duplicates before insert", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([holdingRow({ ticker: "BRK.B.NYS" })]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(
      createHolding({
        ticker: "BRK/B.NYS",
        quantity: 1,
        entry_price: 450,
      }),
    ).rejects.toMatchObject({
      status: 409,
      message: "Holding 'BRK.B.NYS' already exists",
    } satisfies Partial<SupabaseApiError>);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("updateHolding falls back to slash alias when canonical dot ticker row is absent", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([holdingRow({ ticker: "BRK/B.NYS" })]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

    const updated = await updateHolding("BRK/B.NYS", {
      ticker: "BRK/B.NYS",
      quantity: 2,
    });

    expect(updated?.ticker).toBe("BRK/B.NYS");
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const firstUrl = new URL(String(fetchMock.mock.calls[0]?.[0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1]?.[0]));
    expect(firstUrl.searchParams.get("ticker")).toBe("eq.BRK.B.NYS");
    expect(secondUrl.searchParams.get("ticker")).toBe("eq.BRK/B.NYS");
  });

  it("updateHolding clears entry pattern when quantity is zero", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([holdingRow({ ticker: "AAPL.NAS", quantity: 0 })]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    await updateHolding("AAPL.NAS", {
      quantity: 0,
    });

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    expect(requestInit?.body).toBe(
      JSON.stringify({
        quantity: 0,
        entry_pattern: null,
      }),
    );
  });

  it("deleteHolding falls back to slash alias when canonical dot ticker row is absent", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ ticker: "BRK.B.NYS" }]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

    const deleted = await deleteHolding("BRK/B.NYS");

    expect(deleted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const firstUrl = new URL(String(fetchMock.mock.calls[0]?.[0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1]?.[0]));
    expect(firstUrl.searchParams.get("ticker")).toBe("eq.BRK.B.NYS");
    expect(secondUrl.searchParams.get("ticker")).toBe("eq.BRK/B.NYS");
  });

  it("deleteHolding keeps deleting aliases after first success", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ ticker: "BRK/B.NYS" }]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ ticker: "BRK.B.NYS" }]), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );

    const deleted = await deleteHolding("BRK/B.NYS");

    expect(deleted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("replaceAllHoldings", () => {
  it("calls replace_holdings_v1 RPC with sanitized holdings snapshot", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            inserted_count: 1,
            updated_count: 2,
            deleted_count: 3,
            unchanged_count: 4,
          },
        ]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    const result = await replaceAllHoldings(
      [
        {
          ticker: "TSLA.NAS",
          quantity: 1,
          entry_price: 250.5,
          entry_currency: "USD",
          entry_date: "2026-03-28",
          strategy: "swing",
          entry_pattern: "swing_high_breakout",
          notes: "leader",
          tags: ["us"],
          stop_override: 220,
          target_override: 300,
        },
      ],
      {
        expectedCurrentHoldings: [
          {
            ticker: "AAPL.NAS",
            quantity: 2,
            entry_price: 180,
            entry_currency: "USD",
            entry_date: "2026-03-01",
            strategy: "swing",
            entry_pattern: "trend_pullback_bounce",
            notes: "preserve",
            tags: ["watch"],
            stop_override: 160,
            target_override: 220,
            created_at: "2026-02-01T00:00:00Z",
            updated_at: "2026-03-01T00:00:00Z",
          },
        ],
      },
    );

    expect(result).toEqual({
      insertedCount: 1,
      updatedCount: 2,
      deletedCount: 3,
      unchangedCount: 4,
    });

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] ?? [];
    const url = new URL(String(requestUrl));
    expect(url.pathname).toBe("/rest/v1/rpc/replace_holdings_v1");
    expect(requestInit?.method).toBe("POST");
    expect(requestInit?.body).toBe(
      JSON.stringify({
        p_holdings: [
          {
            ticker: "TSLA.NAS",
            quantity: 1,
            entry_price: 250.5,
            entry_currency: "USD",
            entry_date: "2026-03-28",
            strategy: "swing",
            entry_pattern: "swing_high_breakout",
            notes: "leader",
            tags: ["us"],
            stop_override: 220,
            target_override: 300,
          },
        ],
        p_expected_holdings: [
          {
            ticker: "AAPL.NAS",
            quantity: 2,
            entry_price: 180,
            entry_currency: "USD",
            entry_date: "2026-03-01",
            strategy: "swing",
            entry_pattern: "trend_pullback_bounce",
            notes: "preserve",
            tags: ["watch"],
            stop_override: 160,
            target_override: 220,
          },
        ],
      }),
    );
  });

  it("omits the compare-and-swap snapshot when replaceAllHoldings has no expected holdings", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            inserted_count: 0,
            updated_count: 0,
            deleted_count: 0,
            unchanged_count: 0,
          },
        ]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    await replaceAllHoldings([]);

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const body =
      typeof requestInit?.body === "string"
        ? (JSON.parse(requestInit.body) as Record<string, unknown>)
        : null;
    expect(body).toEqual({ p_holdings: [] });
  });

  it("replaceAllHoldings omits undefined entry pattern but keeps explicit null", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          {
            inserted_count: 0,
            updated_count: 1,
            deleted_count: 0,
            unchanged_count: 0,
          },
        ]),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    await replaceAllHoldings([
      {
        ticker: "AAPL.NAS",
        quantity: 1,
        entry_price: 100,
        entry_currency: "USD",
        entry_date: null,
        strategy: null,
        entry_pattern: undefined,
        notes: null,
        tags: [],
        stop_override: null,
        target_override: null,
      },
      {
        ticker: "MSFT.NAS",
        quantity: 1,
        entry_price: 300,
        entry_currency: "USD",
        entry_date: null,
        strategy: null,
        entry_pattern: null,
        notes: null,
        tags: [],
        stop_override: null,
        target_override: null,
      },
    ]);

    const [, requestInit] = fetchMock.mock.calls[0] ?? [];
    const body =
      typeof requestInit?.body === "string"
        ? (JSON.parse(requestInit.body) as {
            p_holdings: Array<Record<string, unknown>>;
          })
        : null;
    expect(body?.p_holdings[0]).not.toHaveProperty("entry_pattern");
    expect(body?.p_holdings[1]).toHaveProperty("entry_pattern", null);
  });

  it("maps replace_holdings_v1 snapshot conflicts to SupabaseApiError(409)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          code: "40001",
          details: "holdings_snapshot_conflict",
          message: "holdings snapshot changed before replace",
        }),
        {
          status: 400,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    await expect(
      replaceAllHoldings([], { expectedCurrentHoldings: [] }),
    ).rejects.toMatchObject({
      status: 409,
      upstreamCode: "40001",
      details: "holdings_snapshot_conflict",
      message:
        "Failed to replace holdings: holdings snapshot changed before replace",
    } satisfies Partial<SupabaseApiError>);
  });
});

describe("addBuyToHolding", () => {
  it("calls holdings_add_buy_v1 RPC and returns updated holding", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([holdingRow({ ticker: "AAPL.NAS" })]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const updated = await addBuyToHolding(
      "AAPL.NAS",
      {
        buy_quantity: 2,
        buy_price: 170.25,
        buy_date: "2026-03-03",
      },
      "supabase-admin-idempotency-key",
    );

    expect(updated?.ticker).toBe("AAPL.NAS");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] ?? [];
    const url = new URL(String(requestUrl));
    expect(url.pathname).toBe("/rest/v1/rpc/holdings_add_buy_v1");
    expect(requestInit?.method).toBe("POST");

    const body =
      typeof requestInit?.body === "string"
        ? (JSON.parse(requestInit.body) as Record<string, unknown>)
        : null;
    expect(body).toEqual({
      p_ticker: "AAPL.NAS",
      p_buy_quantity: 2,
      p_buy_price: 170.25,
      p_buy_date: "2026-03-03",
      p_idempotency_key: "supabase-admin-idempotency-key",
    });
  });

  it("returns null when RPC reports no matching holding", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const updated = await addBuyToHolding(
      "AAPL.NAS",
      {
        buy_quantity: 2,
        buy_price: 170.25,
      },
      "supabase-admin-idempotency-key",
    );

    expect(updated).toBeNull();
  });

  it("maps Supabase RPC failures to SupabaseApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ message: "currency mismatch" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(
      addBuyToHolding(
        "AAPL.NAS",
        {
          buy_quantity: 1,
          buy_price: 100,
        },
        "supabase-admin-idempotency-key",
      ),
    ).rejects.toMatchObject({
      status: 409,
      message: "Failed to add buy to holding 'AAPL.NAS': currency mismatch",
    } satisfies Partial<SupabaseApiError>);
  });

  it("propagates idempotency payload mismatch as conflict", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          code: "23505",
          details: "holdings_add_buy_idempotency_payload_mismatch",
          message: "duplicate key value violates unique constraint",
        }),
        {
          status: 409,
          headers: { "content-type": "application/json" },
        },
      ),
    );

    await expect(
      addBuyToHolding(
        "AAPL.NAS",
        {
          buy_quantity: 1,
          buy_price: 100,
        },
        "supabase-admin-idempotency-key",
      ),
    ).rejects.toMatchObject({
      status: 409,
      message:
        "Failed to add buy to holding 'AAPL.NAS': duplicate key value violates unique constraint",
      code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
      upstreamCode: "23505",
      details: "holdings_add_buy_idempotency_payload_mismatch",
    } satisfies Partial<SupabaseApiError>);
  });

  it("maps Supabase timeout failures to SupabaseApiError(504)", async () => {
    const timeoutError = Object.assign(new Error("request timed out"), {
      name: "TimeoutError",
    });
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(timeoutError);

    await expect(
      addBuyToHolding(
        "AAPL.NAS",
        {
          buy_quantity: 1,
          buy_price: 100,
        },
        "supabase-admin-idempotency-key",
      ),
    ).rejects.toMatchObject({
      status: 504,
    } satisfies Partial<SupabaseApiError>);
  });
});
