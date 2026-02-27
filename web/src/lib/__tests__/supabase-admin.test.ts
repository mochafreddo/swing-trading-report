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
  fetchReportIndexPage,
  createHolding,
  deleteHolding,
  SupabaseApiError,
  updateHolding,
  upsertReportIndexEntry,
} from "@/lib/supabase-admin";

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

function holdingRow(
  overrides: Partial<{
    ticker: string;
    quantity: number;
    entry_price: number;
  }> = {},
) {
  return {
    ticker: overrides.ticker ?? "AAPL.US",
    quantity: overrides.quantity ?? 1,
    entry_price: overrides.entry_price ?? 100,
    entry_currency: null,
    entry_date: null,
    strategy: null,
    notes: null,
    tags: [],
    stop_override: null,
    target_override: null,
    created_at: "2026-02-24T00:00:00Z",
    updated_at: "2026-02-24T00:00:00Z",
  };
}

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
