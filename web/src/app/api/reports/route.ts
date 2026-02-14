import { NextRequest, NextResponse } from "next/server";

import { getSupabaseEnv } from "@/lib/env.server";
import {
  filterAndSortReportKeys,
  toReportListItem
} from "@/lib/report-key";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import { extractReportTickers } from "@/lib/report-tickers";
import { reportListQuerySchema } from "@/lib/schemas";
import {
  downloadStorageJson,
  listAllStorageKeys,
  SupabaseApiError
} from "@/lib/supabase-admin";
import type { ReportListItem } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function extractSummary(
  report: Record<string, unknown>
): Record<string, unknown> | undefined {
  const payload = report.summary;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return undefined;
  }
  return payload as Record<string, unknown>;
}

function matchesTickerQuery(tickers: string[], query: string): boolean {
  const needle = query.toLowerCase();
  return tickers.some((ticker) => ticker.toLowerCase().includes(needle));
}

export async function GET(request: NextRequest) {
  const parsedQuery = reportListQuerySchema.safeParse({
    type: request.nextUrl.searchParams.get("type") ?? undefined,
    q: request.nextUrl.searchParams.get("q") ?? "",
    limit: request.nextUrl.searchParams.get("limit") ?? undefined
  });

  if (!parsedQuery.success) {
    return NextResponse.json(
      {
        error: "Invalid query parameters",
        details: parsedQuery.error.flatten()
      },
      { status: 400 }
    );
  }

  const { type, q, limit } = parsedQuery.data;
  const searchWindow = resolveReportSearchWindow(process.env.REPORT_SEARCH_WINDOW);

  try {
    const env = getSupabaseEnv();
    const keys = await listAllStorageKeys(env.SUPABASE_REPORTS_BUCKET);
    const sorted = filterAndSortReportKeys(keys, type);

    if (!q) {
      return NextResponse.json({
        items: sorted.slice(0, limit).map((entry) => toReportListItem(entry)),
        total: sorted.length,
        searched: 0,
        searchWindow,
        truncated: false
      });
    }

    const searchedCandidates = sorted.slice(0, searchWindow);
    const matchedItems: ReportListItem[] = [];

    for (const candidate of searchedCandidates) {
      let report: Record<string, unknown>;
      try {
        report = await downloadStorageJson(env.SUPABASE_REPORTS_BUCKET, candidate.key);
      } catch (error) {
        if (error instanceof SupabaseApiError && error.status === 404) {
          continue;
        }
        throw error;
      }

      const tickers = extractReportTickers(report);
      if (!matchesTickerQuery(tickers, q)) {
        continue;
      }

      const generatedAt =
        typeof report.generated_at === "string" ? report.generated_at : undefined;

      matchedItems.push(
        toReportListItem(candidate, {
          generatedAt,
          summary: extractSummary(report),
          tickers
        })
      );
    }

    return NextResponse.json({
      items: matchedItems.slice(0, limit),
      total: matchedItems.length,
      searched: searchedCandidates.length,
      searchWindow,
      truncated: sorted.length > searchedCandidates.length
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
