import { describe, expect, it } from "vitest";

import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

function makeRequest(
  requestUrl: string,
  headers: Record<string, string>,
): { headers: Headers; nextUrl: URL } {
  return { headers: new Headers(headers), nextUrl: new URL(requestUrl) };
}

function makeHeadersOnlyRequest(headers: Record<string, string>): {
  headers: Headers;
} {
  return { headers: new Headers(headers) };
}

describe("same-origin", () => {
  it("allows matching Origin", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:55300/api/auth/logout", {
          origin: "http://localhost:55300",
        }),
      ),
    ).not.toThrow();
  });

  it("rejects mismatched Origin", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:55300/api/auth/logout", {
          origin: "https://evil.example",
        }),
      ),
    ).toThrow(SameOriginError);
  });

  it("rejects cross-site fetch metadata when Origin missing", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:55300/api/auth/logout", {
          "sec-fetch-site": "cross-site",
        }),
      ),
    ).toThrow(SameOriginError);
  });

  it("allows Origin that matches Host when nextUrl has internal port", () => {
    expect(() =>
      assertSameOrigin(
        makeRequest("http://localhost:3000/api/auth/logout", {
          origin: "http://localhost:55300",
          host: "localhost:55300",
          "x-forwarded-proto": "http",
        }),
      ),
    ).not.toThrow();
  });

  it("allows matching Origin when only headers are available", () => {
    expect(() =>
      assertSameOrigin(
        makeHeadersOnlyRequest({
          host: "localhost:55300",
          origin: "http://localhost:55300",
        }),
      ),
    ).not.toThrow();
  });

  it("rejects mismatched Origin when only headers are available", () => {
    expect(() =>
      assertSameOrigin(
        makeHeadersOnlyRequest({
          host: "localhost:55300",
          origin: "https://evil.example",
        }),
      ),
    ).toThrow(SameOriginError);
  });

  it("allows same-origin fetch metadata when only headers are available", () => {
    expect(() =>
      assertSameOrigin(
        makeHeadersOnlyRequest({
          host: "localhost:55300",
          "sec-fetch-site": "same-origin",
        }),
      ),
    ).not.toThrow();
  });
});
