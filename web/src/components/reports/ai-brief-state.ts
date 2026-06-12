import aiBriefStateContract from "./ai-brief-state-contract.json";
import { asRecord, asRecordArray, readNumberLike, readString } from "./helpers";
import type { ReportJson } from "./types";

interface AiBriefStateView {
  state: string;
  reason: string;
}

interface AiBriefStateInputsView {
  preselectedCount: number;
  recommendationCount: number;
  sourceIssueCount: number;
  systemIssueCount: number;
  hasRecommendations: boolean;
  missingRecommendationSources: boolean;
}

type AiBriefStateRuleId = keyof typeof aiBriefStateContract.rules;

const AI_BRIEF_INFERENCE_PRECEDENCE =
  aiBriefStateContract.inference_precedence as AiBriefStateRuleId[];

const VALID_AI_BRIEF_STATE_REASONS: Record<
  string,
  Set<string>
> = Object.fromEntries(
  Object.entries(aiBriefStateContract.reasons_by_state).map(
    ([state, reasons]) => [state, new Set(reasons)],
  ),
);

const AI_BRIEF_RULE_PREDICATES: Record<
  AiBriefStateRuleId,
  (inputs: AiBriefStateInputsView) => boolean
> = {
  no_signal: (inputs) => inputs.preselectedCount === 0,
  source_backed_final: (inputs) =>
    inputs.hasRecommendations &&
    inputs.recommendationCount > 0 &&
    !inputs.missingRecommendationSources &&
    inputs.sourceIssueCount === 0 &&
    inputs.systemIssueCount === 0,
  system_issue: (inputs) => inputs.systemIssueCount > 0,
  weak_news_coverage: (inputs) =>
    inputs.sourceIssueCount > 0 || inputs.missingRecommendationSources,
  model_deferred: () => true,
};

function aiBriefStateForRule(ruleId: AiBriefStateRuleId): AiBriefStateView {
  const rule = aiBriefStateContract.rules[ruleId];
  return { state: rule.state, reason: rule.reason };
}

function inferAiBriefStateFromContract(
  inputs: AiBriefStateInputsView,
): AiBriefStateView {
  for (const ruleId of AI_BRIEF_INFERENCE_PRECEDENCE) {
    if (AI_BRIEF_RULE_PREDICATES[ruleId](inputs)) {
      return aiBriefStateForRule(ruleId);
    }
  }
  return aiBriefStateForRule("model_deferred");
}

function withMatchingExplicitAiBriefState(
  explicitState: string | null,
  explicitReason: string | null,
  inferred: AiBriefStateView,
): AiBriefStateView {
  if (
    explicitState &&
    explicitReason &&
    explicitState === inferred.state &&
    explicitReason === inferred.reason &&
    VALID_AI_BRIEF_STATE_REASONS[explicitState]?.has(explicitReason)
  ) {
    return { state: explicitState, reason: explicitReason };
  }
  return inferred;
}

function readSummaryCount(
  detail: ReportJson | null,
  key: string,
  fallback: number,
): number {
  const summaryRecord = asRecord(detail?.summary);
  return (
    readNumberLike(summaryRecord?.[key]) ??
    readNumberLike(detail?.[key]) ??
    fallback
  );
}

// Reported counts must never fall below the count actually observed in the
// payload, so clamp the summary value up to the observed floor.
function readCountAtLeast(
  detail: ReportJson | null,
  key: string,
  floor: number,
): number {
  return Math.max(readSummaryCount(detail, key, floor), floor);
}

function recommendationHasSources(row: ReportJson): boolean {
  return asRecordArray(row.sources).length > 0;
}

export function resolveAiBriefState(
  detail: ReportJson | null,
): AiBriefStateView {
  const explicitState = readString(detail?.brief_state);
  const explicitReason = readString(detail?.brief_reason);

  const shownRecommendations = asRecordArray(detail?.recommendations);
  const eligibleTickers = Array.isArray(detail?.eligible_tickers)
    ? detail.eligible_tickers
    : [];
  const sourceIssues = asRecordArray(detail?.source_issues);
  const systemIssues = asRecordArray(detail?.system_issues);
  const recommendationCount = readCountAtLeast(
    detail,
    "recommendation_count",
    shownRecommendations.length,
  );
  const preselectedFloor = Math.max(
    eligibleTickers.length,
    shownRecommendations.length,
    recommendationCount,
  );
  const preselectedCount = readCountAtLeast(
    detail,
    "preselected_count",
    preselectedFloor,
  );
  const sourceIssueCount = readCountAtLeast(
    detail,
    "source_issue_count",
    sourceIssues.length,
  );
  const systemIssueCount = readCountAtLeast(
    detail,
    "system_issue_count",
    systemIssues.length,
  );
  const missingSources = shownRecommendations.some(
    (row) => !recommendationHasSources(row),
  );

  return withMatchingExplicitAiBriefState(
    explicitState,
    explicitReason,
    inferAiBriefStateFromContract({
      preselectedCount,
      recommendationCount,
      sourceIssueCount,
      systemIssueCount,
      hasRecommendations: shownRecommendations.length > 0,
      missingRecommendationSources: missingSources,
    }),
  );
}
