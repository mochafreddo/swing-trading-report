import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assertLocalRequest,
  isLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";

function makeRequest(headers: Record<string, string>): { headers: Headers } {
  return { headers: new Headers(headers) };
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("local-request-guard", () => {
  it("detects localhost and loopback hosts", () => {
    expect(isLocalRequest(makeRequest({ host: "localhost:3000" }))).toBe(true);
    expect(isLocalRequest(makeRequest({ host: "127.0.0.1:55300" }))).toBe(true);
    expect(isLocalRequest(makeRequest({ host: "[::1]:3000" }))).toBe(true);
    expect(isLocalRequest(makeRequest({ host: "example.com" }))).toBe(false);
  });

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

  it("ignores x-forwarded-host and trusts host only", () => {
    vi.stubEnv("NODE_ENV", "development");

    expect(() =>
      assertLocalRequest(
        makeRequest({
          host: "localhost:3000",
          "x-forwarded-host": "example.com",
        }),
      ),
    ).not.toThrow();

    expect(() =>
      assertLocalRequest(
        makeRequest({
          host: "example.com",
          "x-forwarded-host": "localhost:3000",
        }),
      ),
    ).toThrow(LocalRequestGuardError);
  });

  it("rejects non-local hosts by default", () => {
    vi.stubEnv("NODE_ENV", "production");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "example.com" })),
    ).toThrow(LocalRequestGuardError);
  });

  it("does not block non-local hosts when strict enforcement is explicitly disabled", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_ENFORCE_LOCAL_REQUEST", "0");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "example.com" })),
    ).not.toThrow();
  });

  it("rejects non-local hosts when strict enforcement is enabled", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_ENFORCE_LOCAL_REQUEST", "1");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "example.com" })),
    ).toThrow(LocalRequestGuardError);
  });

  it("allows requests in test environment even when strict enforcement is enabled", () => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("SAB_ENFORCE_LOCAL_REQUEST", "1");

    expect(() =>
      assertLocalRequest(makeRequest({ host: "example.com" })),
    ).not.toThrow();
  });
});
