import { describe, expect, it } from "vitest";

import { resolveSelectedKeyFromUrl } from "@/components/reports/selected-key-sync";

describe("resolveSelectedKeyFromUrl", () => {
  it("clears selected key when URL key is removed", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: null,
      availableKeys: [],
    });

    expect(result).toBeNull();
  });

  it("keeps previous selection on the initial hydration gap only", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: "2026/02/2026-02-28.buy.json",
      nextKeyRaw: null,
      availableKeys: ["2026/02/2026-02-28.buy.json"],
      preserveSelectionWhenKeyMissing: true,
    });

    expect(result).toBe("2026/02/2026-02-28.buy.json");
  });

  it("clears previous selection when URL key is removed after hydration", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: "2026/02/2026-02-28.buy.json",
      nextKeyRaw: null,
      availableKeys: ["2026/02/2026-02-28.buy.json"],
    });

    expect(result).toBeNull();
  });

  it("applies URL key when it exists", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: "2026/02/2026-02-28.buy.json",
      availableKeys: ["2026/02/2026-02-28.buy.json"],
    });

    expect(result).toBe("2026/02/2026-02-28.buy.json");
  });

  it("trims URL key value", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: null,
      nextKeyRaw: " 2026/02/2026-02-27.buy.json ",
      availableKeys: ["2026/02/2026-02-27.buy.json"],
    });

    expect(result).toBe("2026/02/2026-02-27.buy.json");
  });

  it("keeps the current selection when URL key is not in the available list", () => {
    const result = resolveSelectedKeyFromUrl({
      previousSelectedKey: "2026/02/2026-02-28.buy.json",
      nextKeyRaw: "2026/02/2026-02-01.buy.json",
      availableKeys: ["2026/02/2026-02-28.buy.json"],
    });

    expect(result).toBe("2026/02/2026-02-28.buy.json");
  });
});
