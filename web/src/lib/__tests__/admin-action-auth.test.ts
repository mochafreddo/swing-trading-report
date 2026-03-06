import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { cookies, headers, requireAdminAuth, state, cookieStore } = vi.hoisted(
  () => {
    const state = {
      requestHeaders: new Headers({
        host: "localhost:55300",
        origin: "http://localhost:55300",
      }),
    };
    const cookieStore = { get: vi.fn() };

    return {
      state,
      cookieStore,
      headers: vi.fn(async () => state.requestHeaders),
      cookies: vi.fn(async () => cookieStore),
      requireAdminAuth: vi.fn(),
    };
  },
);

vi.mock("next/headers", () => ({
  headers,
  cookies,
}));

vi.mock("@/lib/admin-auth", () => ({
  requireAdminAuth,
}));

import { requireAdminActionSession } from "@/lib/admin-action-auth";

describe("admin-action-auth", () => {
  beforeEach(() => {
    state.requestHeaders = new Headers({
      host: "localhost:55300",
      origin: "http://localhost:55300",
    });
    headers.mockClear();
    cookies.mockClear();
    requireAdminAuth.mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("passes local same-origin requests through to admin auth", async () => {
    vi.stubEnv("NODE_ENV", "production");

    await expect(requireAdminActionSession()).resolves.toBeUndefined();

    expect(requireAdminAuth).toHaveBeenCalledWith({
      headers: state.requestHeaders,
      cookies: cookieStore,
    });
  });

  it("rejects cross-site requests before admin auth", async () => {
    vi.stubEnv("NODE_ENV", "production");
    state.requestHeaders = new Headers({
      host: "localhost:55300",
      origin: "https://evil.example",
    });

    await expect(requireAdminActionSession()).rejects.toThrow(
      "Cross-site request blocked",
    );

    expect(requireAdminAuth).not.toHaveBeenCalled();
  });

  it("rejects non-local hosts before admin auth", async () => {
    vi.stubEnv("NODE_ENV", "production");
    state.requestHeaders = new Headers({
      host: "example.com",
      origin: "https://example.com",
    });

    await expect(requireAdminActionSession()).rejects.toThrow(
      "API is only available from local host",
    );

    expect(requireAdminAuth).not.toHaveBeenCalled();
  });
});
