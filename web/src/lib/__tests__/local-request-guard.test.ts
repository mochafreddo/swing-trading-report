import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";

function makeRequest(headers: Record<string, string>): { headers: Headers } {
  return { headers: new Headers(headers) };
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("local-request-guard", () => {
  it("allows localhost and loopback hosts", () => {
    vi.stubEnv("NODE_ENV", "development");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "localhost:3000" })),
    ).not.toThrow();
    expect(() =>
      assertLocalRequest(makeRequest({ host: "127.0.0.1:55300" })),
    ).not.toThrow();
    expect(() =>
      assertLocalRequest(makeRequest({ host: "[::1]:3000" })),
    ).not.toThrow();
  });

  it("uses x-forwarded-host first when present", () => {
    vi.stubEnv("NODE_ENV", "development");

    expect(() =>
      assertLocalRequest(
        makeRequest({
          host: "localhost:3000",
          "x-forwarded-host": "example.com",
        }),
      ),
    ).toThrow(LocalRequestGuardError);
  });

  it("rejects non-local hosts", () => {
    vi.stubEnv("NODE_ENV", "production");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "example.com" })),
    ).toThrow(LocalRequestGuardError);
  });

  it("allows requests in test environment", () => {
    vi.stubEnv("NODE_ENV", "test");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "example.com" })),
    ).not.toThrow();
  });
});
