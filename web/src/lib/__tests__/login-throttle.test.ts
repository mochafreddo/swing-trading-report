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

  it("blocks after max failed attempts", () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "30");

    const key = "local:sab";
    const now = 1_700_000_000_000;

    assertLoginAttemptAllowed(key, now);
    recordLoginAttemptFailure(key, now + 1_000);
    recordLoginAttemptFailure(key, now + 2_000);

    expect(() => assertLoginAttemptAllowed(key, now + 2_500)).toThrow(
      LoginThrottleError,
    );
  });

  it("resets block after clear", () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "1");

    const key = "local:sab";
    const now = 1_700_000_000_000;

    recordLoginAttemptFailure(key, now);
    expect(() => assertLoginAttemptAllowed(key, now + 500)).toThrow(
      LoginThrottleError,
    );

    clearLoginAttemptFailures(key);
    expect(() => assertLoginAttemptAllowed(key, now + 600)).not.toThrow();
  });

  it("caps tracked key count to bounded size", () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "1");

    for (let index = 0; index < 700; index += 1) {
      recordLoginAttemptFailure(`user-${index}`, 1_700_000_000_000 + index);
    }

    expect(__getTrackedLoginThrottleKeyCountForTests()).toBeLessThanOrEqual(
      512,
    );
  });

  it("preserves global throttle state when per-user eviction happens", () => {
    vi.stubEnv("SAB_LOGIN_MAX_ATTEMPTS", "2");
    vi.stubEnv("SAB_LOGIN_WINDOW_SECONDS", "900");
    vi.stubEnv("SAB_LOGIN_BLOCK_SECONDS", "600");

    const globalKey = buildGlobalLoginThrottleKey();
    const now = 1_700_000_000_000;

    recordLoginAttemptFailure(globalKey, now);
    recordLoginAttemptFailure(globalKey, now + 1_000);

    for (let index = 0; index < 700; index += 1) {
      recordLoginAttemptFailure(`user-${index}`, now + 2_000 + index);
    }

    expect(__getTrackedLoginThrottleKeyCountForTests()).toBeLessThanOrEqual(
      512,
    );
    expect(() => assertLoginAttemptAllowed(globalKey, now + 3_000)).toThrow(
      LoginThrottleError,
    );
  });
});
