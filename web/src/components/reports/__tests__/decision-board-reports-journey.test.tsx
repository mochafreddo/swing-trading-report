// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReportsClient } from "@/components/reports-client";
import type { ReportsInitialState } from "@/components/reports/types";

const navigationMock = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/reports",
  useSearchParams: () => navigationMock.searchParams,
}));

const ENTRY_FIXTURE_PATH = resolve(
  process.cwd(),
  "../tests/fixtures/decision_board/published-entry.json",
);
const HOLDING_FIXTURE_PATH = resolve(
  process.cwd(),
  "../tests/fixtures/decision_board/published-holding.json",
);

const fixture = (name: "published-entry.json" | "published-holding.json") =>
  JSON.parse(
    readFileSync(
      name === "published-entry.json"
        ? ENTRY_FIXTURE_PATH
        : HOLDING_FIXTURE_PATH,
      "utf8",
    ),
  ) as Record<string, unknown>;

const ENTRY_DIGEST = "e".repeat(64);
const HOLDING_DIGEST = "f".repeat(64);
const ENTRY_KEY =
  "2026/08/2026-08-06.decision-board.entry." +
  `entry-2026-08-06T010000Z.${ENTRY_DIGEST}.json`;
const HOLDING_KEY =
  "2026/08/2026-08-06.decision-board.holding." +
  `holding-2026-08-06T020000Z.${HOLDING_DIGEST}.json`;

const INITIAL_STATE: ReportsInitialState = {
  reportType: "all",
  runKind: null,
  query: "",
  appliedQuery: "",
  items: [],
  total: 0,
  searched: 0,
  truncated: false,
  searchWindow: 100,
  warnings: [],
  selectedKey: null,
  selectedBucketId: null,
  detail: null,
  detailKey: null,
  detailBucketId: null,
  showRaw: false,
  journalStatus: {
    state: "UNAVAILABLE",
    reason: "NOT_CONFIGURED",
    records: [],
  },
};

function response(payload: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
}

async function waitForText(
  container: HTMLElement,
  text: string,
): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (container.textContent?.includes(text)) {
      return;
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
  throw new Error(`Timed out waiting for ${text}: ${container.textContent}`);
}

