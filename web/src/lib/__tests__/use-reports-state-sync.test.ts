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
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  });

  function renderWithSearchParams(value: string): void {
    navigationMock.setSearchParams(value);

    act(() => {
      root.render(
        React.createElement(Harness, { initialState: INITIAL_STATE }),
      );
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
});
