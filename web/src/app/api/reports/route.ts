import { NextRequest, NextResponse } from "next/server";

import { getSupabaseEnv } from "@/lib/env.server";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { filterAndSortReportKeys, toReportListItem } from "@/lib/report-key";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import {
  resolveReportKeysCacheTtlSeconds,
  resolveReportSearchConcurrency,
} from "@/lib/report-performance-policy";
import { extractReportTickers } from "@/lib/report-tickers";
import { reportListQuerySchema } from "@/lib/schemas";
import {
  downloadStorageJson,
  listAllStorageKeysCached,
  SupabaseApiError,
} from "@/lib/supabase-admin";
import type { ReportListItem } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function extractSummary(
  report: Record<string, unknown>,
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
  try {
    await requireAdminAuth(request);
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof AdminAuthError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status, headers: error.headers },
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
  const keysCacheTtlSeconds = resolveReportKeysCacheTtlSeconds(
    process.env.REPORT_KEYS_CACHE_TTL_SECONDS,
  );
  const searchConcurrency = resolveReportSearchConcurrency(
    process.env.REPORT_SEARCH_CONCURRENCY,
  );

  try {
    const env = getSupabaseEnv();
    const keys = await listAllStorageKeysCached(
      env.SUPABASE_REPORTS_BUCKET,
      keysCacheTtlSeconds,
    );
    const sorted = filterAndSortReportKeys(keys, type);

    if (!q) {
      return NextResponse.json({
        items: sorted.slice(0, limit).map((entry) => toReportListItem(entry)),
        total: sorted.length,
        searched: 0,
        searchWindow,
        truncated: false,
      });
    }

    const searchedCandidates = sorted.slice(0, searchWindow);
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

          const candidate = searchedCandidates[index];
          let report: Record<string, unknown>;
          try {
            report = await downloadStorageJson(
              env.SUPABASE_REPORTS_BUCKET,
              candidate.key,
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

          const tickers = extractReportTickers(report);
          if (!matchesTickerQuery(tickers, q)) {
            continue;
          }

          const generatedAt =
            typeof report.generated_at === "string"
              ? report.generated_at
              : undefined;

          matchedByIndex.set(
            index,
            toReportListItem(candidate, {
              generatedAt,
              summary: extractSummary(report),
              tickers,
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
      truncated: sorted.length > searchedCandidates.length,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
