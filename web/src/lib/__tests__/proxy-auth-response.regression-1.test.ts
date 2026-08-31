import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { config, proxy } from "../../proxy";

describe("proxy auth response shape", () => {
  it("redirects unauthorized page requests to /login before rendering protected pages", async () => {
    // Regression: ISSUE-002 - protected pages rendered before Next 16 proxy auth gate
    // Found by /qa on 2026-06-22
    // Report: .gstack/qa-reports/qa-report-127-0-0-1-55301-2026-06-22.md
    const request = new NextRequest("http://localhost:55300/reports", {
      method: "GET",
    });
    const response = await proxy(request);

    expect(config.matcher).toContain("/reports/:path*");
    expect(config.matcher).toContain("/today/:path*");
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:55300/login?next=%2Freports",
    );
  });
});