describe("fixture-only Decision Board reports journey", () => {
  let container: HTMLDivElement;
  let root: Root;
  let requestedUrls: string[];

  beforeEach(() => {
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    window.history.replaceState(null, "", "/reports");
    navigationMock.searchParams = new URLSearchParams();
    requestedUrls = [];
    const originalReplaceState = window.history.replaceState.bind(
      window.history,
    );
    vi.spyOn(window.history, "replaceState").mockImplementation(
      (data, unused, value) => {
        originalReplaceState(data, unused, value);
        navigationMock.searchParams = new URL(
          String(value),
          "http://localhost:55300",
        ).searchParams;
      },
    );

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost:55300");
      requestedUrls.push(url.toString());
      if (url.pathname === "/api/reports/decision-board-journal") {
        return response({
          state: "AVAILABLE",
          records: [
            {
              schema_version: "decision-board.v0",
              run_id: "holding-slot-stale",
              run_kind: "HOLDING",
              status: "STALE_INCOMPLETE",
              expected_at: "2026-08-11T01:00:00Z",
              started_at: "2026-08-11T01:00:01Z",
              terminal_at: "2026-08-11T02:00:00Z",
              grace_seconds: 60,
              stale_seconds: 300,
              issues: [
                {
                  code: "STALE_INCOMPLETE",
                  message:
                    "Started run did not reach a terminal state before its TTL.",
                },
              ],
              report_file: null,
            },
          ],
        });
      }
      if (url.pathname === "/api/reports") {
        const holding = url.searchParams.get("runKind") === "HOLDING";
        const key = holding ? HOLDING_KEY : ENTRY_KEY;
        return response({
          items: [
            {
              key,
              bucketId: "reports",
              type: "decision-board",
              reportDate: "2026-08-06",
              duplicateIndex: 0,
              runKind: holding ? "HOLDING" : "ENTRY",
              runId: holding
                ? "holding-2026-08-06T020000Z"
                : "entry-2026-08-06T010000Z",
            },
          ],
          total: 1,
          searched: 0,
          searchWindow: 100,
          truncated: false,
          warnings: [],
        });
      }
      if (url.pathname === "/api/reports/detail") {
        const key = url.searchParams.get("key");
        return response({
          key,
          bucketId: "reports",
          report:
            key === HOLDING_KEY
              ? fixture("published-holding.json")
              : fixture("published-entry.json"),
        });
      }
      throw new Error(`Unexpected fixture request: ${url.pathname}`);
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean })
      .IS_REACT_ACT_ENVIRONMENT;
  });

  it("chooses ENTRY, opens detail, switches to HOLDING SELL, and shows stale status", async () => {
    await act(async () => {
      root.render(<ReportsClient initialState={INITIAL_STATE} />);
    });

    const reportType = container.querySelector<HTMLSelectElement>(
      'select[name="reportType"]',
    );
    expect(reportType).not.toBeNull();
    await act(async () => {
      if (reportType) {
        reportType.value = "decision-board";
        reportType.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await waitForText(container, "entry-2026-08-06T010000Z");
    const entryRow = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("entry-2026-08-06T010000Z"),
    );
    await act(async () => entryRow?.click());
    await waitForText(container, "AUR.NAS");
    expect(container.textContent).toContain("BUY");
    await act(async () => {
      root.render(<ReportsClient initialState={INITIAL_STATE} />);
      await Promise.resolve();
    });

    const runKind = container.querySelector<HTMLSelectElement>(
      'select[name="runKind"]',
    );
    expect(runKind?.value).toBe("ENTRY");
    navigationMock.searchParams.set("runKind", "HOLDING");
    navigationMock.searchParams.set("key", HOLDING_KEY);
    navigationMock.searchParams.set("bucket", "reports");
    await act(async () => {
      if (runKind) {
        runKind.value = "HOLDING";
        runKind.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    expect(runKind?.value).toBe("HOLDING");

    try {
      await waitForText(container, "ELM.NYS");
    } catch (error) {
      throw new Error(
        `${String(error)} requests=${requestedUrls.join("|")} lane=${runKind?.value} url=${navigationMock.searchParams.toString()}`,
      );
    }
    expect(container.textContent).toContain("SELL");
    expect(container.textContent).toContain("STALE_INCOMPLETE");
    expect(container.textContent).toContain("Local shadow run warning");
    expect(container.textContent).not.toMatch(
      /place order|notify|notification/i,
    );
    expect(container.querySelector('[data-order-action="true"]')).toBeNull();
    expect(navigationMock.searchParams.get("runKind")).toBe("HOLDING");
  });

  it("does not show ENTRY rows when the HOLDING lane request fails", async () => {
    const entryInitialState: ReportsInitialState = {
      ...INITIAL_STATE,
      reportType: "decision-board",
      runKind: "ENTRY",
      query: "failure-case",
      appliedQuery: "failure-case",
      items: [
        {
          key: ENTRY_KEY,
          bucketId: "reports",
          type: "decision-board",
          reportDate: "2026-08-06",
          duplicateIndex: 0,
          runKind: "ENTRY",
          runId: "entry-2026-08-06T010000Z",
        },
      ],
      total: 1,
      selectedKey: ENTRY_KEY,
      selectedBucketId: "reports",
      detail: fixture("published-entry.json"),
      detailKey: ENTRY_KEY,
      detailBucketId: "reports",
    };
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = new URL(String(input), "http://localhost:55300");
      if (url.pathname === "/api/reports") {
        return Promise.resolve(
          new Response(JSON.stringify({ error: "HOLDING unavailable" }), {
            status: 503,
            headers: { "content-type": "application/json" },
          }),
        );
      }
      return response({
        state: "UNAVAILABLE",
        reason: "NOT_CONFIGURED",
        records: [],
      });
    });
    navigationMock.searchParams = new URLSearchParams({
      type: "decision-board",
      runKind: "ENTRY",
      q: "failure-case",
      key: ENTRY_KEY,
      bucket: "reports",
    });

    await act(async () => {
      root.render(<ReportsClient initialState={entryInitialState} />);
    });
    expect(container.textContent).toContain("entry-2026-08-06T010000Z");

    const runKind = container.querySelector<HTMLSelectElement>(
      'select[name="runKind"]',
    );
    navigationMock.searchParams.set("runKind", "HOLDING");
    navigationMock.searchParams.delete("key");
    navigationMock.searchParams.delete("bucket");
    await act(async () => {
      if (runKind) {
        runKind.value = "HOLDING";
        runKind.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    await waitForText(container, "HOLDING unavailable");

    expect(container.textContent).not.toContain("entry-2026-08-06T010000Z");
    expect(container.textContent).not.toContain("AUR.NAS");
  });
});
