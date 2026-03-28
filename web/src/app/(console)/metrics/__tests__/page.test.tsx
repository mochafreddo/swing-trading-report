import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { hasValidAdminSession, loadMetricsDashboardData } = vi.hoisted(() => ({
  hasValidAdminSession: vi.fn(),
  loadMetricsDashboardData: vi.fn(),
}));

vi.mock("@/components/metrics-dashboard", () => ({
  MetricsDashboard: ({ initialState }: { initialState?: unknown }) => (
    <div data-state={initialState ? "ready" : "empty"} />
  ),
}));

vi.mock("@/lib/admin-prefetch", () => ({
  hasValidAdminSession,
}));

vi.mock("@/lib/metrics-data", () => ({
  loadMetricsDashboardData,
}));

import MetricsPage, {
  loadMetricsInitialState,
} from "@/app/(console)/metrics/page";

describe("MetricsPage", () => {
  beforeEach(() => {
    hasValidAdminSession.mockReset();
    loadMetricsDashboardData.mockReset();
  });

  it("returns a Suspense boundary immediately", () => {
    const element = MetricsPage();

    expect(element.type).toBe(Suspense);
  });

  it("does not load metrics when the admin session is invalid", async () => {
    hasValidAdminSession.mockResolvedValue(false);

    await expect(loadMetricsInitialState()).resolves.toBeUndefined();
    expect(loadMetricsDashboardData).not.toHaveBeenCalled();
  });

  it("loads metrics when the admin session is valid", async () => {
    hasValidAdminSession.mockResolvedValue(true);
    loadMetricsDashboardData.mockResolvedValue({
      buy: { panel: { title: "Scan Health" }, error: null },
      sell: { panel: null, error: "sell unavailable" },
      entry: { panel: { title: "Entry Health" }, error: null },
    });

    await expect(loadMetricsInitialState()).resolves.toEqual({
      buy: { panel: { title: "Scan Health" }, error: null },
      sell: { panel: null, error: "sell unavailable" },
      entry: { panel: { title: "Entry Health" }, error: null },
    });
  });
});
