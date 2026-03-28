import Link from "next/link";

import type {
  MetricSeriesPoint,
  MetricsDashboardData,
  MetricsPanelData,
  MetricsPanelMetric,
  MetricsPanelState,
} from "@/lib/metrics-data";

import styles from "./metrics-dashboard.module.css";

interface MetricsDashboardProps {
  initialState?: MetricsDashboardData;
}

function formatMetricValue(
  value: number | null,
  presentation: MetricsPanelMetric["presentation"],
): string {
  if (value === null) {
    return "N/A";
  }
  if (presentation === "ratio") {
    return `${(value * 100).toFixed(1)}%`;
  }
  const normalized = Number.isInteger(value)
    ? value.toFixed(0)
    : value.toFixed(1);
  return normalized;
}

function buildSparklinePath(series: MetricSeriesPoint[]): {
  linePath: string | null;
  areaPath: string | null;
} {
  const width = 240;
  const height = 68;
  const paddingX = 6;
  const paddingY = 8;
  const numericPoints = series
    .map((point, index) => ({
      index,
      value: point.value,
    }))
    .filter(
      (point): point is { index: number; value: number } =>
        typeof point.value === "number" && Number.isFinite(point.value),
    );

  if (numericPoints.length === 0) {
    return { linePath: null, areaPath: null };
  }

  const minValue = Math.min(...numericPoints.map((point) => point.value));
  const maxValue = Math.max(...numericPoints.map((point) => point.value));
  const valueRange = maxValue - minValue || 1;
  const xStep =
    numericPoints.length <= 1
      ? 0
      : (width - paddingX * 2) / (numericPoints.length - 1);

  const coordinates = numericPoints.map((point, index) => {
    const x = paddingX + xStep * index;
    const y =
      height -
      paddingY -
      ((point.value - minValue) / valueRange) * (height - paddingY * 2);
    return { x, y };
  });

  const linePath = coordinates
    .map(
      (coordinate, index) =>
        `${index === 0 ? "M" : "L"}${coordinate.x.toFixed(2)},${coordinate.y.toFixed(2)}`,
    )
    .join(" ");
  const lastCoordinate = coordinates[coordinates.length - 1];
  const firstCoordinate = coordinates[0];
  const areaPath = `${linePath} L${lastCoordinate.x.toFixed(2)},${(
    height - paddingY
  ).toFixed(2)} L${firstCoordinate.x.toFixed(2)},${(height - paddingY).toFixed(
    2,
  )} Z`;

  return { linePath, areaPath };
}

function Sparkline({ metric }: { metric: MetricsPanelMetric }) {
  const sparklineId = `metricsArea-${metric.key}`;
  const { linePath, areaPath } = buildSparklinePath(metric.series);

  return (
    <div className={styles.sparklineWrap}>
      <svg
        className={styles.sparkline}
        viewBox="0 0 240 68"
        role="img"
        aria-label={`${metric.label} 최근 ${metric.series.length}개 추이`}
      >
        <defs>
          <linearGradient id={sparklineId} x1="0%" x2="0%" y1="0%" y2="100%">
            <stop offset="0%" stopColor="rgba(107, 163, 255, 0.35)" />
            <stop offset="100%" stopColor="rgba(107, 163, 255, 0)" />
          </linearGradient>
        </defs>
        <path className={styles.sparklineTrack} d="M6 60 H234" />
        {linePath && areaPath ? (
          <>
            <path
              className={styles.sparklineArea}
              d={areaPath}
              fill={`url(#${sparklineId})`}
            />
            <path className={styles.sparklineStroke} d={linePath} />
          </>
        ) : (
          <path className={styles.sparklineFallback} d="M12 34 H228" />
        )}
      </svg>
      <p className={styles.sparklineCaption}>
        최근 {metric.series.length}개 run 기준
      </p>
    </div>
  );
}

function MetricsMetricCard({ metric }: { metric: MetricsPanelMetric }) {
  return (
    <article className={styles.metricCard}>
      <div className={styles.metricHeader}>
        <p className={styles.metricLabel}>{metric.label}</p>
        <p className={styles.metricCurrent}>
          {formatMetricValue(metric.latest, metric.presentation)}
        </p>
        <p className={styles.metricAverage}>
          Avg {formatMetricValue(metric.average, metric.presentation)}
        </p>
      </div>
      <Sparkline metric={metric} />
    </article>
  );
}

