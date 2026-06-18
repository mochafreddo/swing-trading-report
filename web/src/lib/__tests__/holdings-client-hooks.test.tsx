// @vitest-environment jsdom

import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  addBuyToHoldingAction,
  type AddBuyToHoldingActionInput,
  deleteHoldingAction,
  saveHoldingAction,
  type HoldingsActionResult,
} from "@/app/actions/holdings";
import { HoldingsClient } from "@/components/holdings-client";
import { useAddBuyFlow } from "@/components/holdings/use-add-buy-flow";
import { useHoldingsImport } from "@/components/holdings/use-holdings-import";
import { useRecentCandidates } from "@/components/holdings/use-recent-candidates";
import { useTickerLookup } from "@/components/holdings/use-ticker-lookup";
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";
import type {
  HoldingRecord,
  HoldingsYamlImportResponse,
  HoldingsYamlImportSummary,
} from "@/lib/types";

vi.mock("@/app/actions/holdings", () => ({
  addBuyToHoldingAction: vi.fn(),
  deleteHoldingAction: vi.fn(),
  saveHoldingAction: vi.fn(),
}));

const HOLDING: HoldingRecord = {
  ticker: "AAPL.NAS",
  quantity: 10,
  entry_price: 100,
  entry_currency: "USD",
  entry_date: "2026-03-01",
  strategy: null,
  entry_pattern: null,
  notes: null,
  tags: [],
  stop_override: null,
  target_override: null,
  created_at: "2026-03-01T00:00:00Z",
  updated_at: "2026-03-02T00:00:00Z",
};

const IMPORT_SUMMARY: HoldingsYamlImportSummary = {
  incomingCount: 1,
  createCount: 1,
  updateCount: 0,
  deleteCount: 0,
  unchangedCount: 0,
  createTickers: ["AAPL.NAS"],
  updateTickers: [],
  deleteTickers: [],
};

