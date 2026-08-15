import type {
  ReportListItem,
  ReportSearchWarning,
  ReportType,
  DecisionBoardJournalStatus,
  DecisionBoardRunKind,
} from "@/lib/types";

export type ReportsFilterType = "all" | ReportType;
export type ReportJson = Record<string, unknown>;

export interface ReportsInitialState {
  reportType: ReportsFilterType;
  runKind: DecisionBoardRunKind | null;
  query: string;
  appliedQuery: string;
  items: ReportListItem[];
  total: number | null;
  searched: number;
  truncated: boolean;
  searchWindow: number;
  warnings: ReportSearchWarning[];
  selectedKey: string | null;
  selectedBucketId: string | null;
  detail: ReportJson | null;
  detailKey: string | null;
  detailBucketId: string | null;
  showRaw: boolean;
  journalStatus: DecisionBoardJournalStatus;
}
