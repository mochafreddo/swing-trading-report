// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

import {
  TodayDecisionBoard,
  type TodayLaneSnapshot,
} from "@/components/today-decision-board";

const fixturePath = resolve(
  process.cwd(),
  "../tests/fixtures/portfolio_mandate/portfolio-mandate-a2-unclassified-preview.synthetic.json",
);
const fixtureDocument = readFileSync(fixturePath, "utf8");
const privateV1FixtureDocument = readFileSync(
  resolve(
    process.cwd(),
    "../tests/fixtures/portfolio_mandate/portfolio-mandate-private-v1-preview.synthetic.json",
  ),
  "utf8",
);

function fileWithText(document: string): File {
  const file = new File([document], "synthetic-unclassified.json", {
    type: "application/json",
  });
  Object.defineProperty(file, "text", {
    configurable: true,
    value: vi.fn().mockResolvedValue(document),
  });
  return file;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function renderBoard() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  const lanes: TodayLaneSnapshot[] = [
    { runKind: "ENTRY", state: "MISSING" },
    { runKind: "HOLDING", state: "MISSING" },
  ];

  act(() => {
    root.render(
      <TodayDecisionBoard
        lanes={lanes}
        journalStatus={{ state: "AVAILABLE", records: [] }}
      />,
    );
  });

  const input = container.querySelector(
    "#unclassified-preview-file",
  ) as HTMLInputElement;

  async function chooseFile(file: File) {
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [file],
    });
    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  async function choose(documentText: string) {
    await chooseFile(fileWithText(documentText));
  }

  return {
    container,
    input,
    choose,
    chooseFile,
    unmount() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("UnclassifiedQueuePreview", () => {
  let previousActEnvironment: boolean | undefined;
  let fetchSpy: ReturnType<typeof vi.fn>;
  let storageSetItemSpy: ReturnType<typeof vi.spyOn>;
  let indexedDbOpenSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    previousActEnvironment = (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT;
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;
    fetchSpy = vi.fn();
    indexedDbOpenSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    vi.stubGlobal("indexedDB", { open: indexedDbOpenSpy });
    storageSetItemSpy = vi.spyOn(Storage.prototype, "setItem");
  });

  afterEach(() => {
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
    vi.unstubAllGlobals();
    document.body.replaceChildren();
  });

  it("renders all five synthetic rows as local no-advice drafts without changing actionCount", async () => {
    const board = renderBoard();
    const fileLabel = board.container.querySelector(
      'label[for="unclassified-preview-file"]',
    );

    expect(fileLabel?.textContent).toBe("Unclassified queue JSON");
    expect(board.input.accept).toBe("application/json,.json");
    expect(
      Array.from(board.container.querySelectorAll("button"), (button) =>
        button.textContent?.trim(),
      ),
    ).toEqual(["Clear local preview"]);
    await board.choose(fixtureDocument);

    expect(
      board.container.querySelector(
        '[aria-labelledby="today-board-title"] strong',
      )?.textContent,
    ).toBe("0");
    expect(
      board.container.querySelectorAll(
        '[aria-label="Unclassified local preview rows"] article',
      ),
    ).toHaveLength(5);
    expect(board.container.textContent).toContain(
      "Top-5 subset of a 12-holding snapshot",
    );
    expect(board.container.textContent).toContain("2026-08-31T09:00:00+09:00");
    expect(board.container.textContent).toContain(
      "not a current, freshness-proven, or complete portfolio view",
    );
    expect(board.container.textContent).toContain("UNCLASSIFIED · NO ADVICE");
    expect(board.container.textContent).toContain(
      "UNAPPROVED DRAFT · LONG_TERM",
    );
    expect(board.container.textContent).toContain(
      "Confirm the unapproved LONG_TERM horizon draft",
    );
    expect(board.container.textContent).toContain(
      "Provide and confirm the thesis",
    );
    expect(board.container.textContent).toContain(
      "Confirm the recalled invalidation conditions",
    );
    const localPreview = board.container.querySelector(
      '[aria-labelledby="unclassified-preview-title"]',
    );
    expect(localPreview?.textContent).not.toMatch(
      /(?:^|\s)(BUY|HOLD|SELL|AVOID|NO_ACTION)(?:\s|$)/u,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(storageSetItemSpy).not.toHaveBeenCalled();
    expect(indexedDbOpenSpy).not.toHaveBeenCalled();

    board.unmount();
  });

  it("renders an explicitly selected eight-holding private v1 overlay without activating advice", async () => {
    const board = renderBoard();

    await board.choose(privateV1FixtureDocument);

    expect(
      board.container.querySelector(
        '[aria-labelledby="today-board-title"] strong',
      )?.textContent,
    ).toBe("0");
    expect(
      board.container.querySelectorAll(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveLength(8);
    expect(board.container.textContent).toContain("5 CORE · 3 SATELLITE");
    expect(board.container.textContent).toContain(
      "PRIVATE DRAFT · NO ADVICE · NOT ACTIVE",
    );
    expect(board.container.textContent).toContain(
      "Synthetic durable-demand thesis for parser and display verification.",
    );
    expect(board.container.textContent).toContain("ALL · 2 conditions");
    expect(board.container.textContent).toContain("WARNING");
    expect(board.container.textContent).toContain("FROZEN_CONCENTRATION");
    expect(board.container.textContent).toContain(
      "ALFA.NAS → BRAV.NYS → CHAR.NAS",
    );
    expect(board.container.textContent).toContain(
      "Synthetic quarterly filing reference",
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(storageSetItemSpy).not.toHaveBeenCalled();
    expect(indexedDbOpenSpy).not.toHaveBeenCalled();

    board.unmount();
  });

  it("rejects invalid JSON atomically and removes a prior preview", async () => {
    const board = renderBoard();
    await board.choose(fixtureDocument);
    expect(board.container.textContent).toContain("SYNTH1.NAS");

    await board.choose('{"schema_version":');

    expect(board.container.textContent).toContain("Local preview rejected");
    expect(board.container.textContent).toContain(
      "Nothing was loaded or uploaded",
    );
    expect(board.container.textContent).not.toContain("SYNTH1.NAS");
    expect(
      board.container.querySelector(
        '[aria-label="Unclassified local preview rows"]',
      ),
    ).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();

    board.unmount();
  });

  it("rejects a strict-contract private field without partial rows", async () => {
    const privateFieldInput = JSON.parse(fixtureDocument) as Record<
      string,
      unknown
    >;
    const holdings = privateFieldInput.holdings as Array<
      Record<string, unknown>
    >;
    holdings[0].account_number = "synthetic-rejected-field";
    const board = renderBoard();

    await board.choose(JSON.stringify(privateFieldInput));

    expect(board.container.textContent).toContain("Local preview rejected");
    expect(board.container.textContent).not.toContain("SYNTH1.NAS");
    expect(fetchSpy).not.toHaveBeenCalled();

    board.unmount();
  });

  it("atomically removes a prior private preview and never echoes rejected input", async () => {
    const invalid = JSON.parse(privateV1FixtureDocument) as Record<
      string,
      unknown
    >;
    const invalidHoldings = invalid.holdings as Array<Record<string, unknown>>;
    const rawPrivateSentinel = "PRIVATE-RAW-SENTINEL-MUST-NOT-RENDER";
    invalidHoldings[0].account_identifier = rawPrivateSentinel;
    const board = renderBoard();
    await board.choose(privateV1FixtureDocument);
    expect(board.container.textContent).toContain("ALFA.NAS");

    await board.choose(JSON.stringify(invalid));

    expect(board.container.textContent).toContain("Local preview rejected");
    expect(board.container.textContent).not.toContain("ALFA.NAS");
    expect(board.container.textContent).not.toContain(rawPrivateSentinel);
    expect(
      board.container.querySelector(
        '[aria-label="Private portfolio mandate preview rows"]',
      ),
    ).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(storageSetItemSpy).not.toHaveBeenCalled();
    expect(indexedDbOpenSpy).not.toHaveBeenCalled();

    board.unmount();
  });

  it("clears the in-memory preview and file control with reset semantics only", async () => {
    const board = renderBoard();
    await board.choose(fixtureDocument);
    const clearButton = Array.from(
      board.container.querySelectorAll("button"),
    ).find((button) => button.textContent === "Clear local preview");

    await act(async () => {
      clearButton?.click();
      await Promise.resolve();
    });

    expect(board.container.textContent).toContain(
      "Local preview cleared from browser memory",
    );
    expect(board.container.textContent).not.toContain("SYNTH1.NAS");
    expect(board.input.value).toBe("");
    expect(fetchSpy).not.toHaveBeenCalled();

    board.unmount();
  });

  it("keeps a cleared preview empty when an earlier file read finishes later", async () => {
    const board = renderBoard();
    const pendingText = deferred<string>();
    const pendingFile = fileWithText(fixtureDocument);
    const textSpy = vi.fn().mockReturnValue(pendingText.promise);
    Object.defineProperty(pendingFile, "text", {
      configurable: true,
      value: textSpy,
    });

    await board.chooseFile(pendingFile);
    const clearButton = Array.from(
      board.container.querySelectorAll("button"),
    ).find((button) => button.textContent === "Clear local preview");
    await act(async () => {
      clearButton?.click();
      pendingText.resolve(fixtureDocument);
      await pendingText.promise;
      await Promise.resolve();
    });

    expect(textSpy).toHaveBeenCalledOnce();
    expect(board.container.textContent).toContain(
      "Local preview cleared from browser memory",
    );
    expect(board.container.textContent).not.toContain("SYNTH1.NAS");

    board.unmount();
  });

  it("keeps the newest selection when an earlier file read finishes later", async () => {
    const board = renderBoard();
    const firstDocument = fixtureDocument.replaceAll("SYNTH", "OLDER");
    const pendingText = deferred<string>();
    const pendingFile = fileWithText(firstDocument);
    Object.defineProperty(pendingFile, "text", {
      configurable: true,
      value: vi.fn().mockReturnValue(pendingText.promise),
    });

    await board.chooseFile(pendingFile);
    await board.choose(fixtureDocument);
    expect(board.container.textContent).toContain("SYNTH1.NAS");

    await act(async () => {
      pendingText.resolve(firstDocument);
      await pendingText.promise;
      await Promise.resolve();
    });

    expect(board.container.textContent).toContain("SYNTH1.NAS");
    expect(board.container.textContent).not.toContain("OLDER1.NAS");

    board.unmount();
  });

  it("allows the same file to be selected again after the file control is clicked", async () => {
    const board = renderBoard();
    const file = fileWithText(privateV1FixtureDocument);

    await board.chooseFile(file);
    await act(async () => {
      board.input.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
    });
    await board.chooseFile(file);

    expect(file.text).toHaveBeenCalledTimes(2);
    expect(
      board.container.querySelectorAll(
        '[aria-label="Private portfolio mandate preview rows"] article',
      ),
    ).toHaveLength(8);

    board.unmount();
  });

  it("rejects an oversized file before reading it", async () => {
    const board = renderBoard();
    const oversizedFile = fileWithText(fixtureDocument);
    Object.defineProperty(oversizedFile, "size", {
      configurable: true,
      value: 1_000_001,
    });

    await board.chooseFile(oversizedFile);

    expect(oversizedFile.text).not.toHaveBeenCalled();
    expect(board.container.textContent).toContain("file is too large");
    expect(board.container.textContent).not.toContain("SYNTH1.NAS");
    expect(fetchSpy).not.toHaveBeenCalled();

    board.unmount();
  });
});