function renderHook<T>(useHook: () => T) {
  let value: T | undefined;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);

  function Harness() {
    value = useHook();
    return null;
  }

  act(() => {
    root.render(React.createElement(Harness));
  });

  return {
    get current(): T {
      if (value === undefined) {
        throw new Error("hook value was not initialized");
      }
      return value;
    },
    unmount() {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

function jsonResponse(payload: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(payload), {
    status: init?.status ?? 200,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
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

function setControlValue(
  control: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement,
  value: string,
  eventName: "input" | "change" = "input",
) {
  const prototype =
    control instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : control instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
  const valueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  valueSetter?.call(control, value);
  control.dispatchEvent(new Event(eventName, { bubbles: true }));
}

describe("holdings client hooks", () => {
  let previousActEnvironment: boolean | undefined;

  beforeEach(() => {
    previousActEnvironment = (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT;
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
  });

  it("debounces ticker lookup and selects a result into the form flow", async () => {
    vi.useFakeTimers();
    const onSelectTicker = vi.fn();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        results: [{ ticker: " cost.nas ", name: " Costco " }],
      }),
    );
    const hook = renderHook(() =>
      useTickerLookup({
        onSelectTicker,
        fetcher,
      }),
    );

    act(() => {
      hook.current.setQuery(" cost ");
    });
    await act(async () => {
      vi.advanceTimersByTime(219);
      await Promise.resolve();
    });
    expect(fetcher).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(String(fetcher.mock.calls[0]?.[0])).toBe(
      "/api/tickers/search?q=cost&limit=8",
    );
    expect(hook.current.results).toEqual([
      { ticker: "COST.NAS", name: "Costco" },
    ]);

    act(() => {
      hook.current.selectTicker("COST.NAS");
    });
    expect(onSelectTicker).toHaveBeenCalledWith("COST.NAS");
    expect(hook.current.query).toBe("");
    expect(hook.current.results).toEqual([]);

    hook.unmount();
  });

  it("loads recent candidates on mount", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
        candidates: [
          {
            ticker: "aapl.nas",
            name: "Apple",
            pattern: "swing_high_breakout",
          },
        ],
      }),
    );
    const hook = renderHook(() => useRecentCandidates({ fetcher }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/tickers/recent-candidates?limitReports=10&limitCandidates=20",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(hook.current.candidates).toEqual([
      { ticker: "AAPL.NAS", name: "Apple", pattern: "swing_high_breakout" },
    ]);
    expect(hook.current.reportKey).toBe("2026/03/report.buy.json");
    expect(hook.current.reportDate).toBe("2026-03-02");
    expect(hook.current.error).toBeNull();

    hook.unmount();
  });

  it("normalizes omitted and invalid recent candidate patterns", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      jsonResponse({
        report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
        candidates: [
          { ticker: "aapl.nas", name: "Apple" },
          { ticker: "msft.nas", name: "Microsoft", pattern: "not_a_breakout" },
        ],
      }),
    );
    const hook = renderHook(() => useRecentCandidates({ fetcher }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(hook.current.candidates).toEqual([
      { ticker: "AAPL.NAS", name: "Apple", pattern: null },
      { ticker: "MSFT.NAS", name: "Microsoft", pattern: null },
    ]);

    hook.unmount();
  });

  it("guards holdings import apply until dry-run and refreshes after apply", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    const cancelEdit = vi.fn();
    const cancelAddBuy = vi.fn();
    const confirm = vi.fn(() => true);
    const requestImport = vi
      .fn<
        (
          document: string,
          apply: boolean,
        ) => Promise<HoldingsYamlImportResponse>
      >()
      .mockImplementation(async (_document, apply) => ({
        mode: apply ? "apply" : "dry-run",
        summary: IMPORT_SUMMARY,
      }));
    const hook = renderHook(() =>
      useHoldingsImport({
        refresh,
        cancelEdit,
        cancelAddBuy,
        requestImport,
        confirm,
        requestExport: vi.fn(),
        triggerDownload: vi.fn(),
      }),
    );

    await act(async () => {
      await hook.current.apply();
    });
    expect(hook.current.error).toBe(
      "Import할 holdings.yaml 파일을 먼저 선택하세요.",
    );
    expect(requestImport).not.toHaveBeenCalled();

    await act(async () => {
      await hook.current.handleFileSelected(
        new File(["holdings: []"], "holdings.yaml", { type: "text/yaml" }),
      );
    });
    expect(hook.current.canDryRun).toBe(true);

    await act(async () => {
      await hook.current.dryRun();
    });
    expect(requestImport).toHaveBeenLastCalledWith("holdings: []", false);
    expect(hook.current.canApply).toBe(true);

    await act(async () => {
      await hook.current.apply();
    });
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(requestImport).toHaveBeenLastCalledWith("holdings: []", true);
    expect(cancelEdit).toHaveBeenCalledTimes(1);
    expect(cancelAddBuy).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(hook.current.fileName).toBeNull();
    expect(hook.current.success).toBe(
      "적용 완료: create 1, update 0, delete 0",
    );

    hook.unmount();
  });

  it("rotates add-buy idempotency key after payload mismatch", async () => {
    const randomUUID = vi
      .spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000003")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000004")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000005");
    const refresh = vi.fn().mockResolvedValue(undefined);
    const setError = vi.fn();
    const addBuyToHolding = vi
      .fn<
        (input: AddBuyToHoldingActionInput) => Promise<HoldingsActionResult>
      >()
      .mockResolvedValueOnce({
        ok: false,
        error: "idempotency_key payload mismatch",
        code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
      })
      .mockResolvedValueOnce({ ok: true });
    const hook = renderHook(() =>
      useAddBuyFlow({
        items: [HOLDING],
        refresh,
        setError,
        addBuyToHolding,
      }),
    );

    act(() => {
      hook.current.begin(HOLDING);
      hook.current.updateField("buy_quantity", "2");
      hook.current.updateField("buy_price", "120");
    });

    await act(async () => {
      await hook.current.submit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>);
    });
    expect(hook.current.error).toContain(
      "요청 충돌이 감지되어 새 Idempotency-Key를 자동 발급했습니다.",
    );

    await act(async () => {
      await hook.current.submit({
        preventDefault: vi.fn(),
      } as unknown as React.FormEvent<HTMLFormElement>);
    });

    expect(addBuyToHolding).toHaveBeenCalledTimes(2);
    const firstKey = addBuyToHolding.mock.calls[0]?.[0].idempotencyKey;
    const secondKey = addBuyToHolding.mock.calls[1]?.[0].idempotencyKey;
    expect(firstKey).not.toBe(secondKey);
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(hook.current.target).toBeNull();
    expect(randomUUID).toHaveBeenCalled();

    hook.unmount();
  });
});

