import "server-only";

import {
  applyScheduledTossQuarantine,
  fetchAllHoldings,
  replaceAllHoldings,
} from "@/lib/supabase-admin";
import { getSupabaseEnv } from "@/lib/env.server";
import {
  buildAuthHeaders,
  fetchSupabase,
  parseError,
  SupabaseApiError,
} from "@/lib/supabase/admin-client";
import {
  listTickerDirectoryExactBaseCandidates,
  type TickerDirectoryExactBaseResponse,
} from "@/lib/ticker-directory";
import { fetchDefaultTossHoldingsItems } from "@/lib/toss/client";
import {
  buildBrokerHoldingsDigestV0,
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
  HoldingSnapshot,
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
  expectedPostStateDigest?: string;
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
  holdingsDigest: string;
  revision: number;
  sealedAt: string;
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
  if (!/^sha256:[0-9a-f]{64}$/.test(result.expectedPostStateDigest ?? "")) {
    throw new Error(
      "Scheduled Toss sync expected post-state digest is missing",
    );
  }
  const now = options.now ?? new Date();
  const sessionDate = options.sessionDate ?? resolveKstSessionDate(now);
  const stateKey = `toss-sync:success:MIXED:${sessionDate}`;
  const expiresAt = new Date(now.getTime() + 36 * 60 * 60 * 1000).toISOString();
  const markerPayload = {
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
  };
  const env = getSupabaseEnv();
  const response = await fetchSupabase(
    `${env.SUPABASE_URL}/rest/v1/rpc/seal_broker_snapshot_v0`,
    {
      method: "POST",
      headers: buildAuthHeaders({
        "Content-Type": "application/json",
        Accept: "application/json",
      }),
      body: JSON.stringify({
        p_state_key: stateKey,
        p_session_date: sessionDate,
        p_status: result.status,
        p_expires_at: expiresAt,
        p_marker_payload: markerPayload,
        p_expected_post_state_digest: result.expectedPostStateDigest,
      }),
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new SupabaseApiError(
      `Failed to seal BrokerSnapshotV0: ${await parseError(response)}`,
      response.status,
    );
  }

  const payload = (await response.json()) as unknown;
  if (!Array.isArray(payload) || payload.length !== 1) {
    throw new SupabaseApiError(
      "seal_broker_snapshot_v0 returned ambiguous cardinality",
      500,
    );
  }
  const sealed = asRecord(payload[0]);
  const holdingsDigest = sealed?.holdings_digest;
  const revision = sealed?.revision;
  const sealedAt = sealed?.sealed_at;
  if (
    sealed?.state_key !== stateKey ||
    sealed?.session_date !== sessionDate ||
    sealed?.status !== result.status ||
    typeof holdingsDigest !== "string" ||
    !/^sha256:[0-9a-f]{64}$/.test(holdingsDigest) ||
    typeof revision !== "number" ||
    !Number.isSafeInteger(revision) ||
    revision <= 0 ||
    typeof sealedAt !== "string" ||
    !Number.isFinite(Date.parse(sealedAt))
  ) {
    throw new SupabaseApiError(
      "seal_broker_snapshot_v0 returned an invalid result",
      500,
    );
  }

  return {
    stateKey,
    sessionDate,
    holdingsDigest,
    revision,
    sealedAt: new Date(sealedAt).toISOString(),
  };
}

function confirmedPostStateRow(row: HoldingReplaceSnapshot): HoldingSnapshot {
  return {
    ...row,
    entry_pattern: row.entry_pattern ?? null,
    broker_state: "confirmed",
    broker_missing_first_seen_date: null,
    broker_missing_last_seen_date: null,
    broker_missing_count: 0,
    broker_missing_diff_hash: null,
  };
}

function quarantinedPostStateRow(
  row: HoldingRecord,
  sessionDate: string,
  diffHash: string,
): HoldingSnapshot {
  const alreadyMissing = row.broker_state === "not_seen_in_toss";
  const alreadyCountedForSession =
    alreadyMissing && row.broker_missing_last_seen_date === sessionDate;
  return {
    ticker: row.ticker,
    quantity: row.quantity,
    entry_price: row.entry_price,
    entry_currency: row.entry_currency,
    entry_date: row.entry_date,
    strategy: row.strategy,
    entry_pattern: row.entry_pattern,
    notes: row.notes,
    tags: [...row.tags],
    stop_override: row.stop_override,
    target_override: row.target_override,
    broker_state: "not_seen_in_toss",
    broker_missing_first_seen_date: alreadyMissing
      ? (row.broker_missing_first_seen_date ?? sessionDate)
      : sessionDate,
    broker_missing_last_seen_date: sessionDate,
    broker_missing_count: alreadyCountedForSession
      ? (row.broker_missing_count ?? 0)
      : alreadyMissing
        ? (row.broker_missing_count ?? 0) + 1
        : 1,
    broker_missing_diff_hash: diffHash,
  };
}

function buildExpectedScheduledPostStateDigest(
  preview: TossHoldingsSyncPreview,
  sessionDate: string,
  quarantineTickers: readonly string[],
): string {
  const quarantineSet = new Set(quarantineTickers);
  const rows = preview.dryRun.targetRows.map(confirmedPostStateRow);
  for (const current of preview.currentHoldings) {
    if (quarantineSet.has(current.ticker)) {
      rows.push(
        quarantinedPostStateRow(current, sessionDate, preview.diffHash),
      );
    }
  }
  return buildBrokerHoldingsDigestV0(rows);
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
  const expectedPostStateDigest = buildExpectedScheduledPostStateDigest(
    preview,
    sessionDate,
    quarantinedTickers,
  );
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
      expectedPostStateDigest,
    };
  }
  if (!preview.hasChanges) {
    return { ...base, status: "unchanged", expectedPostStateDigest };
  }

  const applied = await applyTossHoldingsSyncPreview(preview, deps);
  return {
    ...applied,
    mode: "auto-apply",
    status: "applied",
    quarantinedCount: 0,
    quarantinedTickers: [],
    expectedPostStateDigest,
  };
}
