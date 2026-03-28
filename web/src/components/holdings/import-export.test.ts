import { afterEach, describe, expect, it, vi } from "vitest";

import {
  requestHoldingsYamlExport,
  requestHoldingsYamlImport,
} from "@/components/holdings/import-export";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("holdings import/export requests", () => {
  it("reads filename and text from holdings YAML export", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response("version: 1\nholdings: []\n", {
          status: 200,
          headers: {
            "content-disposition": 'attachment; filename="holdings.yaml"',
          },
        }),
    );

    await expect(requestHoldingsYamlExport(fetcher)).resolves.toEqual({
      filename: "holdings.yaml",
      document: "version: 1\nholdings: []\n",
    });
  });

  it("surfaces JSON error messages from export failures", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: "export failed" }), {
          status: 500,
          headers: { "content-type": "application/json" },
        }),
    );

    await expect(requestHoldingsYamlExport(fetcher)).rejects.toThrow(
      "export failed",
    );
  });

  it("posts dry-run/apply payloads to import route", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            mode: "dry-run",
            summary: {
              incomingCount: 1,
              createCount: 1,
              updateCount: 0,
              deleteCount: 0,
              unchangedCount: 0,
              createTickers: ["TSLA.NAS"],
              updateTickers: [],
              deleteTickers: [],
            },
          }),
          {
            status: 200,
            headers: { "content-type": "application/json" },
          },
        ),
    );

    const response = await requestHoldingsYamlImport(
      "holdings: []",
      false,
      fetcher,
    );

    expect(response.mode).toBe("dry-run");
    expect(fetcher).toHaveBeenCalledWith("/api/holdings/yaml", {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        document: "holdings: []",
        apply: false,
      }),
    });
  });
});
