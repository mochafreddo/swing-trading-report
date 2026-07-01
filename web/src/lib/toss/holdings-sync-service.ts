import "server-only";

import { fetchAllHoldings, replaceAllHoldings } from "@/lib/supabase-admin";
import {
  listTickerDirectoryExactBaseCandidates,
  type TickerDirectoryExactBaseResponse,
} from "@/lib/ticker-directory";
import { fetchDefaultTossHoldingsItems } from "@/lib/toss/client";
import {
  buildTossHoldingsDiffHash,
  buildTossHoldingsDryRun,
  type TossHoldingsDryRunResult,
  type TossHoldingsItem,
  type TossTickerDirectoryCandidate,
} from "@/lib/toss/holdings-sync";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";
import type { ReplaceAllHoldingsResult } from "@/lib/supabase/holdings";

export type TossHoldingsSyncMode = "dry-run" | "apply";

export type ScheduledTossAutoSyncStatus =
  | "applied"
  | "unchanged"
  | "disabled"
  | "blocked"
  | "wipe_guard_blocked"
  | "error";

export interface TossHoldingsSyncResponsePayload {
  mode: TossHoldingsSyncMode;
  diffHash: string;
  applyBlocked: boolean;
  summary: HoldingsYamlImportSummary;
  changes: TossHoldingsDryRunResult["reconciliation"]["changes"];
  blockedRows: TossHoldingsDryRunResult["blockedRows"];
  targetRows: HoldingReplaceSnapshot[];
}

export interface ScheduledTossAutoSyncResponse extends Omit<
  TossHoldingsSyncResponsePayload,
  "mode"
> {
  mode: "auto-apply";
  status: ScheduledTossAutoSyncStatus;
}

export interface TossHoldingsSyncPreview {
  currentHoldings: HoldingRecord[];
  tossItems: TossHoldingsItem[];
  tickerDirectoryCandidates: TossTickerDirectoryCandidate[];
  dryRun: TossHoldingsDryRunResult;
  diffHash: string;
  hasChanges: boolean;
  hasActiveCurrentHoldings: boolean;
  payload: TossHoldingsSyncResponsePayload;
}

export interface TossHoldingsSyncDependencies {
  fetchAllHoldings: () => Promise<HoldingRecord[]>;
  fetchTossHoldingsItems: () => Promise<TossHoldingsItem[]>;
  listTickerDirectoryExactBaseCandidates: (
    symbols: readonly string[],
  ) => Promise<TickerDirectoryExactBaseResponse>;
  replaceAllHoldings: (
    rows: HoldingReplaceSnapshot[],
  ) => Promise<ReplaceAllHoldingsResult>;
}

export const defaultTossHoldingsSyncDependencies: TossHoldingsSyncDependencies =
  {
    fetchAllHoldings,
    fetchTossHoldingsItems: fetchDefaultTossHoldingsItems,
    listTickerDirectoryExactBaseCandidates,
    replaceAllHoldings,
  };

function hasChanges(summary: HoldingsYamlImportSummary): boolean {
  return (
    summary.createCount > 0 ||
    summary.updateCount > 0 ||
    summary.deleteCount > 0
  );
}

