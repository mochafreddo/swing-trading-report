export type Provider = "kis" | "pykrx";
export type ScanUniverse = "KR" | "US" | "both";

export type ReportType = "buy" | "sell" | "entry";

export interface ReportListItem {
  key: string;
  type: ReportType;
  reportDate: string;
  duplicateIndex: number;
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

export interface HoldingRecord {
  ticker: string;
  quantity: number;
  entry_price: number;
  entry_currency: string | null;
  entry_date: string | null;
  strategy: string | null;
  notes: string | null;
  tags: string[];
  stop_override: number | null;
  target_override: number | null;
  created_at: string;
  updated_at: string;
}

export type HoldingSnapshot = Omit<HoldingRecord, "created_at" | "updated_at">;

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
