import Link from "next/link";

import longTermSyntheticFixture from "../../fixtures/portfolio-long-term.t13.synthetic.json";

import type { DecisionBoardEnvelopeV0 } from "@/lib/decision-board-schema";
import { parsePortfolioLongTermT13Fixture } from "@/lib/portfolio-long-term-schema";
import type {
  DecisionBoardJournalStatus,
  DecisionBoardRunKind,
} from "@/lib/types";

import { UnclassifiedQueuePreview } from "./unclassified-queue-preview";
import { LongTermSyntheticLane } from "./long-term-synthetic-lane";

import styles from "./today-decision-board.module.css";

const LONG_TERM_SYNTHETIC_FIXTURE = parsePortfolioLongTermT13Fixture(
  longTermSyntheticFixture,
);

type PublishedDecisionBoardReport = Extract<
  DecisionBoardEnvelopeV0,
  { status: "PUBLISHED" }
>;
type BlockedDecisionBoardReport = Extract<
  DecisionBoardEnvelopeV0,
  { status: "BLOCKED" }
>;

type LoadedTodayLaneSnapshot =
  | {
      runKind: DecisionBoardRunKind;
      state: "PUBLISHED";
      report: PublishedDecisionBoardReport;
      reportKey: string;
      bucketId: string;
    }
  | {
      runKind: DecisionBoardRunKind;
      state: "BLOCKED";
      report: BlockedDecisionBoardReport;
      reportKey: string;
      bucketId: string;
    };

export type TodayLaneSnapshot =
  | {
      runKind: DecisionBoardRunKind;
      state: "MISSING";
    }
  | {
      runKind: DecisionBoardRunKind;
      state: "INVALID";
    }
  | {
      runKind: DecisionBoardRunKind;
      state: "UNAVAILABLE";
    }
  | LoadedTodayLaneSnapshot;

type PublicDecisionItem = Extract<
  DecisionBoardEnvelopeV0,
  { status: "PUBLISHED" }
>["decision_payload"]["items"][number];

export interface TodayQueueItem {
  key: string;
  priority: number;
  kind:
    "JOURNAL_ALERT" | "LANE_ALERT" | "RUN_ISSUE" | "DECISION" | "HISTORICAL";
  runKind?: DecisionBoardRunKind;
  label: string;
  detail?: string;
  ticker?: string;
  companyName?: string;
  sourceStatus?: "DECIDED" | "REVIEW";
  sourceAction?: string;
  projectionStatus?: "FRESHNESS_UNPROVEN · NOT ACTIVE";
  issueCodes: string[];
  evidence: PublicDecisionItem["evidence"];
  reportHref?: string;
  runId?: string;
  expectedAt?: string;
}

export interface TodayBoardViewModel {
  alerts: TodayQueueItem[];
  queue: TodayQueueItem[];
  holds: TodayQueueItem[];
  historical: TodayQueueItem[];
  actionCount: number;
  hasLaneWarning: boolean;
  hasJournalWarning: boolean;
  journalUnavailable: boolean;
}

const STATE_COPY = {
  MISSING: {
    title: "No verified report",
    detail: "This lane has no indexed public report to review.",
  },
  INVALID: {
    title: "Invalid report",
    detail: "The latest indexed artifact did not pass the public contract.",
  },
  UNAVAILABLE: {
    title: "Lane unavailable",
    detail: "The latest public report could not be verified right now.",
  },
} as const;

function buildReportHref(lane: LoadedTodayLaneSnapshot) {
  const params = new URLSearchParams({
    type: "decision-board",
    runKind: lane.runKind,
    key: lane.reportKey,
    bucket: lane.bucketId,
  });
  return `/reports?${params.toString()}`;
}

function itemPriority(item: PublicDecisionItem): number {
  if (item.status === "REVIEW") {
    return 3;
  }
  if (item.action === "SELL") {
    return 1;
  }
  return 2;
}

function decisionItem(
  lane: Extract<TodayLaneSnapshot, { state: "PUBLISHED" }>,
  item: PublicDecisionItem,
): TodayQueueItem {
  const label = item.status === "DECIDED" ? item.action : "REVIEW";
  return {
    key: `${lane.runKind}:${item.instrument.canonical_ticker}:${label}`,
    priority: itemPriority(item),
    kind: "DECISION",
    runKind: lane.runKind,
    label,
    ticker: item.instrument.canonical_ticker,
    companyName: item.instrument.company_name,
    issueCodes: item.issues.map((issue) => issue.code),
    evidence: item.evidence,
    reportHref: buildReportHref(lane),
  };
}

