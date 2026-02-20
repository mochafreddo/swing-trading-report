import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { POST as loginPost } from "@/app/api/auth/login/route";
import { POST as logoutPost } from "@/app/api/auth/logout/route";
import { ADMIN_SESSION_COOKIE_NAME } from "@/lib/admin-session";
import { __resetLoginThrottleForTests } from "@/lib/login-throttle";

afterEach(() => {
  __resetLoginThrottleForTests();
  vi.unstubAllEnvs();
});

describe("auth routes", () => {
  it("sets signed session cookie on successful login", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");

    const request = new NextRequest("http://localhost:55300/api/auth/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://localhost:55300",
      },
      body: JSON.stringify({ username: "sab", password: "pass" }),
    });

    const response = await loginPost(request);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true });
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain(`${ADMIN_SESSION_COOKIE_NAME}=`);
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=lax");
    expect(setCookie).toContain("Path=/");
  });

  it("returns 401 JSON on login failure", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");

    const request = new NextRequest("http://localhost:55300/api/auth/login", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://localhost:55300",
      },
      body: JSON.stringify({ username: "sab", password: "wrong" }),
    });

    const response = await loginPost(request);

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toEqual({ error: "Unauthorized" });
  });

  it("returns 429 after repeated failed login attempts", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");

    const makeRequest = () =>
      new NextRequest("http://localhost:55300/api/auth/login", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: "http://localhost:55300",
        },
        body: JSON.stringify({ username: "sab", password: "wrong" }),
      });

    const first = await loginPost(makeRequest());
    const second = await loginPost(makeRequest());
    const third = await loginPost(makeRequest());

    expect(first.status).toBe(401);
    expect(second.status).toBe(401);
    expect(third.status).toBe(429);
    expect(third.headers.get("retry-after")).toBe("60");
    await expect(third.json()).resolves.toEqual({
      error: "Too many login attempts. Try again later.",
    });
  });

  it("applies global throttle across different usernames", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");

    const makeRequest = (username: string) =>
      new NextRequest("http://localhost:55300/api/auth/login", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: "http://localhost:55300",
        },
        body: JSON.stringify({ username, password: "wrong" }),
      });

    const first = await loginPost(makeRequest("sab"));
    const second = await loginPost(makeRequest("other-user"));
    const third = await loginPost(makeRequest("another-user"));

    expect(first.status).toBe(401);
    expect(second.status).toBe(401);
    expect(third.status).toBe(429);
  });

  it("does not double-count when username matches global sentinel", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");

    const makeRequest = () =>
      new NextRequest("http://localhost:55300/api/auth/login", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: "http://localhost:55300",
        },
        body: JSON.stringify({ username: "__global__", password: "wrong" }),
      });

    const first = await loginPost(makeRequest());
    const second = await loginPost(makeRequest());
    const third = await loginPost(makeRequest());

    expect(first.status).toBe(401);
    expect(second.status).toBe(401);
    expect(third.status).toBe(429);
  });

  it("keeps global throttle enforced under username spray beyond key cap", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "513");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");

    const makeRequest = (username: string) =>
      new NextRequest("http://localhost:55300/api/auth/login", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: "http://localhost:55300",
        },
        body: JSON.stringify({ username, password: "wrong" }),
      });

    let lastPreBlockStatus = 0;
    for (let index = 0; index < 513; index += 1) {
      const response = await loginPost(makeRequest(`spray-${index}`));
      lastPreBlockStatus = response.status;
    }

    expect(lastPreBlockStatus).toBe(401);

    const blocked = await loginPost(makeRequest("spray-block"));
    expect(blocked.status).toBe(429);
    expect(blocked.headers.get("retry-after")).toBe("60");
    await expect(blocked.json()).resolves.toEqual({
      error: "Too many login attempts. Try again later.",
    });

    const stillBlocked = await loginPost(makeRequest("spray-next"));
    expect(stillBlocked.status).toBe(429);
  });

  it("clears session cookie on logout", async () => {
    const request = new NextRequest("http://localhost:55300/api/auth/logout", {
      method: "POST",
      headers: {
        origin: "http://localhost:55300",
        cookie: `${ADMIN_SESSION_COOKIE_NAME}=dummy`,
      },
    });

    const response = await logoutPost(request);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true });
    const setCookie = response.headers.get("set-cookie") ?? "";
    expect(setCookie).toContain(`${ADMIN_SESSION_COOKIE_NAME}=`);
    expect(setCookie).toContain("Max-Age=0");
  });
});
