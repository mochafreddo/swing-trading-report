import { parseReportStorageKey } from "@/lib/report-key";
import type { DecisionBoardRunKind, ReportType } from "@/lib/types";

interface ResolveSelectedKeyFromUrlInput {
  previousSelectedKey: string | null;
  nextKeyRaw: string | null;
  reportType?: "all" | ReportType;
  runKind?: DecisionBoardRunKind | null;
  availableKeys?: readonly string[];
  preserveSelectionWhenKeyMissing?: boolean;
}

export function resolveSelectedKeyFromUrl({
  previousSelectedKey,
  nextKeyRaw,
  reportType,
  runKind,
  preserveSelectionWhenKeyMissing = false,
}: ResolveSelectedKeyFromUrlInput): string | null {
  const nextKey = nextKeyRaw?.trim() || null;
  if (!nextKey) {
    return preserveSelectionWhenKeyMissing ? previousSelectedKey : null;
  }
  if (reportType === "decision-board") {
    const parsedKey = parseReportStorageKey(nextKey);
    if (parsedKey?.type !== "decision-board" || parsedKey.runKind !== runKind) {
      return null;
    }
  }
  return previousSelectedKey === nextKey ? previousSelectedKey : nextKey;
}
