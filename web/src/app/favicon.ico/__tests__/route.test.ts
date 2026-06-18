import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { describe, expect, it } from "vitest";

type FaviconRoute = {
  GET: () => Promise<Response> | Response;
};

describe("GET /favicon.ico route", () => {
  it("serves a cacheable favicon instead of a 404", async () => {
    const routePath = path.resolve(
      process.cwd(),
      "src/app/favicon.ico/route.ts",
    );
    expect(
      fs.existsSync(routePath),
      "Expected an App Router favicon route",
    ).toBe(true);

    const route = (await import(pathToFileURL(routePath).href)) as FaviconRoute;
    const response = await route.GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("image/svg+xml");
    expect(response.headers.get("cache-control")).toBe("public, max-age=86400");
    expect(await response.text()).toContain("<svg");
  });
});
