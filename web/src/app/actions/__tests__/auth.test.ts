import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  cookieStore,
  cookies,
  headers,
  performAdminLogin,
  getAdminSessionCookieOptions,
  state,
} = vi.hoisted(() => {
  const cookieStore = {
    set: vi.fn(),
  };
  const state = {
    requestHeaders: new Headers({
      host: "localhost:55300",
      origin: "http://localhost:55300",
    }),
  };

  return {
    state,
    cookieStore,
    cookies: vi.fn(async () => cookieStore),
    headers: vi.fn(async () => state.requestHeaders),
    performAdminLogin: vi.fn(),
    getAdminSessionCookieOptions: vi.fn((maxAge?: number) => ({
      httpOnly: true,
      maxAge,
    })),
  };
});

vi.mock("next/headers", () => ({
  cookies,
  headers,
}));

vi.mock("@/lib/admin-login", () => ({
  performAdminLogin,
}));

vi.mock("@/lib/admin-session", () => ({
  ADMIN_SESSION_COOKIE_NAME: "sab_admin_session",
  getAdminSessionCookieOptions,
}));

import { loginAction, logoutAction } from "@/app/actions/auth";

describe("auth actions", () => {
  beforeEach(() => {
    state.requestHeaders = new Headers({
      host: "localhost:55300",
      origin: "http://localhost:55300",
    });
    cookieStore.set.mockReset();
    cookies.mockClear();
    headers.mockClear();
    performAdminLogin.mockReset();
    getAdminSessionCookieOptions.mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("sets the session cookie after a successful login", async () => {
    performAdminLogin.mockResolvedValue({
      ok: true,
      token: "signed-token",
    });

    await expect(
      loginAction({
        username: "sab",
        password: "pass",
      }),
    ).resolves.toEqual({ ok: true });

    expect(cookieStore.set).toHaveBeenCalledWith(
      "sab_admin_session",
      "signed-token",
      {
        httpOnly: true,
        maxAge: undefined,
      },
    );
  });

  it("returns the login error without mutating cookies", async () => {
    performAdminLogin.mockResolvedValue({
      ok: false,
      error: "Unauthorized",
    });

    await expect(
      loginAction({
        username: "sab",
        password: "wrong",
      }),
    ).resolves.toEqual({
      ok: false,
      error: "Unauthorized",
    });

    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("blocks login attempts from non-local hosts", async () => {
    vi.stubEnv("NODE_ENV", "production");
    state.requestHeaders = new Headers({
      host: "example.com",
      origin: "https://example.com",
    });

    await expect(
      loginAction({
        username: "sab",
        password: "pass",
      }),
    ).resolves.toEqual({
      ok: false,
      error: "API is only available from local host",
    });

    expect(performAdminLogin).not.toHaveBeenCalled();
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("clears the session cookie on logout", async () => {
    await expect(logoutAction()).resolves.toEqual({ ok: true });

    expect(cookieStore.set).toHaveBeenCalledWith("sab_admin_session", "", {
      httpOnly: true,
      maxAge: 0,
    });
  });

  it("blocks logout from cross-site requests", async () => {
    vi.stubEnv("NODE_ENV", "production");
    state.requestHeaders = new Headers({
      host: "localhost:55300",
      origin: "https://evil.example",
    });

    await expect(logoutAction()).resolves.toEqual({
      ok: false,
      error: "Cross-site request blocked",
    });

    expect(cookieStore.set).not.toHaveBeenCalled();
  });
});