describe("HoldingsClient composition", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    (
      globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
    ).IS_REACT_ACT_ENVIRONMENT = true;
    vi.mocked(saveHoldingAction).mockResolvedValue({ ok: true });
    vi.mocked(deleteHoldingAction).mockResolvedValue({ ok: true });
    vi.mocked(addBuyToHoldingAction).mockResolvedValue({ ok: true });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        report: null,
        candidates: [],
      }),
    );
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it("wires table Add Buy selection into the extracted add-buy panel", async () => {
    await act(async () => {
      root.render(
        React.createElement(HoldingsClient, {
          initialState: {
            items: [HOLDING],
            hasMore: false,
            nextCursor: null,
          },
        }),
      );
      await Promise.resolve();
    });

    act(() => {
      findButton(container, "Add Buy").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });

    expect(container.textContent).toContain("Ticker: AAPL.NAS");
    expect(
      container.querySelector<HTMLInputElement>('input[name="buy_quantity"]'),
    ).not.toBeNull();
  });

  it("populates entry pattern when selecting a patterned recent candidate", async () => {
    vi.mocked(globalThis.fetch as typeof fetch).mockResolvedValueOnce(
      jsonResponse({
        report: { key: "2026/03/report.buy.json", reportDate: "2026-03-02" },
        candidates: [
          {
            ticker: "msft.nas",
            name: "Microsoft",
            pattern: "swing_high_breakout",
          },
        ],
      }),
    );

    await act(async () => {
      root.render(
        React.createElement(HoldingsClient, {
          initialState: { items: [], hasMore: false, nextCursor: null },
        }),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Pattern: swing_high_breakout");

    act(() => {
      findButton(container, "MSFT.NAS").dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });

    expect(
      container.querySelector<HTMLInputElement>('input[name="ticker"]')?.value,
    ).toBe("MSFT.NAS");
    expect(
      container.querySelector<HTMLSelectElement>('select[name="entryPattern"]')
        ?.value,
    ).toBe("swing_high_breakout");
  });

  it("submits entry pattern from the holdings form", async () => {
    await act(async () => {
      root.render(
        React.createElement(HoldingsClient, {
          initialState: { items: [], hasMore: false, nextCursor: null },
        }),
      );
      await Promise.resolve();
    });

    const ticker = container.querySelector<HTMLInputElement>(
      'input[name="ticker"]',
    );
    const quantity = container.querySelector<HTMLInputElement>(
      'input[name="quantity"]',
    );
    const entryPrice = container.querySelector<HTMLInputElement>(
      'input[name="entryPrice"]',
    );
    const entryPattern = container.querySelector<HTMLSelectElement>(
      'select[name="entryPattern"]',
    );
    expect(ticker).not.toBeNull();
    expect(quantity).not.toBeNull();
    expect(entryPrice).not.toBeNull();
    expect(entryPattern).not.toBeNull();

    act(() => {
      setControlValue(ticker!, "AAPL.NAS");
      setControlValue(quantity!, "1");
      setControlValue(entryPrice!, "100");
      setControlValue(entryPattern!, "swing_high_breakout", "change");
    });

    await act(async () => {
      container
        .querySelector("form")
        ?.dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        );
      await Promise.resolve();
    });

    expect(saveHoldingAction).toHaveBeenCalledWith({
      editingTicker: null,
      payload: expect.objectContaining({
        ticker: "AAPL.NAS",
        entry_pattern: "swing_high_breakout",
      }),
    });
  });

  it("renders entry pattern metadata in the holdings table", async () => {
    await act(async () => {
      root.render(
        React.createElement(HoldingsClient, {
          initialState: {
            items: [{ ...HOLDING, entry_pattern: "swing_high_breakout" }],
            hasMore: false,
            nextCursor: null,
          },
        }),
      );
      await Promise.resolve();
    });

    expect(container.textContent).toContain(
      "Entry Pattern: swing_high_breakout",
    );
  });
});
