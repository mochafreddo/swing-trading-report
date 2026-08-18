import "server-only";

import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import {
  applyScheduledTossQuarantine,
  captureBrokerHoldingsDigest,
  fetchAllHoldings,
  fetchBrokerHoldingsState,
  replaceAllHoldings,
  replaceAllHoldingsAndCaptureBrokerDigest,
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
  buildTossHoldingsDiffHash,
  buildTossHoldingsDryRun,
  type TossHoldingsDryRunResult,
  type TossHoldingsItem,
  type TossTickerDirectoryCandidate,
} from "@/lib/toss/holdings-sync";
import { loadReviewedTossTickerMappingsFromEnv } from "@/lib/toss/ticker-mapping-registry";
import qaTossHoldingsFixture from "../../../fixtures/toss-holdings.qa.json";
import type {
  HoldingRecord,
  HoldingReplaceSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";
import type {
  BrokerHoldingsMutationResult,
  BrokerHoldingsState,
  ReplaceAllHoldingsResult,
} from "@/lib/supabase/holdings";

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
  initialHoldingsDigest: string | null;
}

export interface TossHoldingsSyncPreviewOptions {
  tickerDirectoryLookupFailureMode?: "ignore" | "throw";
  brokerSnapshotBoundary?: boolean;
}

export interface TossHoldingsSyncDependencies {
  fetchAllHoldings: () => Promise<HoldingRecord[]>;
  fetchBrokerHoldingsState: () => Promise<BrokerHoldingsState>;
  fetchTossHoldingsItems: () => Promise<TossHoldingsItem[]>;
  listTickerDirectoryExactBaseCandidates: (
    symbols: readonly string[],
  ) => Promise<TickerDirectoryExactBaseResponse>;
  listReviewedTickerMappings: (
    symbols: readonly string[],
  ) => Promise<TossTickerDirectoryCandidate[]>;
  replaceAllHoldings: (
    rows: HoldingReplaceSnapshot[],
    options?: { expectedCurrentHoldings?: readonly HoldingRecord[] },
  ) => Promise<ReplaceAllHoldingsResult>;
  replaceAllHoldingsAndCaptureBrokerDigest: (
    rows: HoldingReplaceSnapshot[],
    options?: { expectedCurrentHoldings?: readonly HoldingRecord[] },
  ) => Promise<BrokerHoldingsMutationResult>;
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
    postStateDigest: string;
  }>;
  captureBrokerHoldingsDigest: (
    expectedPreStateDigest: string,
  ) => Promise<string>;
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
  fetchBrokerHoldingsState,
  fetchTossHoldingsItems: fetchDefaultTossHoldingsItems,
  listTickerDirectoryExactBaseCandidates,
  listReviewedTickerMappings: async (symbols) =>
    loadReviewedTossTickerMappingsFromEnv(symbols),
  replaceAllHoldings,
  replaceAllHoldingsAndCaptureBrokerDigest,
  applyScheduledTossQuarantine,
  captureBrokerHoldingsDigest,
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
const EXPLICIT_US_SUFFIX_PATTERN = /^(.+)\.(NAS|NYS|AMS)$/;

function normalizeUsBaseSymbol(value: string): string {
  const normalized = normalizeHoldingTickerForMutation(`${value.trim()}.NAS`);
  return EXPLICIT_US_SUFFIX_PATTERN.exec(normalized)?.[1] ?? "";
}

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

async function fetchTossTickerDirectoryCandidates(
  items: readonly TossHoldingsItem[],
  deps: Pick<
    TossHoldingsSyncDependencies,
    "listTickerDirectoryExactBaseCandidates" | "listReviewedTickerMappings"
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

  let directoryCandidates: TossTickerDirectoryCandidate[] = [];
  try {
    const result = await deps.listTickerDirectoryExactBaseCandidates(usSymbols);
    directoryCandidates = result.candidates.map((row) => ({
      ticker: row.ticker,
    }));
  } catch (error) {
    if (options.tickerDirectoryLookupFailureMode === "throw") {
      throw error;
    }
  }

  const directoryBases = new Set(
    directoryCandidates
      .map(
        (candidate) => EXPLICIT_US_SUFFIX_PATTERN.exec(candidate.ticker)?.[1],
      )
      .filter((base): base is string => base !== undefined),
  );
  const unresolvedSymbols = usSymbols.filter(
    (symbol) => !directoryBases.has(normalizeUsBaseSymbol(symbol)),
  );
  const reviewedCandidates =
    unresolvedSymbols.length > 0
      ? await deps.listReviewedTickerMappings(unresolvedSymbols)
      : [];
  return [...directoryCandidates, ...reviewedCandidates];
}

export async function buildTossHoldingsSyncPreview(
  deps: TossHoldingsSyncDependencies = defaultTossHoldingsSyncDependencies,
  options: TossHoldingsSyncPreviewOptions = {},
): Promise<TossHoldingsSyncPreview> {
  const [holdingsState, tossItems] = await Promise.all([
    options.brokerSnapshotBoundary
      ? deps.fetchBrokerHoldingsState()
      : deps.fetchAllHoldings().then((holdings) => ({
          holdings,
          holdingsDigest: null,
        })),
    deps.fetchTossHoldingsItems(),
  ]);
  const currentHoldings = holdingsState.holdings;
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
    initialHoldingsDigest: holdingsState.holdingsDigest,
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
  options: { autoApplyEnabled: boolean; sessionDate?: string; now?: Date },
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

  const currentSessionDate = resolveKstSessionDate(options.now);
  const sessionDate = options.sessionDate ?? currentSessionDate;
  if (sessionDate > currentSessionDate) {
    throw new Error("Scheduled Toss sync cannot use a future KST session");
  }
  const preview = await buildTossHoldingsSyncPreview(deps, {
    tickerDirectoryLookupFailureMode: "throw",
    brokerSnapshotBoundary: true,
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
      expectedPostStateDigest: result.postStateDigest,
    };
  }
  if (!preview.hasChanges) {
    if (!preview.initialHoldingsDigest) {
      throw new Error("Scheduled Toss sync initial DB digest is missing");
    }
    const expectedPostStateDigest = await deps.captureBrokerHoldingsDigest(
      preview.initialHoldingsDigest,
    );
    return { ...base, status: "unchanged", expectedPostStateDigest };
  }

  const applied = await deps.replaceAllHoldingsAndCaptureBrokerDigest(
    preview.dryRun.targetRows,
    { expectedCurrentHoldings: preview.currentHoldings },
  );
  assertReplaceAllResultMatchesPreview(
    applied,
    preview.dryRun.reconciliation.summary,
  );
  return {
    ...preview.payload,
    mode: "auto-apply" as const,
    status: "applied",
    quarantinedCount: 0,
    quarantinedTickers: [],
    expectedPostStateDigest: applied.postStateDigest,
  };
}
