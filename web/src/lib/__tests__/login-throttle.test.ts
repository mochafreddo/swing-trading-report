import { afterEach, describe, expect, it, vi } from "vitest";

import {
  __resetLoginThrottleForTests,
  __getTrackedLoginThrottleKeyCountForTests,
  assertLoginAttemptAllowed,
  buildGlobalLoginThrottleKey,
  buildLoginThrottleKey,
  clearLoginAttemptFailures,
  LoginThrottleError,
  recordLoginAttemptFailure,
} from "@/lib/login-throttle";

afterEach(() => {
  __resetLoginThrottleForTests();
  vi.unstubAllEnvs();
});

describe("login-throttle", () => {
  it("builds namespaced key from normalized username", () => {
    expect(buildLoginThrottleKey("Admin ")).toBe("user:admin");
    expect(buildLoginThrottleKey("")).toBe("user:unknown");
    expect(buildGlobalLoginThrottleKey()).toBe("__global__");
    expect(buildLoginThrottleKey("__global__")).toBe("user:__global__");
  });

  it("blocks after max failed attempts", async () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "30");

    const key = "local:sab";
    const now = 1_700_000_000_000;

    await assertLoginAttemptAllowed(key, now);
    await recordLoginAttemptFailure(key, now + 1_000);
    await recordLoginAttemptFailure(key, now + 2_000);

    await expect(
      assertLoginAttemptAllowed(key, now + 2_500),
    ).rejects.toBeInstanceOf(LoginThrottleError);
  });

  it("resets block after clear", async () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "1");

    const key = "local:sab";
    const now = 1_700_000_000_000;

    await recordLoginAttemptFailure(key, now);
    await expect(
      assertLoginAttemptAllowed(key, now + 500),
    ).rejects.toBeInstanceOf(LoginThrottleError);

    await clearLoginAttemptFailures(key);
    await expect(
      assertLoginAttemptAllowed(key, now + 600),
    ).resolves.toBeUndefined();
  });

  it("throws on failure record while key is already blocked", async () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "1");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");

    const key = "local:sab";
    const now = 1_700_000_000_000;

    await recordLoginAttemptFailure(key, now);
    await expect(
      recordLoginAttemptFailure(key, now + 1_000),
    ).rejects.toBeInstanceOf(LoginThrottleError);
  });

  it("caps tracked key count to bounded size", async () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "1");

    for (let index = 0; index < 700; index += 1) {
      await recordLoginAttemptFailure(
        `user-${index}`,
        1_700_000_000_000 + index,
      );
    }

    expect(__getTrackedLoginThrottleKeyCountForTests()).toBeLessThanOrEqual(
      512,
    );
  });

  it("preserves global throttle state when per-user eviction happens", async () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "600");

    const globalKey = buildGlobalLoginThrottleKey();
    const now = 1_700_000_000_000;

    await recordLoginAttemptFailure(globalKey, now);
    await recordLoginAttemptFailure(globalKey, now + 1_000);

    for (let index = 0; index < 700; index += 1) {
      await recordLoginAttemptFailure(`user-${index}`, now + 2_000 + index);
    }

    expect(__getTrackedLoginThrottleKeyCountForTests()).toBeLessThanOrEqual(
      512,
    );
    await expect(
      assertLoginAttemptAllowed(globalKey, now + 3_000),
    ).rejects.toBeInstanceOf(LoginThrottleError);
  });

  it("stores throttle state in supabase runtime_state when configured", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_RUNTIME_STATE_STORE", "supabase");
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test_key");

    const runtimeState = new Map<
      string,
      { state_payload: Record<string, unknown>; expires_at: string }
    >();

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";
      if (
        url.pathname.endsWith("/rest/v1/rpc/consume_login_throttle_attempt")
      ) {
        const body = JSON.parse(String(init?.body)) as {
          p_state_key: string;
          p_now: string;
          p_window_seconds: number;
          p_block_seconds: number;
          p_max_attempts: number;
        };
        const now = Date.parse(body.p_now);
        const current = runtimeState.get(body.p_state_key);
        const parsedCurrent = current?.state_payload as
          | {
              failures?: number;
              windowStartedAt?: number;
              blockedUntil?: number;
            }
          | undefined;
        const windowMs = body.p_window_seconds * 1000;
        const blockMs = body.p_block_seconds * 1000;
        let failures = parsedCurrent?.failures ?? 0;
        let windowStartedAt = parsedCurrent?.windowStartedAt ?? now;
        let blockedUntil = parsedCurrent?.blockedUntil ?? 0;

        if (blockedUntil > now) {
          return new Response(
            JSON.stringify([
              {
                failures,
                window_started_at: windowStartedAt,
                blocked_until: blockedUntil,
                is_blocked: true,
                retry_after_seconds: Math.max(
                  1,
                  Math.ceil((blockedUntil - now) / 1000),
                ),
              },
            ]),
            { status: 200, headers: { "content-type": "application/json" } },
          );
        }

        if (
          now - windowStartedAt > windowMs ||
          (blockedUntil > 0 && blockedUntil <= now)
        ) {
          failures = 0;
          windowStartedAt = now;
          blockedUntil = 0;
        }

        failures += 1;
        if (failures >= body.p_max_attempts) {
          blockedUntil = now + blockMs;
        }

        runtimeState.set(body.p_state_key, {
          state_payload: {
            failures,
            windowStartedAt,
            blockedUntil,
          },
          expires_at: new Date(
            Math.max(windowStartedAt + windowMs, blockedUntil, now + 1_000),
          ).toISOString(),
        });
        return new Response(
          JSON.stringify([
            {
              failures,
              window_started_at: windowStartedAt,
              blocked_until: blockedUntil,
              is_blocked: false,
              retry_after_seconds: 0,
            },
          ]),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }

      if (url.pathname.endsWith("/rest/v1/runtime_state")) {
        const stateKeyFilter = url.searchParams.get("state_key") ?? "";
        const stateKey = stateKeyFilter.startsWith("eq.")
          ? stateKeyFilter.slice(3)
          : "";

        if (method === "GET") {
          const row = runtimeState.get(stateKey);
          return new Response(
            JSON.stringify(row ? [{ state_key: stateKey, ...row }] : []),
            {
              status: 200,
              headers: { "content-type": "application/json" },
            },
          );
        }

        if (method === "DELETE") {
          runtimeState.delete(stateKey);
          return new Response("", { status: 204 });
        }
      }

      throw new Error(`Unexpected request: ${method} ${url.toString()}`);
    });

    const key = buildLoginThrottleKey("sab");
    const now = 1_700_000_000_000;

    await recordLoginAttemptFailure(key, now);
    await recordLoginAttemptFailure(key, now + 1_000);
    await expect(
      recordLoginAttemptFailure(key, now + 2_000),
    ).rejects.toBeInstanceOf(LoginThrottleError);

    await expect(
      assertLoginAttemptAllowed(key, now + 2_500),
    ).rejects.toBeInstanceOf(LoginThrottleError);
  });

  it("ignores stale-state cleanup failure in supabase mode", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_RUNTIME_STATE_STORE", "supabase");
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "60");
    vi.stubEnv("SUPABASE_URL", "https://example.supabase.co");
    vi.stubEnv("SUPABASE_SECRET_KEY", "sb_secret_test_key");

    const key = buildLoginThrottleKey("sab");
    const staleExpiresAt = new Date(1_700_000_000_000 - 1_000).toISOString();

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";

      if (url.pathname.endsWith("/rest/v1/runtime_state") && method === "GET") {
        return new Response(
          JSON.stringify([
            {
              state_key: `login_throttle:${key}`,
              state_payload: {
                failures: 2,
                windowStartedAt: 1_700_000_000_000 - 10_000,
                blockedUntil: 1_700_000_000_000 - 5_000,
              },
              expires_at: staleExpiresAt,
            },
          ]),
          {
            status: 200,
            headers: { "content-type": "application/json" },
          },
        );
      }

      if (
        url.pathname.endsWith("/rest/v1/runtime_state") &&
        method === "DELETE"
      ) {
        return new Response(JSON.stringify({ message: "cleanup failed" }), {
          status: 500,
          headers: { "content-type": "application/json" },
        });
      }

      throw new Error(`Unexpected request: ${method} ${url.toString()}`);
    });

    await expect(
      assertLoginAttemptAllowed(key, 1_700_000_000_000),
    ).resolves.toBeUndefined();
  });
});
