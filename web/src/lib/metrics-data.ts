import "server-only";

import { toErrorMessage } from "@/lib/error-utils";
import {
  fetchReportIndexPage,
  type ReportIndexRow,
} from "@/lib/supabase-admin";

const METRICS_LOOKBACK_LIMIT = 30;

type MetricsPanelType = "buy" | "sell" | "entry";
type MetricPresentation = "count" | "ratio";

interface MetricsMetricDefinition {
  key: string;
  label: string;
  presentation: MetricPresentation;
}

export interface MetricSeriesPoint {
  key: string;
  label: string;
  value: number | null;
}

export interface MetricsPanelMetric {
  key: string;
  label: string;
  presentation: MetricPresentation;
  latest: number | null;
  average: number | null;
  series: MetricSeriesPoint[];
}

export interface MetricsPanelData {
  type: MetricsPanelType;
  title: string;
  description: string;
  reportCount: number;
  latestReportKey: string | null;
  latestGeneratedAt: string | null;
  latestReportHref: string;
  browseHref: string;
  metrics: MetricsPanelMetric[];
}

export interface MetricsPanelState {
  panel: MetricsPanelData | null;
  error: string | null;
}

export interface MetricsDashboardData {
  buy: MetricsPanelState;
  sell: MetricsPanelState;
  entry: MetricsPanelState;
}

const METRIC_DEFINITIONS: Record<
  MetricsPanelType,
  readonly MetricsMetricDefinition[]
> = {
  buy: [
    { key: "candidate_count", label: "Candidates", presentation: "count" },
    { key: "data_coverage_ratio", label: "Coverage", presentation: "ratio" },
    {
      key: "provider_fallback_ratio",
      label: "Fallback",
      presentation: "ratio",
    },
    {
      key: "rs_benchmark_unavailable_ratio",
      label: "RS Benchmark Unavailable",
      presentation: "ratio",
    },
    {
      key: "system_issue_count",
      label: "System issues",
      presentation: "count",
    },
  ],
  sell: [
    { key: "evaluated_count", label: "Evaluated", presentation: "count" },
    { key: "data_coverage_ratio", label: "Coverage", presentation: "ratio" },
    {
      key: "provider_fallback_ratio",
      label: "Fallback",
      presentation: "ratio",
    },
    { key: "issue_count", label: "Issues", presentation: "count" },
  ],
  entry: [
    {
      key: "missing_entry_price_ratio",
      label: "Missing price",
      presentation: "ratio",
    },
    { key: "entry_count", label: "Entries", presentation: "count" },
    {
      key: "system_issue_count",
      label: "System issues",
      presentation: "count",
    },
  ],
};

const PANEL_TITLES: Record<MetricsPanelType, string> = {
  buy: "Scan Health",
  sell: "Sell Health",
  entry: "Entry Health",
};

const PANEL_DESCRIPTIONS: Record<MetricsPanelType, string> = {
  buy: "후보 생성 품질과 데이터 열화를 같은 축에서 읽습니다.",
  sell: "보유 평가 커버리지와 fallback 의존도를 추적합니다.",
  entry: "진입 판단에서 가격 누락과 시스템 이슈를 분리해 봅니다.",
};

function readSummaryNumber(
  summary: Record<string, unknown> | null,
  key: string,
): number | null {
  if (!summary) {
    return null;
  }
  const value = summary[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function averageMetric(values: Array<number | null>): number | null {
  const definedValues = values.filter(
    (value): value is number =>
      typeof value === "number" && Number.isFinite(value),
  );
  if (definedValues.length === 0) {
    return null;
  }
  return (
    definedValues.reduce((sum, value) => sum + value, 0) / definedValues.length
  );
}

function buildReportHref(
  type: MetricsPanelType,
  key?: string | null,
  bucketId?: string | null,
): string {
  const params = new URLSearchParams({ type });
  if (key) {
    params.set("key", key);
    if (bucketId) {
      params.set("bucket", bucketId);
    }
  }
  return `/reports?${params.toString()}`;
}

export function buildMetricsPanel(
  type: MetricsPanelType,
  rows: ReportIndexRow[],
): MetricsPanelData {
  const latestRow = rows[0] ?? null;
  const seriesRows = rows.slice().reverse();
  const metrics = METRIC_DEFINITIONS[type].map((definition) => {
    const values = rows.map((row) =>
      readSummaryNumber(row.summary, definition.key),
    );
    const series = seriesRows.map((row) => ({
      key: row.report_key,
      label: row.report_date,
      value: readSummaryNumber(row.summary, definition.key),
    }));

    return {
      key: definition.key,
      label: definition.label,
      presentation: definition.presentation,
      latest: values[0] ?? null,
      average: averageMetric(values),
      series,
    };
  });

  return {
    type,
    title: PANEL_TITLES[type],
    description: PANEL_DESCRIPTIONS[type],
    reportCount: rows.length,
    latestReportKey: latestRow?.report_key ?? null,
    latestGeneratedAt: latestRow?.generated_at ?? null,
    latestReportHref: buildReportHref(
      type,
      latestRow?.report_key ?? null,
      latestRow?.bucket_id ?? null,
    ),
    browseHref: buildReportHref(type),
    metrics,
  };
}

async function loadPanelState(
  type: MetricsPanelType,
): Promise<MetricsPanelState> {
  try {
    const page = await fetchReportIndexPage({
      type,
      limit: METRICS_LOOKBACK_LIMIT,
      includeTotal: false,
      lookahead: false,
    });
    return {
      panel: buildMetricsPanel(type, page.items),
      error: null,
    };
  } catch (error) {
    return {
      panel: null,
      error: toErrorMessage(error, "Unknown metrics loading error"),
    };
  }
}

export async function loadMetricsDashboardData(): Promise<MetricsDashboardData> {
  const [buy, sell, entry] = await Promise.all([
    loadPanelState("buy"),
    loadPanelState("sell"),
    loadPanelState("entry"),
  ]);

  return { buy, sell, entry };
}

export { METRICS_LOOKBACK_LIMIT };
