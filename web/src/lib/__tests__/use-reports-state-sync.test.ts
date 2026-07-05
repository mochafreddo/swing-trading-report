// @vitest-environment jsdom

import { act } from "react";
import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useReportsState } from "@/components/reports/use-reports-state";
import type { ReportsInitialState } from "@/components/reports/types";

const navigationMock = vi.hoisted(() => {
  let searchParams = new URLSearchParams();

  return {
    replace: vi.fn(),
    pathname: "/reports",
    setSearchParams(value: string) {
      searchParams = new URLSearchParams(value);
    },
    getSearchParams() {
      return searchParams;
    },
  };
});

vi.mock("next/navigation", () => ({
  usePathname: () => navigationMock.pathname,
  useRouter: () => ({
    replace: navigationMock.replace,
  }),
  useSearchParams: () => navigationMock.getSearchParams(),
}));

const INITIAL_STATE: ReportsInitialState = {
  reportType: "all",
  query: "",
  appliedQuery: "",
  items: [
    {
      key: "2026/02/2026-02-28.buy.json",
      type: "buy",
      reportDate: "2026-02-28",
      duplicateIndex: 0,
    },
    {
      key: "2026/02/2026-02-27.buy.json",
      type: "buy",
      reportDate: "2026-02-27",
      duplicateIndex: 0,
    },
  ],
  total: 2,
  searched: 0,
  truncated: false,
  searchWindow: 100,
  warnings: [],
  selectedKey: "2026/02/2026-02-28.buy.json",
  detailKey: "2026/02/2026-02-28.buy.json",
  detail: {
    schema: "sab.report.v1",
    type: "buy",
  },
  showRaw: false,
};

const EMPTY_SEARCH_STATE: ReportsInitialState = {
  ...INITIAL_STATE,
  query: "AAPL",
  appliedQuery: "AAPL",
  items: [],
  total: 0,
  searched: 100,
  truncated: false,
  selectedKey: null,
  detailKey: null,
  detail: null,
};

function Harness({
  initialState,
}: {
  initialState: ReportsInitialState;
}): React.JSX.Element {
  const { selectedKey } = useReportsState(initialState);

  return React.createElement(
    "output",
    { "data-testid": "selected-key" },
    selectedKey ?? "none",
  );
}

function DetailHarness({
  initialState,
}: {
  initialState: ReportsInitialState;
}): React.JSX.Element {
  const { selectedKey, detail, loadingDetail, setSelectedKey } =
    useReportsState(initialState);
  const detailType = typeof detail?.type === "string" ? detail.type : "none";

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      "output",
      { "data-testid": "detail-state" },
      `${selectedKey ?? "none"}|${loadingDetail ? "loading" : "idle"}|${detailType}`,
    ),
    React.createElement(
      "button",
      {
        type: "button",
        onClick: () => setSelectedKey("2026/02/2026-02-27.sell.json"),
      },
      "Select B",
    ),
  );
}

describe("useReportsState URL sync", () => {
  let container: HTMLDivElement;
  let root: Root;
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
    navigationMock.replace.mockReset();
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  });

  function renderWithSearchParams(
    value: string,
    initialState: ReportsInitialState = INITIAL_STATE,
  ): void {
    navigationMock.setSearchParams(value);

    act(() => {
      root.render(React.createElement(Harness, { initialState }));
    });
  }

  it("keeps the server-selected key on first hydration when URL key is absent", () => {
    renderWithSearchParams("");

    expect(container.textContent).toContain(INITIAL_STATE.selectedKey ?? "");
    expect(navigationMock.replace).toHaveBeenCalledWith(
      `/reports?key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}`,
      { scroll: false },
    );
  });

  it("does not restore a stale key after the URL key is removed later", () => {
    renderWithSearchParams("");
    renderWithSearchParams(
      `key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}`,
    );

    navigationMock.replace.mockClear();

    renderWithSearchParams("");

    expect(container.textContent).toContain("none");
    expect(navigationMock.replace).not.toHaveBeenCalled();
  });

  it("clears a stale URL key when the loaded report list is empty", () => {
    renderWithSearchParams(
      `q=AAPL&key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}`,
      EMPTY_SEARCH_STATE,
    );

    expect(container.textContent).toContain("none");
    expect(navigationMock.replace).toHaveBeenCalledWith("/reports?q=AAPL", {
      scroll: false,
    });
  });

  it("keeps a prefetched deep-link key when the loaded report list is empty", () => {
    const selectedKey = "2026/01/2026-01-31.buy.json";
    renderWithSearchParams(`q=AAPL&key=${encodeURIComponent(selectedKey)}`, {
      ...EMPTY_SEARCH_STATE,
      selectedKey,
      detailKey: selectedKey,
      detail: {
        schema: "sab.report.v1",
        type: "buy",
      },
    });

    expect(container.textContent).toContain(selectedKey);
    expect(navigationMock.replace).not.toHaveBeenCalled();
  });

  it("clears previous detail while loading a different selected key", async () => {
    navigationMock.setSearchParams(
      `key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}`,
    );
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    await act(async () => {
      root.render(
        React.createElement(DetailHarness, { initialState: INITIAL_STATE }),
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain(
      "2026/02/2026-02-28.buy.json|idle|buy",
    );

    await act(async () => {
      container
        .querySelector("button")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain(
      "2026/02/2026-02-27.sell.json|loading|none",
    );
  });
});
