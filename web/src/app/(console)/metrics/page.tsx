import { Suspense } from "react";

import { MetricsDashboard } from "@/components/metrics-dashboard";
import type { MetricsDashboardData } from "@/lib/metrics-data";
import { loadMetricsDashboardData } from "@/lib/metrics-data";
import { hasValidAdminSession } from "@/lib/admin-prefetch";

export async function loadMetricsInitialState(): Promise<
  MetricsDashboardData | undefined
> {
  if (!(await hasValidAdminSession())) {
    return undefined;
  }

  return loadMetricsDashboardData();
}

function MetricsPageFallback() {
  return (
    <section className="panel">
      <p className="subtle">Loading metrics...</p>
    </section>
  );
}

async function MetricsPageContent() {
  const initialState = await loadMetricsInitialState();
  return <MetricsDashboard initialState={initialState} />;
}

export default function MetricsPage() {
  return (
    <Suspense fallback={<MetricsPageFallback />}>
      <MetricsPageContent />
    </Suspense>
  );
}
