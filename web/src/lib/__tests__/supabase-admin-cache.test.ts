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
  listAllStorageKeysCached,
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
});
