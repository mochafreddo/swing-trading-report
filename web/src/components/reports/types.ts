import type {
  ReportListItem,
  ReportSearchWarning,
  ReportType,
} from "@/lib/types";

export type ReportsFilterType = "all" | ReportType;
export type ReportJson = Record<string, unknown>;

export interface ReportsInitialState {
  reportType: ReportsFilterType;
  query: string;
  appliedQuery: string;
  items: ReportListItem[];
  total: number | null;
  searched: number;
  truncated: boolean;
  searchWindow: number;
  warnings: ReportSearchWarning[];
  selectedKey: string | null;
  detail: ReportJson | null;
  detailKey: string | null;
  showRaw: boolean;
}