function MetricsPanel({ panel }: { panel: MetricsPanelData }) {
  return (
    <section className={`panel ${styles.panel}`}>
      <div className={styles.panelHeader}>
        <div className={styles.panelHeaderCopy}>
          <div>
            <h2 className="panelTitle">{panel.title}</h2>
            <p className="subtle">{panel.description}</p>
          </div>
          <p className={styles.panelMeta}>
            <span>{panel.reportCount} reports</span>
            <span>•</span>
            <span>{panel.latestGeneratedAt ?? "generated_at unavailable"}</span>
          </p>
        </div>
        <div className={styles.actions}>
          <Link className={styles.link} href={panel.latestReportHref}>
            Open latest {panel.type} report
          </Link>
          <Link className={styles.link} href={panel.browseHref}>
            Browse {panel.type} reports
          </Link>
        </div>
      </div>

      <div className={styles.metricGrid}>
        {panel.metrics.map((metric) => (
          <MetricsMetricCard key={metric.key} metric={metric} />
        ))}
      </div>
    </section>
  );
}

function MetricsPanelError({
  type,
  state,
}: {
  type: MetricsPanelData["type"];
  state: MetricsPanelState;
}) {
  return (
    <section className={`panel ${styles.panel} ${styles.errorPanel}`}>
      <div className={styles.panelHeader}>
        <div className={styles.panelHeaderCopy}>
          <div>
            <h2 className="panelTitle">
              {type === "buy"
                ? "Scan Health"
                : type === "sell"
                  ? "Sell Health"
                  : "Entry Health"}
            </h2>
            <p className="subtle">
              이 패널은 현재 집계를 불러오지 못했습니다. 다른 패널은 계속 사용할
              수 있습니다.
            </p>
          </div>
        </div>
        <div className={styles.actions}>
          <Link className={styles.link} href={`/reports?type=${type}`}>
            Browse {type} reports
          </Link>
        </div>
      </div>
      <p className={styles.errorText}>
        {state.error ?? "Metrics panel unavailable"}
      </p>
    </section>
  );
}

export function MetricsDashboard({ initialState }: MetricsDashboardProps) {
  if (!initialState) {
    return (
      <section className={`panel ${styles.panel}`}>
        <h2 className="panelTitle">Metrics</h2>
        <p className="subtle">Loading metrics...</p>
      </section>
    );
  }

  const panels: Array<[MetricsPanelData["type"], MetricsPanelState]> = [
    ["buy", initialState.buy],
    ["entry", initialState.entry],
    ["sell", initialState.sell],
  ];
  const healthyPanelCount = panels.filter(([, state]) => state.panel).length;
  const brokenPanelCount = panels.length - healthyPanelCount;
  const totalReports = panels.reduce(
    (sum, [, state]) => sum + (state.panel?.reportCount ?? 0),
    0,
  );

  return (
    <div className={styles.shell}>
      <section className={`panel ${styles.hero}`}>
        <div className={styles.heroCopy}>
          <p className={styles.eyebrow}>Operations Metrics</p>
          <h1 className={styles.heroTitle}>
            Run quality, not just run success.
          </h1>
          <p className="subtle">
            타입별 최근 30개 리포트에서 후보 수, coverage, fallback, 가격 누락을
            동시에 읽어 운영 저하와 전략 열화를 분리합니다.
          </p>
        </div>
        <div className={styles.heroMeta}>
          <div className={styles.metaItem}>
            <p className={styles.metaLabel}>Healthy Panels</p>
            <p className={styles.metaValue}>{healthyPanelCount}/3</p>
          </div>
          <div className={styles.metaItem}>
            <p className={styles.metaLabel}>Loaded Reports</p>
            <p className={styles.metaValue}>{totalReports}</p>
          </div>
          <div className={styles.metaItem}>
            <p className={styles.metaLabel}>Panel Errors</p>
            <p className={styles.metaValue}>{brokenPanelCount}</p>
          </div>
        </div>
      </section>

      <div className={styles.panels}>
        {panels.map(([type, state]) =>
          state.panel ? (
            <MetricsPanel key={type} panel={state.panel} />
          ) : (
            <MetricsPanelError key={type} type={type} state={state} />
          ),
        )}
      </div>
    </div>
  );
}
