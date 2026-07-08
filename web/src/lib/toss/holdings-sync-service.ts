import "server-only";

import {
  applyScheduledTossQuarantine,
  fetchAllHoldings,
  replaceAllHoldings,
} from "@/lib/supabase-admin";
import { upsertRuntimeStateEntry } from "@/lib/supabase/runtime-state";
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
import qaTossHoldingsFixture from "../../../fixtures/toss-holdings.qa.json";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";
import type { ReplaceAllHoldingsResult } from "@/lib/supabase/holdings";

type TossHoldingsSyncMode = "dry-run" | "apply";

type ScheduledTossAutoSyncStatus =
  | "applied"
  | "unchanged"
  | "disabled"
  | "blocked"
  | "wipe_guard_blocked"
  | "marker_failed"
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
  quarantinedCount: number;
  quarantinedTickers: string[];
}

export interface TossHoldingsSyncPreview {
  currentHoldings: HoldingRecord[];
  tossItems: TossHoldingsItem[];
  tickerDirectoryCandidates: TossTickerDirectoryCandidate[];
  dryRun: TossHoldingsDryRunResult;
  diffHash: string;
  hasChanges: boolean;
  hasCurrentHoldings: boolean;
  payload: TossHoldingsSyncResponsePayload;
}

export interface TossHoldingsSyncPreviewOptions {
  tickerDirectoryLookupFailureMode?: "ignore" | "throw";
}

export interface TossHoldingsSyncDependencies {
  fetchAllHoldings: () => Promise<HoldingRecord[]>;
  fetchTossHoldingsItems: () => Promise<TossHoldingsItem[]>;
  listTickerDirectoryExactBaseCandidates: (
    symbols: readonly string[],
  ) => Promise<TickerDirectoryExactBaseResponse>;
  replaceAllHoldings: (
    rows: HoldingReplaceSnapshot[],
    options?: { expectedCurrentHoldings?: readonly HoldingRecord[] },
  ) => Promise<ReplaceAllHoldingsResult>;
  applyScheduledTossQuarantine: (input: {
    targetRows: HoldingReplaceSnapshot[];
    quarantineTickers: string[];
    expectedCurrentHoldings: readonly HoldingRecord[];
    sessionDate: string;
    diffHash: string;
  }) => Promise<{
    insertedCount: number;
    updatedCount: number;
    quarantinedCount: number;
    unchangedCount: number;
  }>;
}

export interface ScheduledTossFreshnessMarkerResult {
  stateKey: string;
  sessionDate: string;
}

const defaultTossHoldingsSyncDependencies: TossHoldingsSyncDependencies = {
  fetchAllHoldings,
  fetchTossHoldingsItems: fetchDefaultTossHoldingsItems,
  listTickerDirectoryExactBaseCandidates,
  replaceAllHoldings,
  applyScheduledTossQuarantine,
};

class TossHoldingsFixtureError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TossHoldingsFixtureError";
  }
}

const FIXTURE_SUPABASE_HOSTS = new Set([
  "127.0.0.1",
  "localhost",
  "::1",
  "host.docker.internal",
]);

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function readFixtureString(
  record: Record<string, unknown>,
  field: keyof TossHoldingsItem,
  context: string,
): string {
  const value = record[field];
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  throw new TossHoldingsFixtureError(
    `${context}: '${field}' must be a non-empty string or finite number.`,
  );
}

