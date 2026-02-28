import { describe, expect, it } from "vitest";

import { resolveSelectedKeyFromUrl } from "@/components/reports/selected-key-sync";

describe("resolveSelectedKeyFromUrl", () => {
  it("clears selected key when URL key is removed", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: null,
    });

    expect(result).toBeNull();
  });

  it("keeps previous selection when URL key is removed", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: "2026/02/2026-02-28.buy.json",
      nextKeyRaw: null,
    });

    expect(result).toBe("2026/02/2026-02-28.buy.json");
  });

  it("applies URL key when it exists", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: "2026/02/2026-02-28.buy.json",
    });

    expect(result).toBe("2026/02/2026-02-28.buy.json");
  });

  it("trims URL key value", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: " 2026/02/2026-02-27.buy.json ",
    });

    expect(result).toBe("2026/02/2026-02-27.buy.json");
  });
});
