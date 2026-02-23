import { NextRequest, NextResponse } from "next/server";

import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import { reportListQuerySchema } from "@/lib/schemas";
import {
  fetchReportIndexPage,
  type ReportIndexCursor,
} from "@/lib/supabase-admin";
import type { ReportListItem, ReportSearchWarning } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const REPORT_SEARCH_PAGE_SIZE = 100;

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

function buildPartialFailureWarning(error: unknown): ReportSearchWarning {
  const message = error instanceof Error ? error.message : "Unknown error";
  return {
    code: "partial_failure",
    message: `검색 중 일부 인덱스 페이지를 불러오지 못했습니다: ${message}`,
  };
}

function buildIndexIncompleteWarning(count: number): ReportSearchWarning {
  return {
    code: "index_incomplete",
    message: `인덱스 미완료 리포트 ${count}건은 검색 결과에서 제외되었습니다.`,
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
        warnings: [],
      });
    }

    const matchedItems: ReportListItem[] = [];
    const warnings: ReportSearchWarning[] = [];
    let searched = 0;
    let cursor: ReportIndexCursor | undefined;
    let hasMoreCandidates = false;
    let partialFailure = false;
    let incompleteRows = 0;

    while (searched < searchWindow) {
      const pageSize = Math.min(
        REPORT_SEARCH_PAGE_SIZE,
        searchWindow - searched,
      );
      if (pageSize <= 0) {
        break;
      }

      let page: Awaited<ReturnType<typeof fetchReportIndexPage>>;
      try {
        page = await fetchReportIndexPage({
          type,
          limit: pageSize,
          cursor,
          includeTotal: false,
          lookahead: true,
        });
      } catch (error) {
        if (searched === 0) {
          throw error;
        }
        warnings.push(buildPartialFailureWarning(error));
        partialFailure = true;
        break;
      }

      if (page.fetchedCount <= 0) {
        break;
      }

      for (const row of page.items) {
        if (!row.tickers_hydrated) {
          incompleteRows += 1;
          continue;
        }

        if (!matchesTickerQuery(row.tickers, q)) {
          continue;
        }

        matchedItems.push(
          toReportListItem(row, {
            generatedAt: row.generated_at ?? undefined,
            summary: row.summary ?? undefined,
            tickers: row.tickers.length > 0 ? row.tickers : undefined,
          }),
        );
      }

      searched += page.fetchedCount;
      hasMoreCandidates = page.hasMore;
      if (!page.hasMore) {
        break;
      }
      if (!page.nextCursor) {
        warnings.push(
          buildPartialFailureWarning(
            new Error("검색 커서를 계산하지 못해 검색을 중단했습니다."),
          ),
        );
        partialFailure = true;
        break;
      }
      cursor = page.nextCursor;
    }

    if (incompleteRows > 0) {
      warnings.push(buildIndexIncompleteWarning(incompleteRows));
    }

    return NextResponse.json({
      items: matchedItems.slice(0, limit),
      total: matchedItems.length,
      searched,
      searchWindow,
      truncated:
        partialFailure || (searched >= searchWindow && hasMoreCandidates),
      warnings,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
