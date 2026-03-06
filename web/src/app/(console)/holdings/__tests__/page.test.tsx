import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { hasValidAdminSession, fetchHoldingsPage } = vi.hoisted(() => ({
  hasValidAdminSession: vi.fn(),
  fetchHoldingsPage: vi.fn(),
}));

vi.mock("@/components/holdings-client", () => ({
  HoldingsClient: ({ initialState }: { initialState?: unknown }) => (
    <div data-state={initialState ? "ready" : "empty"} />
  ),
}));

vi.mock("@/components/holdings/helpers", () => ({
  HOLDINGS_PAGE_SIZE: 100,
}));

vi.mock("@/lib/admin-prefetch", () => ({
  hasValidAdminSession,
}));

vi.mock("@/lib/supabase-admin", () => ({
  fetchHoldingsPage,
}));

import HoldingsPage, {
  loadHoldingsInitialState,
} from "@/app/(console)/holdings/page";

describe("HoldingsPage", () => {
  beforeEach(() => {
    hasValidAdminSession.mockReset();
    fetchHoldingsPage.mockReset();
  });

  it("returns a Suspense boundary immediately", () => {
    const element = HoldingsPage();

    expect(element.type).toBe(Suspense);
  });

  it("does not load holdings when the admin session is invalid", async () => {
    hasValidAdminSession.mockResolvedValue(false);

    await expect(loadHoldingsInitialState()).resolves.toBeUndefined();
    expect(fetchHoldingsPage).not.toHaveBeenCalled();
  });

  it("rethrows holdings loading failures instead of swallowing them", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    fetchHoldingsPage.mockRejectedValueOnce(new Error("holdings unavailable"));

    await expect(loadHoldingsInitialState()).rejects.toThrow(
      "holdings unavailable",
    );
  });
});
