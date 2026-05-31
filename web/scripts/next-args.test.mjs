import { describe, expect, it } from "vitest";

import { hasOption, resolveEffectiveBindHost } from "./next-args.mjs";

describe("next args", () => {
  it("uses explicit long hostname arguments for startup bind checks", () => {
    expect(
      resolveEffectiveBindHost(["--hostname", "0.0.0.0"], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("0.0.0.0");
  });

  it("uses explicit inline hostname arguments for startup bind checks", () => {
    expect(
      resolveEffectiveBindHost(["--hostname=0.0.0.0"], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("0.0.0.0");
  });

  it("detects short hostname arguments with attached values", () => {
    expect(hasOption(["-H=0.0.0.0"], "--hostname", "-H")).toBe(true);
    expect(
      resolveEffectiveBindHost(["-H=0.0.0.0"], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("0.0.0.0");
  });

  it("preserves an explicitly empty hostname so startup validation can reject it", () => {
    expect(
      resolveEffectiveBindHost(["--hostname="], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("");
  });

  it("preserves a missing hostname value so startup validation can reject it", () => {
    expect(
      resolveEffectiveBindHost(["--hostname"], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("");
    expect(
      resolveEffectiveBindHost(["-H"], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("");
  });

  it("ignores hostname-like operands after the end-of-options marker", () => {
    expect(hasOption(["--", "--hostname", "0.0.0.0"], "--hostname", "-H")).toBe(
      false,
    );
    expect(
      resolveEffectiveBindHost(["--", "--hostname", "0.0.0.0"], {
        WEB_BIND_HOST: "127.0.0.1",
      }),
    ).toBe("127.0.0.1");
  });

  it("falls back to WEB_BIND_HOST when no hostname argument is provided", () => {
    expect(resolveEffectiveBindHost([], { WEB_BIND_HOST: "localhost" })).toBe(
      "localhost",
    );
  });
});