function hasActiveQuantity(value: unknown): boolean {
  if (typeof value === "boolean" || value == null) {
    return false;
  }
  if (typeof value !== "number" && typeof value !== "string") {
    return false;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0;
}

function hasActiveHoldings(rows: readonly HoldingRecord[]): boolean {
  return rows.some((row) => hasActiveQuantity(row.quantity));
}

function buildResponsePayload(
  mode: TossHoldingsSyncMode,
  dryRun: TossHoldingsDryRunResult,
  diffHash: string,
): TossHoldingsSyncResponsePayload {
  return {
    mode,
    diffHash,
    applyBlocked: dryRun.applyBlocked,
    summary: dryRun.reconciliation.summary,
    changes: dryRun.reconciliation.changes,
    blockedRows: dryRun.blockedRows,
    targetRows: dryRun.targetRows,
  };
}

async function fetchTossTickerDirectoryCandidates(
  items: readonly TossHoldingsItem[],
  deps: Pick<
    TossHoldingsSyncDependencies,
    "listTickerDirectoryExactBaseCandidates"
  >,
): Promise<TossTickerDirectoryCandidate[]> {
  const usSymbols = Array.from(
    new Set(
      items
        .filter((item) => item.marketCountry === "US")
        .map((item) => item.symbol.trim())
        .filter(Boolean),
    ),
  ).sort((left, right) => left.localeCompare(right));
  if (usSymbols.length <= 0) {
    return [];
  }

  try {
    const result = await deps.listTickerDirectoryExactBaseCandidates(usSymbols);
    return result.candidates.map((row) => ({ ticker: row.ticker }));
  } catch {
    return [];
  }
}

export async function buildTossHoldingsSyncPreview(
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
): Promise<TossHoldingsSyncPreview> {
  const [currentHoldings, tossItems] = await Promise.all([
    deps.fetchAllHoldings(),
    deps.fetchTossHoldingsItems(),
  ]);
  const tickerDirectoryCandidates = await fetchTossTickerDirectoryCandidates(
    tossItems,
    deps,
  );
  const dryRun = buildTossHoldingsDryRun({
    currentHoldings,
    items: tossItems,
    tickerDirectoryCandidates,
  });
  const diffHash = buildTossHoldingsDiffHash(dryRun);
  const payload = buildResponsePayload("dry-run", dryRun, diffHash);

  return {
    currentHoldings,
    tossItems,
    tickerDirectoryCandidates,
    dryRun,
    diffHash,
    hasChanges: hasChanges(dryRun.reconciliation.summary),
    hasActiveCurrentHoldings: hasActiveHoldings(currentHoldings),
    payload,
  };
}

export async function applyTossHoldingsSyncPreview(
  preview: TossHoldingsSyncPreview,
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
): Promise<TossHoldingsSyncResponsePayload> {
  const responsePayload = buildResponsePayload(
    "apply",
    preview.dryRun,
    preview.diffHash,
  );
  if (preview.hasChanges) {
    const result = await deps.replaceAllHoldings(preview.dryRun.targetRows);
    responsePayload.summary = {
      ...responsePayload.summary,
      createCount: result.insertedCount,
      updateCount: result.updatedCount,
      deleteCount: result.deletedCount,
      unchangedCount: result.unchangedCount,
    };
  }
  return responsePayload;
}

export async function runScheduledTossAutoApply(
  options: { autoApplyEnabled: boolean },
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
): Promise<ScheduledTossAutoSyncResponse> {
  if (!options.autoApplyEnabled) {
    return {
      mode: "auto-apply",
      status: "disabled",
      diffHash: "",
      applyBlocked: false,
      summary: {
        incomingCount: 0,
        createCount: 0,
        updateCount: 0,
        deleteCount: 0,
        unchangedCount: 0,
        createTickers: [],
        updateTickers: [],
        deleteTickers: [],
      },
      changes: { create: [], update: [], delete: [], unchanged: [] },
      blockedRows: [],
      targetRows: [],
    };
  }

  const preview = await buildTossHoldingsSyncPreview(deps);
  const base = {
    mode: "auto-apply" as const,
    diffHash: preview.diffHash,
    applyBlocked: preview.dryRun.applyBlocked,
    summary: preview.dryRun.reconciliation.summary,
    changes: preview.dryRun.reconciliation.changes,
    blockedRows: preview.dryRun.blockedRows,
    targetRows: preview.dryRun.targetRows,
  };

  if (preview.dryRun.applyBlocked) {
    return { ...base, status: "blocked" };
  }
  if (preview.tossItems.length === 0 && preview.hasActiveCurrentHoldings) {
    return { ...base, status: "wipe_guard_blocked" };
  }
  if (!preview.hasChanges) {
    return { ...base, status: "unchanged" };
  }

  const applied = await applyTossHoldingsSyncPreview(preview, deps);
  return {
    ...applied,
    mode: "auto-apply",
    status: "applied",
  };
}
