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
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
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
