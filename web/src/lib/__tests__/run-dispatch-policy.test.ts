import { describe, expect, it } from "vitest";

import {
  coerceScanUniverseForProvider,
  isScanUniverseAllowed,
} from "@/lib/run-dispatch-policy";

describe("isScanUniverseAllowed", () => {
  it("allows all scan universes for kis", () => {
    expect(isScanUniverseAllowed("kis", "KR")).toBe(true);
    expect(isScanUniverseAllowed("kis", "US")).toBe(true);
    expect(isScanUniverseAllowed("kis", "both")).toBe(true);
  });

  it("allows only KR scan universe for pykrx", () => {
    expect(isScanUniverseAllowed("pykrx", "KR")).toBe(true);
    expect(isScanUniverseAllowed("pykrx", "US")).toBe(false);
    expect(isScanUniverseAllowed("pykrx", "both")).toBe(false);
  });
});

describe("coerceScanUniverseForProvider", () => {
  it("keeps already-allowed universes", () => {
    expect(coerceScanUniverseForProvider("kis", "US")).toBe("US");
    expect(coerceScanUniverseForProvider("kis", "both")).toBe("both");
    expect(coerceScanUniverseForProvider("pykrx", "KR")).toBe("KR");
  });

  it("coerces disallowed pykrx universes to KR", () => {
    expect(coerceScanUniverseForProvider("pykrx", "US")).toBe("KR");
    expect(coerceScanUniverseForProvider("pykrx", "both")).toBe("KR");
  });
});
