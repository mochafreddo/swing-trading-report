// @vitest-environment jsdom

import { act } from "react";
import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunClient } from "@/components/run-client";

function createDispatchResponse(): Response {
  return new Response(
    JSON.stringify({
      dispatched: true,
      workflow: "scan",
      workflowFile: "scan.yml",
      workflowUrl: "https://github.com/owner/repo/actions/workflows/scan.yml",
      actionsUrl: "https://github.com/owner/repo/actions",
      ref: "main",
    }),
    {
      status: 202,
      headers: {
        "Content-Type": "application/json",
      },
    },
  );
}

function findSelect(container: HTMLElement, name: string): HTMLSelectElement {
  const element = container.querySelector(
    `select[name="${name}"]`,
  ) as HTMLSelectElement | null;
  if (!element) {
    throw new Error(`select[name="${name}"] not found`);
  }
  return element;
}

function findButton(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find((item) =>
    item.textContent?.includes(text),
  ) as HTMLButtonElement | undefined;
  if (!button) {
    throw new Error(`button containing "${text}" not found`);
  }
  return button;
}

function findOption(
  select: HTMLSelectElement,
  value: string,
): HTMLOptionElement {
  const option = Array.from(select.options).find(
    (item) => item.value === value,
  );
  if (!option) {
    throw new Error(`option "${value}" not found`);
  }
  return option;
}

describe("RunClient", () => {
  let container: HTMLDivElement;
  let root: Root;
  let fetchMock: ReturnType<typeof vi.fn>;
  let previousActEnvironment: boolean | undefined;

  beforeEach(() => {
    previousActEnvironment = (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT;
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    fetchMock = vi.fn().mockResolvedValue(createDispatchResponse());
    vi.stubGlobal("fetch", fetchMock);

    act(() => {
      root.render(React.createElement(RunClient));
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  });

  it("coerces universe to KR and disables US/both options for pykrx provider", () => {
    const providerSelect = findSelect(container, "provider");
    const universeSelect = findSelect(container, "universe");

    expect(providerSelect.value).toBe("kis");
    expect(universeSelect.value).toBe("both");

    act(() => {
      providerSelect.value = "pykrx";
      providerSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(universeSelect.value).toBe("KR");
    expect(findOption(universeSelect, "US").disabled).toBe(true);
    expect(findOption(universeSelect, "both").disabled).toBe(true);
    expect(container.textContent).toContain(
      "pykrx provider는 scan에서 KR만 지원합니다.",
    );

    act(() => {
      providerSelect.value = "kis";
      providerSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(findOption(universeSelect, "US").disabled).toBe(false);
    expect(findOption(universeSelect, "both").disabled).toBe(false);
  });

  it("dispatches scan with KR universe after switching provider to pykrx", async () => {
    const providerSelect = findSelect(container, "provider");
    const runScanButton = findButton(container, "Run Scan");

    act(() => {
      providerSelect.value = "pykrx";
      providerSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await act(async () => {
      runScanButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/run");
    expect(options.method).toBe("POST");
    expect(JSON.parse(String(options.body))).toEqual({
      workflow: "scan",
      provider: "pykrx",
      universe: "KR",
    });
  });
});
