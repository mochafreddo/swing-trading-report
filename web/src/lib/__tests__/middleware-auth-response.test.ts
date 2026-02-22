import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { config, middleware } from "../../../middleware";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("middleware auth response shape", () => {
  it("limits middleware execution to protected routes", () => {
    expect(config.matcher).toEqual([
      "/",
      "/holdings/:path*",
      "/reports/:path*",
      "/run/:path*",
      "/api/holdings/:path*",
      "/api/reports/:path*",
      "/api/run/:path*",
    ]);
  });

  it("returns JSON for unauthorized /api requests", async () => {
    const request = new NextRequest("http://localhost:55300/api/holdings", {
      method: "GET",
    });
    const response = await middleware(request);

    expect(response.status).toBe(401);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(response.headers.get("www-authenticate")).toBeNull();
    await expect(response.json()).resolves.toEqual({ error: "Unauthorized" });
  });

  it("redirects unauthorized page requests to /login", async () => {
    const request = new NextRequest("http://localhost:55300/holdings", {
      method: "GET",
    });
    const response = await middleware(request);

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:55300/login?next=%2Fholdings",
    );
  });
});
