import { describe, expect, it } from "vitest";

import {
  readApiError,
  readApiErrorCode,
  toErrorMessage,
} from "@/lib/error-utils";

describe("error-utils", () => {
  it("reads non-empty string fields from API error payloads", () => {
    expect(readApiError({ error: "failed" })).toBe("failed");
    expect(readApiErrorCode({ code: "CONFLICT" })).toBe("CONFLICT");
  });

  it("ignores missing, blank, non-string, and non-object API error fields", () => {
    expect(readApiError({ error: "   " })).toBeUndefined();
    expect(readApiError({ error: 500 })).toBeUndefined();
    expect(readApiError(["failed"])).toBeUndefined();
    expect(readApiError(null)).toBeUndefined();
  });

  it("uses Error.message when converting unknown errors", () => {
    expect(toErrorMessage(new Error("boom"))).toBe("boom");
    expect(toErrorMessage("boom", "fallback")).toBe("fallback");
  });
});
