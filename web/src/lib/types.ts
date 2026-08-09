export type Provider = "kis" | "pykrx";
export type ScanUniverse = "KR" | "US" | "both";

export const REPORT_TYPES = [
  "buy",
  "sell",
  "entry",
  "ai-brief",
  "ai-brief-skip",
  "sell-ai-brief",
  "decision-board",
] as const;
export const REPORT_TYPE_PATTERN = REPORT_TYPES.filter(
  (type) => type !== "decision-board",
).join("|");
export type ReportType = (typeof REPORT_TYPES)[number];
export type DecisionBoardRunKind = "ENTRY" | "HOLDING";

export function isReportType(value: unknown): value is ReportType {
  return (
    typeof value === "string" &&
    (REPORT_TYPES as readonly string[]).includes(value)
  );
}

export interface ReportListItem {
  key: string;
  bucketId: string;
  type: ReportType;
  reportDate: string;
  duplicateIndex: number;
  runKind?: DecisionBoardRunKind;
  generatedAt?: string;
  summary?: Record<string, unknown>;
  tickers?: string[];
}

export interface ReportSearchWarning {
  code: "index_incomplete" | "partial_failure";
  message: string;
}

export interface ReportsListResponse {
  items: ReportListItem[];
  total: number | null;
  searched: number;
  searchWindow: number;
  truncated: boolean;
  warnings: ReportSearchWarning[];
}

export type HoldingBrokerState = "confirmed" | "not_seen_in_toss";

export interface HoldingBrokerStateSnapshot {
  broker_state?: HoldingBrokerState | null;
  broker_missing_first_seen_date?: string | null;
  broker_missing_last_seen_date?: string | null;
  broker_missing_count?: number | null;
  broker_missing_diff_hash?: string | null;
}

export interface HoldingRecord extends HoldingBrokerStateSnapshot {
  ticker: string;
  quantity: number;
  entry_price: number;
  entry_currency: string | null;
  entry_date: string | null;
  strategy: string | null;
  entry_pattern: string | null;
  notes: string | null;
  tags: string[];
  stop_override: number | null;
  target_override: number | null;
  created_at: string;
  updated_at: string;
}

export type HoldingSnapshot = Omit<HoldingRecord, "created_at" | "updated_at">;

export type HoldingReplaceSnapshot = Omit<HoldingSnapshot, "entry_pattern"> & {
  entry_pattern?: string | null;
};

export interface HoldingCursor {
  updated_at: string;
  ticker: string;
}

export interface HoldingsListResponse {
  items: HoldingRecord[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface HoldingMutationInput {
  ticker?: string;
  quantity?: number;
  entry_price?: number;
  entry_currency?: string | null;
  entry_date?: string | null;
  strategy?: string | null;
  entry_pattern?: string | null;
  notes?: string | null;
  tags?: string[];
  stop_override?: number | null;
  target_override?: number | null;
}

export interface HoldingsYamlImportSummary {
  incomingCount: number;
  createCount: number;
  updateCount: number;
  deleteCount: number;
  unchangedCount: number;
  createTickers: string[];
  updateTickers: string[];
  deleteTickers: string[];
}

export interface HoldingsYamlImportResponse {
  mode: "dry-run" | "apply";
  summary: HoldingsYamlImportSummary;
}

export type RunWorkflow = "scan" | "sell";

export type WorkflowDispatchInput =
  | {
      workflow: "scan";
      provider: "kis";
      universe: ScanUniverse;
    }
  | {
      workflow: "scan";
      provider: "pykrx";
      universe: "KR";
    }
  | {
      workflow: "sell";
      provider: Provider;
    };

export interface WorkflowDispatchResult {
  dispatched: boolean;
  workflow: RunWorkflow;
  workflowFile: "scan.yml" | "sell.yml";
  workflowUrl: string;
  actionsUrl: string;
  ref: string;
}
