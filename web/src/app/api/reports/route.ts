import { NextRequest, NextResponse } from "next/server";

import { getSupabaseEnv } from "@/lib/env.server";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { resolveReportSearchConcurrency } from "@/lib/report-performance-policy";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import { extractReportTickers } from "@/lib/report-tickers";
import { reportListQuerySchema } from "@/lib/schemas";
import {
  downloadStorageJson,
  fetchReportIndexPage,
  SupabaseApiError,
  upsertReportIndexEntry,
} from "@/lib/supabase-admin";
import type { ReportListItem } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function matchesTickerQuery(
  tickers: string[] | undefined,
  query: string,
): boolean {
  if (!tickers || tickers.length === 0) {
    return false;
  }
  const needle = query.toLowerCase();
  return tickers.some((ticker) => ticker.toLowerCase().includes(needle));
}

function extractSummary(
  report: Record<string, unknown>,
): Record<string, unknown> | undefined {
  const payload = report.summary;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  return payload as Record<string, unknown>;
}

function toReportListItem(
  row: {
    report_key: string;
    report_type: "buy" | "sell";
    report_date: string;
    duplicate_index: number;
    generated_at: string | null;
    summary: Record<string, unknown> | null;
    tickers: string[];
    tickers_hydrated: boolean;
  },
  extras?: Pick<ReportListItem, "generatedAt" | "summary" | "tickers">,
): ReportListItem {
  return {
    key: row.report_key,
    type: row.report_type,
    reportDate: row.report_date,
    duplicateIndex: row.duplicate_index,
    ...extras,
  };
}

export async function GET(request: NextRequest) {
  try {
    await requireAdminAuth(request);
    assertSameOrigin(request);
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof AdminAuthError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status, headers: error.headers },
      );
    }
    if (error instanceof SameOriginError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof LocalRequestGuardError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  const parsedQuery = reportListQuerySchema.safeParse({
    type: request.nextUrl.searchParams.get("type") ?? undefined,
    q: request.nextUrl.searchParams.get("q") ?? "",
    limit: request.nextUrl.searchParams.get("limit") ?? undefined,
  });

  if (!parsedQuery.success) {
    return NextResponse.json(
      {
        error: "Invalid query parameters",
        details: parsedQuery.error.flatten(),
      },
      { status: 400 },
    );
  }

  const { type, q, limit } = parsedQuery.data;
  const searchWindow = resolveReportSearchWindow(
    process.env.REPORT_SEARCH_WINDOW,
  );
  const searchConcurrency = resolveReportSearchConcurrency(
    process.env.REPORT_SEARCH_CONCURRENCY,
  );

  try {
    if (!q) {
      const { items, total } = await fetchReportIndexPage({
        type,
        limit,
      });
      return NextResponse.json({
        items: items.map((row) => toReportListItem(row)),
        total,
        searched: 0,
        searchWindow,
        truncated: false,
      });
    }

    const { items: searchedCandidates, total } = await fetchReportIndexPage({
      type,
      limit: searchWindow,
    });
    const env = getSupabaseEnv();
    const matchedByIndex = new Map<number, ReportListItem>();
    let nextIndex = 0;
    let workerError: unknown;
    let shouldStop = false;

    const workerCount = Math.min(searchConcurrency, searchedCandidates.length);
    await Promise.all(
      Array.from({ length: workerCount }, async () => {
        while (true) {
          if (shouldStop) {
            return;
          }

          const index = nextIndex;
          nextIndex += 1;
          if (index >= searchedCandidates.length) {
            return;
          }

          const row = searchedCandidates[index];
          let tickers = row.tickers;
          let generatedAt = row.generated_at ?? undefined;
          let summary = row.summary ?? undefined;

          if (!row.tickers_hydrated) {
            let report: Record<string, unknown>;
            try {
              report = await downloadStorageJson(
                env.SUPABASE_REPORTS_BUCKET,
                row.report_key,
              );
            } catch (error) {
              if (error instanceof SupabaseApiError && error.status === 404) {
                continue;
              }
              if (!workerError) {
                workerError = error;
              }
              shouldStop = true;
              return;
            }

            tickers = extractReportTickers(report);
            generatedAt =
              generatedAt ??
              (typeof report.generated_at === "string"
                ? report.generated_at
                : undefined);
            summary = summary ?? extractSummary(report);

            try {
              await upsertReportIndexEntry({
                reportKey: row.report_key,
                reportType: row.report_type,
                reportDate: row.report_date,
                duplicateIndex: row.duplicate_index,
                generatedAt,
                summary,
                tickers,
                tickersHydrated: true,
              });
            } catch (error) {
              const message =
                error instanceof Error ? error.message : "Unknown error";
              console.warn(
                `Report index hydration failed for '${row.report_key}': ${message}`,
              );
            }
          }

          if (!matchesTickerQuery(tickers, q)) {
            continue;
          }

          matchedByIndex.set(
            index,
            toReportListItem(row, {
              generatedAt,
              summary,
              tickers: tickers.length > 0 ? tickers : undefined,
            }),
          );
        }
      }),
    );

    if (workerError) {
      throw workerError;
    }

    const matchedItems: ReportListItem[] = [];
    for (let index = 0; index < searchedCandidates.length; index += 1) {
      const item = matchedByIndex.get(index);
      if (item) {
        matchedItems.push(item);
      }
    }

    return NextResponse.json({
      items: matchedItems.slice(0, limit),
      total: matchedItems.length,
      searched: searchedCandidates.length,
      searchWindow,
      truncated: total > searchedCandidates.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
