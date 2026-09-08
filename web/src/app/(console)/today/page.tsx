import { PortfolioReviewFixtureControls } from "@/components/portfolio-review-fixture-controls";
import {
  liveReviewFixtureOrigin,
  readLiveReviewFixture,
} from "@/lib/portfolio-review-fixture.server";
import { Suspense } from "react";
import { PortfolioStoredReview } from "@/components/portfolio-stored-review";
import {
  portfolioReviewStoreSchema,
  type StoredReviewSource,
} from "@/lib/portfolio-review-store-schema";
import { readAuthenticatedStoredReviews } from "@/lib/portfolio-review-store.server";
import storedReviewFixture from "../../../../fixtures/portfolio-review-store.r2.synthetic.json";

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
import type { TodayDogfoodSelection } from "@/lib/portfolio-dogfood-t14-schema";
import { readDecisionBoardJournalStatus } from "@/lib/decision-board-journal.server";
import { fetchLatestDecisionBoardReport } from "@/lib/supabase-admin";
import type {
  DecisionBoardJournalStatus,
  DecisionBoardRunKind,
} from "@/lib/types";

const RUN_KINDS = ["ENTRY", "HOLDING"] as const;
type TodaySearchParams = Record<string, string | string[] | undefined>;

export function readTodayDogfoodSelection(
  searchParams: TodaySearchParams,
): TodayDogfoodSelection {
  const selection = searchParams.dogfood;
  if (selection === undefined) {
    return { state: "DEFAULT" };
  }
  if (selection === "invalid-contract") {
    return { state: "INVALID_FIXTURE" };
  }
  if (
    typeof selection !== "string" ||
    !/^[a-z0-9][a-z0-9-]{0,63}$/.test(selection)
  ) {
    return { state: "INVALID" };
  }
  return { state: "SELECTED", scenarioId: selection };
}

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

async function TodayPageContent({
  searchParams,
}: {
  searchParams: Promise<TodaySearchParams>;
}) {
  const [snapshot, resolvedSearchParams] = await Promise.all([
    loadTodayDecisionBoard(),
    searchParams,
  ]);
  const synthetic =
    process.env.SAB_SKIP_ROOT_ENV === "1" &&
    process.env.SAB_PORTFOLIO_R2_FIXTURE === "1";
  let stored: StoredReviewSource = await readAuthenticatedStoredReviews();
  if (synthetic && (await hasValidAdminSession())) {
    if (liveReviewFixtureOrigin()) {
      stored = await readLiveReviewFixture();
    } else {
      const value = portfolioReviewStoreSchema.safeParse(storedReviewFixture);
      stored = value.success
        ? { state: "READY", value: value.data }
        : { state: "UNAVAILABLE" };
    }
    if (resolvedSearchParams.stored === "stale") stored = { state: "STALE" };
    if (resolvedSearchParams.stored === "error")
      stored = { state: "UNAVAILABLE" };
  }
  return (
    <>
      <TodayDecisionBoard
        {...snapshot}
        dogfoodSelection={readTodayDogfoodSelection(resolvedSearchParams)}
      />
      <PortfolioStoredReview source={stored} synthetic={synthetic} />
      {liveReviewFixtureOrigin() &&
        stored.state === "READY" &&
        stored.value.rows
          .filter((row) => row.run_id !== null)
          .map((row) => (
            <PortfolioReviewFixtureControls
              key={row.run_id}
              runId={row.run_id!}
            />
          ))}
    </>
  );
}

export default function TodayPage({
  searchParams = Promise.resolve({}),
}: {
  searchParams?: Promise<TodaySearchParams>;
} = {}) {
  return (
    <Suspense fallback={<TodayPageFallback />}>
      <TodayPageContent searchParams={searchParams} />
    </Suspense>
  );
}
