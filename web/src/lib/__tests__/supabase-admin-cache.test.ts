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
  __resetStorageKeysCacheForTests,
  fetchReportIndexPage,
  listAllStorageKeysCached,
  upsertReportIndexEntry,
} from "@/lib/supabase-admin";

const REPORT_KEY_A = "2026/02/2026-02-14.buy.json";
const REPORT_KEY_B = "2026/02/2026-02-13.buy.json";

function storageListResponse(keys: string[]): Response {
  return new Response(JSON.stringify(keys.map((key) => ({ name: key }))), {
    status: 200,
    headers: {
      "content-type": "application/json",
    },
  });
}

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
  __resetStorageKeysCacheForTests();
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe("listAllStorageKeysCached", () => {
  it("reuses cached keys within TTL", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(storageListResponse([REPORT_KEY_A]));

    const first = await listAllStorageKeysCached("reports", 30);
    const second = await listAllStorageKeysCached("reports", 30);

    expect(first).toEqual([REPORT_KEY_A]);
    expect(second).toEqual([REPORT_KEY_A]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("refreshes cache after TTL expiry", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-02-20T05:00:00Z"));

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(storageListResponse([REPORT_KEY_A]))
      .mockResolvedValueOnce(storageListResponse([REPORT_KEY_B]));

    const first = await listAllStorageKeysCached("reports", 30);
    vi.setSystemTime(new Date("2026-02-20T05:00:31Z"));
    const second = await listAllStorageKeysCached("reports", 30);

    expect(first).toEqual([REPORT_KEY_A]);
    expect(second).toEqual([REPORT_KEY_B]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shares in-flight request per bucket", async () => {
    let resolveFetch: ((value: Response) => void) | undefined;
    const fetchPromise = new Promise<Response>((resolve) => {
      resolveFetch = (value: Response) => resolve(value);
    });

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(() => fetchPromise);

    const firstPromise = listAllStorageKeysCached("reports", 30);
    const secondPromise = listAllStorageKeysCached("reports", 30);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    if (!resolveFetch) {
      throw new Error("expected resolver to be initialized");
    }
    resolveFetch(storageListResponse([REPORT_KEY_A]));

    const [first, second] = await Promise.all([firstPromise, secondPromise]);
    expect(first).toEqual([REPORT_KEY_A]);
    expect(second).toEqual([REPORT_KEY_A]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not cache failed list calls", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ message: "boom" }), { status: 500 }),
      )
      .mockResolvedValueOnce(storageListResponse([REPORT_KEY_A]));

    await expect(listAllStorageKeysCached("reports", 30)).rejects.toThrow(
      "Failed to list storage objects",
    );

    const second = await listAllStorageKeysCached("reports", 30);
    expect(second).toEqual([REPORT_KEY_A]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("uses supabase runtime_state cache when configured", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_RUNTIME_STATE_STORE", "supabase");

    const runtimeState = new Map<
      string,
      { state_payload: Record<string, unknown>; expires_at: string }
    >();

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = new URL(String(input));
        const method = init?.method ?? "GET";

        if (url.pathname.endsWith("/rest/v1/runtime_state")) {
          const stateKeyFilter = url.searchParams.get("state_key") ?? "";
          const stateKey = stateKeyFilter.startsWith("eq.")
            ? stateKeyFilter.slice(3)
            : "";

          if (method === "GET") {
            const row = runtimeState.get(stateKey);
            return new Response(
              JSON.stringify(row ? [{ state_key: stateKey, ...row }] : []),
              {
                status: 200,
                headers: { "content-type": "application/json" },
              },
            );
          }

          if (method === "POST") {
            const body = JSON.parse(String(init?.body)) as Array<{
              state_key: string;
              state_payload: Record<string, unknown>;
              expires_at: string;
            }>;
            const row = body[0];
            runtimeState.set(row.state_key, {
              state_payload: row.state_payload,
              expires_at: row.expires_at,
            });
            return new Response("", { status: 201 });
          }

          throw new Error(`Unexpected runtime_state method: ${method}`);
        }

        if (url.pathname.includes("/storage/v1/object/list/reports")) {
          return storageListResponse([REPORT_KEY_A]);
        }

        throw new Error(`Unexpected URL: ${url.toString()}`);
      });

    const first = await listAllStorageKeysCached("reports", 30);
    const second = await listAllStorageKeysCached("reports", 30);

    expect(first).toEqual([REPORT_KEY_A]);
    expect(second).toEqual([REPORT_KEY_A]);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("continues when stale runtime_state cleanup fails", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_RUNTIME_STATE_STORE", "supabase");

    const staleExpiresAt = new Date("2026-02-20T04:59:00Z").toISOString();

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = new URL(String(input));
        const method = init?.method ?? "GET";

        if (
          url.pathname.endsWith("/rest/v1/runtime_state") &&
          method === "GET"
        ) {
          return new Response(
            JSON.stringify([
              {
                state_key: "storage_keys:reports",
                state_payload: { keys: [REPORT_KEY_B] },
                expires_at: staleExpiresAt,
              },
            ]),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }

        if (
          url.pathname.endsWith("/rest/v1/runtime_state") &&
          method === "DELETE"
        ) {
          return new Response(JSON.stringify({ message: "cleanup failed" }), {
            status: 500,
            headers: { "content-type": "application/json" },
          });
        }

        if (url.pathname.includes("/storage/v1/object/list/reports")) {
          return storageListResponse([REPORT_KEY_A]);
        }

        if (
          url.pathname.endsWith("/rest/v1/runtime_state") &&
          method === "POST"
        ) {
          return new Response("", { status: 201 });
        }

        throw new Error(`Unexpected request: ${method} ${url.toString()}`);
      });

    const result = await listAllStorageKeysCached("reports", 30);

    expect(result).toEqual([REPORT_KEY_A]);
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("shares in-flight request in supabase runtime_state mode", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_RUNTIME_STATE_STORE", "supabase");

    let resolveRuntimeGet: ((response: Response) => void) | undefined;
    const runtimeGetPromise = new Promise<Response>((resolve) => {
      resolveRuntimeGet = (response: Response) => resolve(response);
    });

    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = new URL(String(input));
        const method = init?.method ?? "GET";

        if (
          method === "GET" &&
          url.pathname.endsWith("/rest/v1/runtime_state")
        ) {
          return runtimeGetPromise;
        }

        if (url.pathname.includes("/storage/v1/object/list/reports")) {
          return storageListResponse([REPORT_KEY_A]);
        }

        if (
          method === "POST" &&
          url.pathname.endsWith("/rest/v1/runtime_state")
        ) {
          return new Response("", { status: 201 });
        }

        throw new Error(`Unexpected request: ${method} ${url.toString()}`);
      });

    const firstPromise = listAllStorageKeysCached("reports", 30);
    const secondPromise = listAllStorageKeysCached("reports", 30);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    if (!resolveRuntimeGet) {
      throw new Error("expected runtime_state resolver to be initialized");
    }
    resolveRuntimeGet(new Response("[]", { status: 200 }));

    const [first, second] = await Promise.all([firstPromise, secondPromise]);
    expect(first).toEqual([REPORT_KEY_A]);
    expect(second).toEqual([REPORT_KEY_A]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
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
