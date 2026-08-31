import { Suspense } from "react";

import {
  TodayDecisionBoard,
  type TodayLaneSnapshot,
} from "@/components/today-decision-board";
import { hasValidAdminSession } from "@/lib/admin-prefetch";
import {
  parseDecisionBoardReportStructure,
  type DecisionBoardEnvelopeV0,
} from "@/lib/decision-board-schema";
import {
  InvalidDecisionBoardReportError,
  readReportDetail,
} from "@/lib/reports-data";
import { readDecisionBoardJournalStatus } from "@/lib/decision-board-journal.server";
import { fetchLatestDecisionBoardReport } from "@/lib/supabase-admin";
import type {
  DecisionBoardJournalStatus,
  DecisionBoardRunKind,
} from "@/lib/types";

const RUN_KINDS = ["ENTRY", "HOLDING"] as const;

function unavailableLane(
  runKind: DecisionBoardRunKind,
  state: "MISSING" | "INVALID" | "UNAVAILABLE",
): TodayLaneSnapshot {
  switch (state) {
    case "MISSING":
      return { runKind, state: "MISSING" };
    case "INVALID":
      return { runKind, state: "INVALID" };
    case "UNAVAILABLE":
      return { runKind, state: "UNAVAILABLE" };
  }
}

async function loadLane(
  runKind: DecisionBoardRunKind,
): Promise<TodayLaneSnapshot> {
  let latest: Awaited<ReturnType<typeof fetchLatestDecisionBoardReport>>;
  try {
    latest = await fetchLatestDecisionBoardReport(runKind);
  } catch {
    return unavailableLane(runKind, "UNAVAILABLE");
  }

  if (!latest) {
    return unavailableLane(runKind, "MISSING");
  }

  let detail: Awaited<ReturnType<typeof readReportDetail>>;
  try {
    detail = await readReportDetail(latest.report_key, {
      bucketId: latest.bucket_id,
    });
  } catch (error) {
    return unavailableLane(
      runKind,
      error instanceof InvalidDecisionBoardReportError
        ? "INVALID"
        : "UNAVAILABLE",
    );
  }

  try {
    const report: DecisionBoardEnvelopeV0 = parseDecisionBoardReportStructure(
      detail.report,
    );
    if (report.run_kind !== runKind) {
      return unavailableLane(runKind, "INVALID");
    }
    if (report.status === "BLOCKED") {
      return {
        runKind,
        state: "BLOCKED",
        report,
        reportKey: detail.key,
        bucketId: detail.bucketId,
      };
    }
    return {
      runKind,
      state: "PUBLISHED",
      report,
      reportKey: detail.key,
      bucketId: detail.bucketId,
    };
  } catch {
    return unavailableLane(runKind, "INVALID");
  }
}

export interface TodayDecisionBoardSnapshot {
  lanes: TodayLaneSnapshot[];
  journalStatus: DecisionBoardJournalStatus;
}

const unavailableJournal = (): DecisionBoardJournalStatus => ({
  state: "UNAVAILABLE",
  reason: "UNSAFE_OR_INVALID",
  records: [],
});

export async function loadTodayDecisionBoard(): Promise<TodayDecisionBoardSnapshot> {
  if (!(await hasValidAdminSession())) {
    return {
      lanes: RUN_KINDS.map((runKind) =>
        unavailableLane(runKind, "UNAVAILABLE"),
      ),
      journalStatus: unavailableJournal(),
    };
  }

  const [lanes, journalStatus] = await Promise.all([
    Promise.all(RUN_KINDS.map((runKind) => loadLane(runKind))),
    readDecisionBoardJournalStatus().catch(unavailableJournal),
  ]);
  return { lanes, journalStatus };
}

function TodayPageFallback() {
  return (
    <section className="panel" aria-busy="true">
      <p className="subtle">Loading today&apos;s public decisions...</p>
    </section>
  );
}

async function TodayPageContent() {
  const snapshot = await loadTodayDecisionBoard();
  return <TodayDecisionBoard {...snapshot} />;
}

export default function TodayPage() {
  return (
    <Suspense fallback={<TodayPageFallback />}>
      <TodayPageContent />
    </Suspense>
  );
}
