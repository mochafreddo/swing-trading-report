import { Suspense } from "react";

import { ReportsClient } from "@/components/reports-client";
import { parseReportType } from "@/components/reports/helpers";
import type { ReportsInitialState } from "@/components/reports/types";
import { hasValidAdminSession } from "@/lib/admin-prefetch";
import { listReports, readReportDetail } from "@/lib/reports-data";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";

const REPORT_PAGE_LIMIT = 30;

type SearchParamsValue = string | string[] | undefined;
type SearchParamsRecord = Record<string, SearchParamsValue>;

function readFirstValue(value: SearchParamsValue): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return null;
}

interface ReportsPageProps {
  searchParams?: SearchParamsRecord | Promise<SearchParamsRecord>;
}

export async function loadReportsInitialState(
  searchParams?: SearchParamsRecord | Promise<SearchParamsRecord>,
): Promise<ReportsInitialState | undefined> {
  const params = await Promise.resolve(searchParams ?? {});
  const reportType = parseReportType(readFirstValue(params.type));
  const query = readFirstValue(params.q) ?? "";
  const appliedQuery = query.trim();
  const requestedKey = (readFirstValue(params.key) ?? "").trim() || null;
  const showRaw = readFirstValue(params.raw) === "1";
  const searchWindow = resolveReportSearchWindow(
    process.env.REPORT_SEARCH_WINDOW,
  );

  if (await hasValidAdminSession()) {
    const list = await listReports({
      type: reportType,
      q: appliedQuery,
      limit: REPORT_PAGE_LIMIT,
      searchWindow,
    });
    const selectedKey = requestedKey ?? list.items[0]?.key ?? null;

    let detail: ReportsInitialState["detail"] = null;
    let detailKey: string | null = null;
    if (selectedKey) {
      try {
        const detailPayload = await readReportDetail(selectedKey);
        detail = detailPayload.report;
        detailKey = detailPayload.key;
      } catch {
        // Leave detail empty so the client can retry without failing the page.
      }
    }

    return {
      reportType,
      query,
      appliedQuery,
      items: list.items,
      total: list.total,
      searched: list.searched,
      truncated: list.truncated,
      searchWindow: list.searchWindow,
      warnings: list.warnings,
      selectedKey,
      detail,
      detailKey,
      showRaw,
    };
  }

  return undefined;
}

function ReportsPageFallback() {
  return (
    <section className="panel">
      <p className="subtle">Loading reports...</p>
    </section>
  );
}

async function ReportsPageContent({ searchParams }: ReportsPageProps) {
  const initialState = await loadReportsInitialState(searchParams);
  return <ReportsClient initialState={initialState} />;
}

export default function ReportsPage({ searchParams }: ReportsPageProps) {
  return (
    <Suspense fallback={<ReportsPageFallback />}>
      <ReportsPageContent searchParams={searchParams} />
    </Suspense>
  );
}