function readOptionalFixtureString(
  record: Record<string, unknown>,
  field: keyof TossHoldingsItem,
): string | null {
  const value = record[field];
  if (value == null) {
    return null;
  }
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function parseFixtureItem(value: unknown, index: number): TossHoldingsItem {
  const record = asRecord(value);
  const context = `Toss holdings fixture item ${index + 1}`;
  if (!record) {
    throw new TossHoldingsFixtureError(`${context} must be an object.`);
  }

  return {
    symbol: readFixtureString(record, "symbol", context),
    name: readOptionalFixtureString(record, "name"),
    marketCountry: readFixtureString(record, "marketCountry", context),
    currency: readFixtureString(record, "currency", context),
    quantity: readFixtureString(record, "quantity", context),
    averagePurchasePrice: readFixtureString(
      record,
      "averagePurchasePrice",
      context,
    ),
  };
}

function readFixtureItems(payload: unknown): TossHoldingsItem[] {
  const holdings = Array.isArray(payload)
    ? payload
    : asRecord(payload)?.holdings;
  if (!Array.isArray(holdings)) {
    throw new TossHoldingsFixtureError(
      "Toss holdings fixture must be an array or an object with a holdings array.",
    );
  }
  return holdings.map(parseFixtureItem);
}

async function fetchFixtureTossHoldingsItems(): Promise<TossHoldingsItem[]> {
  return readFixtureItems(qaTossHoldingsFixture);
}

function isLocalFixtureSupabaseUrl(value: string): boolean {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:") {
      return false;
    }
    return FIXTURE_SUPABASE_HOSTS.has(url.hostname);
  } catch {
    return false;
  }
}

function assertFixtureSourceAllowed(): void {
  if (process.env.TOSS_SYNC_QA_FIXTURE_ENABLED !== "1") {
    throw new TossHoldingsFixtureError(
      "TOSS_SYNC_SOURCE=fixture requires TOSS_SYNC_QA_FIXTURE_ENABLED=1.",
    );
  }

  const supabaseUrl = process.env.SUPABASE_URL?.trim() ?? "";
  if (!isLocalFixtureSupabaseUrl(supabaseUrl)) {
    throw new TossHoldingsFixtureError(
      "TOSS_SYNC_SOURCE=fixture requires a local Supabase URL.",
    );
  }
}

export function buildTossHoldingsSyncDependenciesFromEnv(): TossHoldingsSyncDependencies {
  const source = process.env.TOSS_SYNC_SOURCE?.trim().toLowerCase();
  if (source === "fixture") {
    assertFixtureSourceAllowed();
    return {
      ...defaultTossHoldingsSyncDependencies,
      fetchTossHoldingsItems: fetchFixtureTossHoldingsItems,
    };
  }
  return defaultTossHoldingsSyncDependencies;
}

function hasChanges(summary: HoldingsYamlImportSummary): boolean {
  return (
    summary.createCount > 0 ||
    summary.updateCount > 0 ||
    summary.deleteCount > 0
  );
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

function assertReplaceAllResultMatchesPreview(
  result: ReplaceAllHoldingsResult,
  summary: HoldingsYamlImportSummary,
): void {
  const matches =
    result.insertedCount === summary.createCount &&
    result.updatedCount === summary.updateCount &&
    result.deletedCount === summary.deleteCount &&
    result.unchangedCount === summary.unchangedCount;
  if (!matches) {
    throw new Error("replace_holdings_v1 result did not match preview");
  }
}

export function resolveKstSessionDate(now: Date = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const byType = new Map(parts.map((part) => [part.type, part.value]));
  return `${byType.get("year")}-${byType.get("month")}-${byType.get("day")}`;
}

export async function recordScheduledTossFreshnessMarker(
  result: ScheduledTossAutoSyncResponse,
  options: { sessionDate?: string; now?: Date } = {},
): Promise<ScheduledTossFreshnessMarkerResult | null> {
  if (result.status !== "applied" && result.status !== "unchanged") {
    return null;
  }
  const now = options.now ?? new Date();
  const sessionDate = options.sessionDate ?? resolveKstSessionDate(now);
  const stateKey = `toss-sync:success:MIXED:${sessionDate}`;
  const expiresAt = new Date(now.getTime() + 36 * 60 * 60 * 1000).toISOString();
  await upsertRuntimeStateEntry(
    stateKey,
    {
      scope: "MIXED",
      sessionDate,
      status: result.status,
      diffHash: result.diffHash,
      incomingCount: result.summary.incomingCount,
      createCount: result.summary.createCount,
      updateCount: result.summary.updateCount,
      deleteCount: result.summary.deleteCount,
      unchangedCount: result.summary.unchangedCount,
      quarantinedCount: result.quarantinedCount,
      quarantinedTickers: result.quarantinedTickers,
      source: "scheduled-route",
      timezone: "Asia/Seoul",
      updatedAt: now.toISOString(),
    },
    expiresAt,
  );
  return { stateKey, sessionDate };
}

async function fetchTossTickerDirectoryCandidates(
  items: readonly TossHoldingsItem[],
  deps: Pick<
    TossHoldingsSyncDependencies,
    "listTickerDirectoryExactBaseCandidates"
  >,
  options: TossHoldingsSyncPreviewOptions = {},
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
  } catch (error) {
    if (options.tickerDirectoryLookupFailureMode === "throw") {
      throw error;
    }
    return [];
  }
}

