// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderHistoryPreview } from "@/components/order-history-preview";

describe("order aggregate synthetic preview", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => {
        throw new Error("network forbidden");
      }),
    );
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage forbidden");
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root.render(<OrderHistoryPreview />));
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT;
  });
  const submit = () =>
    act(() => {
      container
        .querySelector("form")!
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
    });
  const choose = (value: string) =>
    act(() => {
      (
        container.querySelector(`input[value="${value}"]`) as HTMLInputElement
      ).click();
    });

  it("renders order aggregates only after explicit submission, with no network or storage", () => {
    expect(container.querySelector("table")).toBeNull();
    submit();
    expect(container.textContent).toContain("조회 완료");
    expect(container.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(container.textContent).toContain("123.456789 USD");
    expect(container.textContent).toContain("SYNTHETIC_ONLY · NO ADVICE");
    expect(container.textContent).not.toContain("synthetic-order");
    expect(fetch).not.toHaveBeenCalled();
    expect(Storage.prototype.setItem).not.toHaveBeenCalled();
  });
  it("clears previous rows when the scenario changes and distinguishes empty, incomplete and error", () => {
    submit();
    for (const [scenario, expected] of [
      ["empty", "조회 결과 없음"],
      ["incomplete", "페이지 미완결"],
      ["invalid", "검증 실패"],
    ]) {
      choose(scenario);
      expect(container.querySelector("table")).toBeNull();
      submit();
      expect(container.textContent).toContain(expected);
      expect(container.querySelector("table")).toBeNull();
    }
  });
  it("clear and remount do not restore query results", () => {
    submit();
    act(() => {
      (
        container.querySelector('button[type="button"]') as HTMLButtonElement
      ).click();
    });
    expect(container.querySelector("table")).toBeNull();
    submit();
    act(() => {
      root.unmount();
    });
    root = createRoot(container);
    act(() => root.render(<OrderHistoryPreview />));
    expect(container.querySelector("table")).toBeNull();
  });
});
