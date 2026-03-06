import { describe, expect, it, vi } from "vitest";

import {
  enforceStartupBindGuard,
  evaluateStartupBindGuard,
} from "./startup-bind-guard.mjs";

describe("startup bind guard", () => {
  it("allows loopback binds by default", () => {
    expect(
      evaluateStartupBindGuard({
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toEqual({
      bindHost: "127.0.0.1",
      warning: null,
      error: null,
    });
  });

  it("warns when binding beyond loopback with the local-request guard enabled", () => {
    const logger = { warn: vi.fn() };

    expect(() =>
      enforceStartupBindGuard(
        {
          WEB_BIND_HOST: "0.0.0.0",
          SAB_ENFORCE_LOCAL_REQUEST: "1",
        },
        logger,
      ),
    ).not.toThrow();

    expect(logger.warn).toHaveBeenCalledWith(
      expect.stringContaining("Docker Compose localhost publishing"),
    );
  });

  it("refuses non-loopback binds when the local-request guard is disabled", () => {
    expect(() =>
      enforceStartupBindGuard({
        WEB_BIND_HOST: "0.0.0.0",
        SAB_ENFORCE_LOCAL_REQUEST: "0",
      }),
    ).toThrow(/Refusing to start/);
  });

  it("allows loopback binds even when the local-request guard is disabled", () => {
    expect(() =>
      enforceStartupBindGuard({
        WEB_BIND_HOST: "[::1]",
        SAB_ENFORCE_LOCAL_REQUEST: "0",
      }),
    ).not.toThrow();
  });
});