function historicalItem(
  lane: Extract<TodayLaneSnapshot, { state: "PUBLISHED" }>,
  item: PublicDecisionItem,
): TodayQueueItem {
  const projected = decisionItem(lane, item);
  return {
    ...projected,
    key: `historical:${projected.key}`,
    kind: "HISTORICAL",
    sourceStatus: item.status,
    sourceAction: item.status === "DECIDED" ? item.action : undefined,
    projectionStatus: "FRESHNESS_UNPROVEN · NOT ACTIVE",
  };
}

export function buildTodayBoardViewModel(
  lanes: readonly TodayLaneSnapshot[],
  journalStatus?: DecisionBoardJournalStatus,
): TodayBoardViewModel {
  const alerts: TodayQueueItem[] = [];
  const queue: TodayQueueItem[] = [];
  const holds: TodayQueueItem[] = [];
  const historical: TodayQueueItem[] = [];
  let hasLaneWarning = false;

  if (journalStatus?.state === "AVAILABLE") {
    for (const record of journalStatus.records) {
      alerts.push({
        key: `journal:${record.run_id}:${record.status}`,
        priority: -2,
        kind: "JOURNAL_ALERT",
        runKind: record.run_kind,
        label: record.status,
        issueCodes: record.issues.map((issue) => issue.code),
        evidence: [],
        runId: record.run_id,
        expectedAt: record.expected_at,
      });
    }
  } else if (journalStatus?.state === "UNAVAILABLE") {
    alerts.push({
      key: "journal:UNAVAILABLE",
      priority: -2,
      kind: "JOURNAL_ALERT",
      label: "JOURNAL UNAVAILABLE",
      detail: "Missed or stale runs cannot be ruled out from this public view.",
      issueCodes: [],
      evidence: [],
    });
  }

  for (const lane of lanes) {
    if (
      lane.state === "MISSING" ||
      lane.state === "INVALID" ||
      lane.state === "UNAVAILABLE"
    ) {
      hasLaneWarning = true;
      alerts.push({
        key: `${lane.runKind}:${lane.state}`,
        priority: 0,
        kind: "LANE_ALERT",
        runKind: lane.runKind,
        label: STATE_COPY[lane.state].title,
        issueCodes: [],
        evidence: [],
      });
      continue;
    }

    const reportHref = buildReportHref(lane);
    if (lane.state === "BLOCKED") {
      hasLaneWarning = true;
      alerts.push({
        key: `${lane.runKind}:BLOCKED`,
        priority: -1,
        kind: "LANE_ALERT",
        runKind: lane.runKind,
        label: "BLOCKED",
        issueCodes: lane.report.issues.map((issue) => issue.code),
        evidence: [],
        reportHref,
      });
      continue;
    }

    hasLaneWarning = true;
    alerts.push({
      key: `${lane.runKind}:FRESHNESS_UNPROVEN`,
      priority: 0,
      kind: "LANE_ALERT",
      runKind: lane.runKind,
      label: "FRESHNESS_UNPROVEN · NOT ACTIVE",
      detail:
        "V0 has no valid_until or current dependency-freshness proof. Source decisions remain historical audit facts only.",
      issueCodes: [],
      evidence: [],
      reportHref,
    });

    if (lane.report.issues.length > 0) {
      hasLaneWarning = true;
      alerts.push({
        key: `${lane.runKind}:RUN_ISSUE`,
        priority: 0,
        kind: "RUN_ISSUE",
        runKind: lane.runKind,
        label: "Run issue",
        issueCodes: lane.report.issues.map((issue) => issue.code),
        evidence: [],
        reportHref,
      });
    }

    for (const item of lane.report.decision_payload.items) {
      historical.push(historicalItem(lane, item));
    }
  }

  alerts.sort(
    (left, right) =>
      left.priority - right.priority ||
      (left.runKind ?? "").localeCompare(right.runKind ?? "") ||
      (left.ticker ?? "").localeCompare(right.ticker ?? ""),
  );
  queue.sort(
    (left, right) =>
      left.priority - right.priority ||
      (left.runKind ?? "").localeCompare(right.runKind ?? "") ||
      (left.ticker ?? "").localeCompare(right.ticker ?? ""),
  );
  holds.sort((left, right) =>
    (left.ticker ?? "").localeCompare(right.ticker ?? ""),
  );
  historical.sort(
    (left, right) =>
      (left.runKind ?? "").localeCompare(right.runKind ?? "") ||
      (left.ticker ?? "").localeCompare(right.ticker ?? ""),
  );

  return {
    alerts,
    queue,
    holds,
    historical,
    actionCount: queue.filter((item) => item.kind === "DECISION").length,
    hasLaneWarning,
    hasJournalWarning: alerts.some((item) => item.kind === "JOURNAL_ALERT"),
    journalUnavailable: journalStatus?.state === "UNAVAILABLE",
  };
}

function formatCreatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-US", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Asia/Seoul",
      }).format(date);
}

function LaneCard({ lane }: { lane: TodayLaneSnapshot }) {
  if (
    lane.state === "MISSING" ||
    lane.state === "INVALID" ||
    lane.state === "UNAVAILABLE"
  ) {
    return (
      <article className={`${styles.laneCard} ${styles.warningCard}`}>
        <div className={styles.cardHeading}>
          <h3>{lane.runKind}</h3>
          <span className={styles.statusBadge}>{lane.state}</span>
        </div>
        <p className={styles.laneMessage}>{STATE_COPY[lane.state].detail}</p>
        <dl className={styles.laneMeta}>
          <div>
            <dt>Run kind</dt>
            <dd>{lane.runKind}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>{lane.state}</dd>
          </div>
        </dl>
      </article>
    );
  }

  const href = buildReportHref(lane);
  return (
    <article
      className={`${styles.laneCard} ${lane.state === "BLOCKED" ? styles.blockedCard : ""}`.trim()}
    >
      <div className={styles.cardHeading}>
        <h3>{lane.runKind}</h3>
        <span className={styles.statusBadge}>{lane.state}</span>
      </div>
      <dl className={styles.laneMeta}>
        <div>
          <dt>Generated</dt>
          <dd>
            <time dateTime={lane.report.created_at}>
              {formatCreatedAt(lane.report.created_at)} KST
            </time>
          </dd>
        </div>
        <div>
          <dt>Run kind</dt>
          <dd>{lane.report.run_kind}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{lane.report.status}</dd>
        </div>
      </dl>
      <Link className={styles.reviewLink} href={href}>
        Open verified report
      </Link>
    </article>
  );
}

