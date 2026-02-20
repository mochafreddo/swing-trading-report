import { describe, expect, it } from "vitest";

import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

function makeRequest(
  origin: string,
  headers: Record<string, string>,
): { headers: Headers; nextUrl: URL } {
  return { headers: new Headers(headers), nextUrl: new URL(origin) };
}

describe("same-origin", () => {
  it("allows matching Origin", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:55300", {
          origin: "http://localhost:55300",
        }),
      ),
    ).not.toThrow();
  });

  it("rejects mismatched Origin", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:55300", {
          origin: "https://evil.example",
        }),
      ),
    ).toThrow(SameOriginError);
  });

  it("rejects cross-site fetch metadata when Origin missing", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:55300", {
          "sec-fetch-site": "cross-site",
        }),
      ),
    ).toThrow(SameOriginError);
  });
});