export async function buildTossHoldingsSyncPreview(
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
  options: TossHoldingsSyncPreviewOptions = {},
): Promise<TossHoldingsSyncPreview> {
  const [currentHoldings, tossItems] = await Promise.all([
    deps.fetchAllHoldings(),
    deps.fetchTossHoldingsItems(),
  ]);
  const tickerDirectoryCandidates = await fetchTossTickerDirectoryCandidates(
    tossItems,
    deps,
    options,
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
    hasCurrentHoldings: currentHoldings.length > 0,
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
    const result = await deps.replaceAllHoldings(preview.dryRun.targetRows, {
      expectedCurrentHoldings: preview.currentHoldings,
    });
    assertReplaceAllResultMatchesPreview(
      result,
      preview.dryRun.reconciliation.summary,
    );
  }
  return responsePayload;
}

export async function runScheduledTossAutoApply(
  options: { autoApplyEnabled: boolean; sessionDate?: string },
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
      quarantinedCount: 0,
      quarantinedTickers: [],
    };
  }

  const sessionDate = options.sessionDate ?? resolveKstSessionDate();
  const preview = await buildTossHoldingsSyncPreview(deps, {
    tickerDirectoryLookupFailureMode: "throw",
  });
  const quarantinedTickers = preview.dryRun.reconciliation.changes.delete.map(
    (row) => row.ticker,
  );
  const base = {
    mode: "auto-apply" as const,
    diffHash: preview.diffHash,
    applyBlocked: preview.dryRun.applyBlocked,
    summary: preview.dryRun.reconciliation.summary,
    changes: preview.dryRun.reconciliation.changes,
    blockedRows: preview.dryRun.blockedRows,
    targetRows: preview.dryRun.targetRows,
    quarantinedCount: 0,
    quarantinedTickers,
  };

  if (preview.dryRun.applyBlocked) {
    return { ...base, status: "blocked" };
  }
  if (
    preview.tossItems.length === 0 &&
    preview.hasCurrentHoldings &&
    preview.dryRun.reconciliation.summary.deleteCount > 0
  ) {
    return { ...base, status: "wipe_guard_blocked" };
  }
  if (preview.dryRun.reconciliation.summary.deleteCount > 0) {
    const result = await deps.applyScheduledTossQuarantine({
      targetRows: preview.dryRun.targetRows,
      quarantineTickers: quarantinedTickers,
      expectedCurrentHoldings: preview.currentHoldings,
      sessionDate,
      diffHash: preview.diffHash,
    });
    return {
      ...base,
      status: "applied",
      quarantinedCount: result.quarantinedCount,
      quarantinedTickers,
    };
  }
  if (!preview.hasChanges) {
    return { ...base, status: "unchanged" };
  }

  const applied = await applyTossHoldingsSyncPreview(preview, deps);
  return {
    ...applied,
    mode: "auto-apply",
    status: "applied",
    quarantinedCount: 0,
    quarantinedTickers: [],
  };
}
