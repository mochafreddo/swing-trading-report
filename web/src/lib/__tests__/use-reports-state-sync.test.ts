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
  useSearchParams: () => navigationMock.getSearchParams(),
}));

const INITIAL_STATE: ReportsInitialState = {
  reportType: "all",
  runKind: null,
  query: "",
  appliedQuery: "",
  items: [
    {
      key: "2026/02/2026-02-28.buy.json",
      bucketId: "reports",
      type: "buy",
      reportDate: "2026-02-28",
      duplicateIndex: 0,
    },
    {
      key: "2026/02/2026-02-27.buy.json",
      bucketId: "reports",
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
  selectedBucketId: "reports",
  detailKey: "2026/02/2026-02-28.buy.json",
  detailBucketId: "reports",
  detail: {
    schema: "sab.report.v1",
    type: "buy",
  },
  showRaw: false,
  journalStatus: {
    state: "UNAVAILABLE",
    reason: "NOT_CONFIGURED",
    records: [],
  },
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
  selectedBucketId: null,
  detailKey: null,
  detailBucketId: null,
  detail: null,
};

const EMPTY_INITIAL_STATE: ReportsInitialState = {
  ...INITIAL_STATE,
  items: [],
  total: 0,
  selectedKey: null,
  selectedBucketId: null,
  detailKey: null,
  detailBucketId: null,
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

function ReportTypeHarness({
  initialState,
}: {
  initialState: ReportsInitialState;
}): React.JSX.Element {
  const { reportType, runKind, selectedKey, setReportType } =
    useReportsState(initialState);

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      "output",
      { "data-testid": "report-type" },
      `${reportType}|${runKind ?? "none"}|${selectedKey ?? "none"}`,
    ),
    React.createElement(
      "button",
      {
        type: "button",
        onClick: () => setReportType("decision-board"),
      },
      "Select Decision Board",
    ),
    React.createElement(
      "button",
      {
        type: "button",
        onClick: () => setReportType("all"),
      },
      "Select All",
    ),
  );
}

describe("useReportsState URL sync", () => {
  let container: HTMLDivElement;
  let root: Root;
  let previousActEnvironment: boolean | undefined;
  let replaceStateSpy: ReturnType<typeof vi.spyOn>;

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
    window.history.replaceState(null, "", "/reports");
    replaceStateSpy = vi.spyOn(window.history, "replaceState");
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
    setExternalSearchParams(value);

    act(() => {
      root.render(React.createElement(Harness, { initialState }));
    });
  }

  function setExternalSearchParams(value: string): void {
    const url = value ? `/reports?${value}` : "/reports";
    window.history.replaceState(null, "", url);
    navigationMock.setSearchParams(value);
    replaceStateSpy.mockClear();
  }

  it("keeps the server-selected key on first hydration when URL key is absent", () => {
    renderWithSearchParams("");

    expect(container.textContent).toContain(INITIAL_STATE.selectedKey ?? "");
    expect(replaceStateSpy).toHaveBeenCalledWith(
      null,
      "",
      `/reports?key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}&bucket=reports`,
    );
  });

  it("does not restore a stale key after the URL key is removed later", () => {
    renderWithSearchParams("");
    renderWithSearchParams(
      `key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}`,
    );

    replaceStateSpy.mockClear();

    renderWithSearchParams("");

    expect(container.textContent).toContain("none");
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });

  it("clears a stale URL key when the loaded report list is empty", () => {
    renderWithSearchParams(
      `q=AAPL&key=${encodeURIComponent(INITIAL_STATE.selectedKey ?? "")}`,
      EMPTY_SEARCH_STATE,
    );

    expect(container.textContent).toContain("none");
    expect(replaceStateSpy).toHaveBeenCalledWith(null, "", "/reports?q=AAPL");
  });

  it("keeps a prefetched deep-link key when the loaded report list is empty", () => {
    const selectedKey = "2026/01/2026-01-31.buy.json";
    renderWithSearchParams(`q=AAPL&key=${encodeURIComponent(selectedKey)}`, {
      ...EMPTY_SEARCH_STATE,
      selectedKey,
      selectedBucketId: null,
      detailKey: selectedKey,
      detailBucketId: "reports",
      detail: {
        schema: "sab.report.v1",
        type: "buy",
      },
    });

    expect(container.textContent).toContain(selectedKey);
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });

  it("clears previous detail while loading a different selected key", async () => {
    setExternalSearchParams(
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

  it("keeps a locally selected report type while the URL update is pending", async () => {
    setExternalSearchParams("");
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });

    await act(async () => {
      container
        .querySelector("button")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });

    expect(container.textContent).toContain("decision-board|ENTRY");
    expect(replaceStateSpy).toHaveBeenCalledWith(
      null,
      "",
      "/reports?type=decision-board&runKind=ENTRY",
    );

    navigationMock.setSearchParams("type=decision-board&runKind=ENTRY");
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });
    expect(container.textContent).toContain("decision-board|ENTRY");

    setExternalSearchParams("type=sell");
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });
    expect(container.textContent).toContain("sell|none");
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });

  it("honors external navigation before a local URL update completes", async () => {
    setExternalSearchParams("");
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });
    await act(async () => {
      container
        .querySelector("button")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    expect(container.textContent).toContain("decision-board|ENTRY");

    setExternalSearchParams("type=sell");
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain("sell|none");
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });

  it("synchronously replaces the latest local report type selection", async () => {
    setExternalSearchParams("");
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });

    const buttons = Array.from(container.querySelectorAll("button"));
    await act(async () => {
      buttons[0]?.click();
      await Promise.resolve();
    });
    expect(window.location.search).toBe("?type=decision-board&runKind=ENTRY");

    await act(async () => {
      buttons[1]?.click();
      await Promise.resolve();
    });
    expect(container.textContent).toContain("all|none");
    expect(window.location.search).toBe("");
  });

  it("ignores stale hook search params after an external navigation", async () => {
    setExternalSearchParams("");
    vi.spyOn(globalThis, "fetch").mockImplementation(
      () => new Promise<Response>(() => undefined),
    );

    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });
    await act(async () => {
      container.querySelector("button")?.click();
      await Promise.resolve();
    });

    navigationMock.setSearchParams("type=decision-board&runKind=ENTRY");
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });

    setExternalSearchParams("type=sell");
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });
    expect(container.textContent).toContain("sell|none");

    navigationMock.setSearchParams("type=decision-board&runKind=ENTRY");
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: EMPTY_INITIAL_STATE,
        }),
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain("sell|none");
    expect(window.location.search).toBe("?type=sell");
  });

  it("does not let an older list response overwrite an external navigation", async () => {
    const query = "external-list-race";
    const raceInitialState: ReportsInitialState = {
      ...EMPTY_INITIAL_STATE,
      query,
      appliedQuery: query,
    };
    setExternalSearchParams(`q=${query}`);

    let resolveListResponse: ((response: Response) => void) | undefined;
    const listResponse = new Promise<Response>((resolve) => {
      resolveListResponse = resolve;
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost:55301");
      if (url.pathname === "/api/reports") {
        return listResponse;
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            state: "UNAVAILABLE",
            reason: "NOT_CONFIGURED",
            records: [],
          }),
          { status: 200 },
        ),
      );
    });

    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: raceInitialState,
        }),
      );
      await Promise.resolve();
    });
    await act(async () => {
      container.querySelector("button")?.click();
      await Promise.resolve();
    });

    const decisionBoardQuery = `type=decision-board&runKind=ENTRY&q=${query}`;
    navigationMock.setSearchParams(decisionBoardQuery);
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: raceInitialState,
        }),
      );
      await Promise.resolve();
    });

    const sellKey = "2026/08/2026-08-16.sell.json";
    const sellQuery =
      `type=sell&q=${query}&key=${encodeURIComponent(sellKey)}` +
      "&bucket=reports";
    window.history.replaceState(null, "", `/reports?${sellQuery}`);
    replaceStateSpy.mockClear();
    await act(async () => {
      resolveListResponse?.(
        new Response(
          JSON.stringify({
            items: [],
            total: 0,
            searched: 0,
            truncated: false,
            searchWindow: 100,
            warnings: [],
          }),
          { status: 200 },
        ),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(window.location.search).toBe(`?${sellQuery}`);
    expect(replaceStateSpy).not.toHaveBeenCalled();

    navigationMock.setSearchParams(sellQuery);
    await act(async () => {
      root.render(
        React.createElement(ReportTypeHarness, {
          initialState: raceInitialState,
        }),
      );
      await Promise.resolve();
    });
    expect(container.textContent).toContain("sell|none");
    expect(container.textContent).toContain(sellKey);
    expect(window.location.search).toBe(`?${sellQuery}`);
  });
});
