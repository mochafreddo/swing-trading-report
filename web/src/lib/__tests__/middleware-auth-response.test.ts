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
    ]);
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
