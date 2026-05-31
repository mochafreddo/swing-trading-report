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

  it("refuses non-loopback binds without an explicit unsafe override", () => {
    expect(() =>
      enforceStartupBindGuard({
        WEB_BIND_HOST: "0.0.0.0",
        SAB_ENFORCE_LOCAL_REQUEST: "1",
      }),
    ).toThrow(/SAB_ALLOW_NON_LOOPBACK_BIND=1/);
  });

  it("warns when an explicit unsafe override allows binding beyond loopback", () => {
    const logger = { warn: vi.fn() };

    expect(() =>
      enforceStartupBindGuard(
        {
          WEB_BIND_HOST: "0.0.0.0",
          SAB_ALLOW_NON_LOOPBACK_BIND: "1",
        },
        logger,
      ),
    ).not.toThrow();

    expect(logger.warn).toHaveBeenCalledWith(
      expect.stringContaining("SAB_ALLOW_NON_LOOPBACK_BIND=1"),
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

  it("checks the effective bind host selected by CLI arguments", () => {
    expect(() =>
      enforceStartupBindGuard(
        {
          WEB_BIND_HOST: "127.0.0.1",
          SAB_ENFORCE_LOCAL_REQUEST: "1",
        },
        console,
        { bindHost: "0.0.0.0" },
      ),
    ).toThrow(/SAB_ALLOW_NON_LOOPBACK_BIND=1/);
  });

  it("rejects an explicitly empty effective bind host", () => {
    expect(() =>
      enforceStartupBindGuard(
        {
          WEB_BIND_HOST: "127.0.0.1",
        },
        console,
        { bindHost: "" },
      ),
    ).toThrow(/--hostname must not be empty/);
  });
});