function QueueCard({ item }: { item: TodayQueueItem }) {
  return (
    <article
      className={`${styles.queueCard} ${item.priority <= 0 ? styles.urgent : ""}`.trim()}
    >
      <div className={styles.queueHeading}>
        <span className={styles.actionBadge}>{item.label}</span>
        <span className={styles.runKind}>{item.runKind ?? "SYSTEM"}</span>
      </div>
      {item.ticker ? (
        <h3>
          {item.ticker}
          {item.companyName ? <span>{item.companyName}</span> : null}
        </h3>
      ) : (
        <h3>
          {item.runKind
            ? `${item.runKind} lane needs review`
            : "Operational status"}
        </h3>
      )}
      {item.projectionStatus ? (
        <p className={styles.notActive}>{item.projectionStatus}</p>
      ) : null}
      {item.sourceStatus ? (
        <p className={styles.sourceStatus}>
          Source status: {item.sourceStatus}
          {item.sourceAction ? ` · Source action: ${item.sourceAction}` : ""}
        </p>
      ) : null}
      {item.detail ? <p className={styles.issueCodes}>{item.detail}</p> : null}
      {item.issueCodes.length > 0 ? (
        <p className={styles.issueCodes}>
          Issue codes: {item.issueCodes.join(" · ")}
        </p>
      ) : item.kind === "LANE_ALERT" && !item.detail ? (
        <p className={styles.issueCodes}>
          No verified public advice is available for this lane.
        </p>
      ) : null}
      {item.kind === "JOURNAL_ALERT" && item.runId && item.expectedAt ? (
        <dl className={styles.operationalMeta}>
          <div>
            <dt>Expected slot</dt>
            <dd>
              <time dateTime={item.expectedAt}>
                {formatCreatedAt(item.expectedAt)} KST
              </time>
            </dd>
          </div>
          <div>
            <dt>Run ID</dt>
            <dd>{item.runId}</dd>
          </div>
        </dl>
      ) : null}
      {item.evidence.length > 0 ? (
        <ul className={styles.evidenceList} aria-label="Public evidence">
          {item.evidence.map((evidence) => (
            <li key={evidence.claim_id}>
              <a
                href={evidence.source_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {evidence.citation_label}
              </a>
              <span>
                {evidence.role} · Publisher: {evidence.publisher} · Source
                freshness: {evidence.freshness} · Published:{" "}
                <time dateTime={evidence.published_at}>
                  {evidence.published_at}
                </time>
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {item.reportHref ? (
        <Link className={styles.reviewLink} href={item.reportHref}>
          Review report
        </Link>
      ) : null}
    </article>
  );
}

export function TodayDecisionBoard({
  lanes,
  journalStatus,
}: {
  lanes: readonly TodayLaneSnapshot[];
  journalStatus: DecisionBoardJournalStatus;
}) {
  const model = buildTodayBoardViewModel(lanes, journalStatus);
  return (
    <div className={styles.board}>
      <section className={styles.intro} aria-labelledby="today-board-title">
        <div>
          <p className={styles.kicker}>Advice-only public projection</p>
          <h2 id="today-board-title">Today&apos;s Investment Actions</h2>
          <p>
            Latest verified ENTRY and HOLDING reports. Trading remains manual.
          </p>
        </div>
        <div className={styles.summary} aria-live="polite">
          <strong>{model.actionCount}</strong>
          <span>queued decisions</span>
          {model.hasLaneWarning || model.hasJournalWarning ? (
            <em>Attention required</em>
          ) : null}
        </div>
      </section>

      <section aria-labelledby="lane-status-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>Latest public reports</p>
            <h2 id="lane-status-title">Lane status</h2>
          </div>
        </div>
        <div className={styles.laneGrid}>
          {lanes.map((lane) => (
            <LaneCard key={lane.runKind} lane={lane} />
          ))}
        </div>
      </section>

      <section aria-labelledby="decision-queue-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>Operational precedence</p>
            <h2 id="decision-queue-title">Attention</h2>
          </div>
          <span>Journal · lane projection</span>
        </div>
        {model.alerts.length > 0 ? (
          <div className={styles.queueGrid} aria-label="Operational alerts">
            {model.alerts.map((item) => (
              <QueueCard key={item.key} item={item} />
            ))}
          </div>
        ) : null}
      </section>

      <section aria-labelledby="active-decision-queue-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>Freshness-proven only</p>
            <h2 id="active-decision-queue-title">Active decision queue</h2>
          </div>
          <span>SELL · BUY/AVOID · REVIEW</span>
        </div>
        {model.queue.length > 0 ? (
          <div className={styles.queueGrid}>
            {model.queue.map((item) => (
              <QueueCard key={item.key} item={item} />
            ))}
          </div>
        ) : (
          <p className={styles.emptyState}>
            No freshness-proven active decisions are available. Historical
            source actions below are not active advice.
          </p>
        )}
      </section>

      <section aria-labelledby="historical-snapshot-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>Audit facts</p>
            <h2 id="historical-snapshot-title">Historical snapshot</h2>
          </div>
          <span>{model.historical.length} source items · NOT ACTIVE</span>
        </div>
        {model.historical.length > 0 ? (
          <div className={styles.historicalGrid}>
            {model.historical.map((item) => (
              <QueueCard key={item.key} item={item} />
            ))}
          </div>
        ) : (
          <p className={styles.emptyState}>
            No published source items are available for historical review.
          </p>
        )}
      </section>

      <section aria-labelledby="hold-monitor-title">
        <div className={styles.sectionHeading}>
          <div>
            <p className={styles.kicker}>Normal monitoring</p>
            <h2 id="hold-monitor-title">HOLD monitor</h2>
          </div>
          <span>{model.holds.length} positions</span>
        </div>
        {model.holds.length > 0 ? (
          <div className={styles.holdGrid}>
            {model.holds.map((item) => (
              <QueueCard key={item.key} item={item} />
            ))}
          </div>
        ) : (
          <p className={styles.emptyState}>
            No freshness-proven active HOLD items are available. Source HOLD
            facts, when present, remain in the historical snapshot.
          </p>
        )}
      </section>

      <LongTermSyntheticLane fixture={LONG_TERM_SYNTHETIC_FIXTURE} />

      <UnclassifiedQueuePreview />

      <p className={styles.completenessNote}>
        This view uses the public projection only. It cannot prove that every
        eligible account item was evaluated, so it never infers an absolute “NO
        ACTION” state.
      </p>
    </div>
  );
}
