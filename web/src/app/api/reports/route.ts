import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { listReports } from "@/lib/reports-data";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import { reportListQuerySchema } from "@/lib/schemas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const REPORTS_CACHE_CONTROL = "private, no-store, max-age=0, must-revalidate";

function jsonWithNoStore(
  payload: unknown,
  init?: {
    status?: number;
    headers?: HeadersInit;
  },
): NextResponse {
  const headers = new Headers(init?.headers);
  headers.set("Cache-Control", REPORTS_CACHE_CONTROL);
  return NextResponse.json(payload, {
    status: init?.status,
    headers,
  });
}

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request, jsonWithNoStore);
  if (guardError) {
    return guardError;
  }

  const parsedQuery = reportListQuerySchema.safeParse({
    type: request.nextUrl.searchParams.get("type") ?? undefined,
    q: request.nextUrl.searchParams.get("q") ?? "",
    limit: request.nextUrl.searchParams.get("limit") ?? undefined,
    refresh: request.nextUrl.searchParams.get("refresh") ?? undefined,
  });

  if (!parsedQuery.success) {
    return jsonWithNoStore(
      {
        error: "Invalid query parameters",
        details: parsedQuery.error.flatten(),
      },
      { status: 400 },
    );
  }

  const { type, q, limit, refresh } = parsedQuery.data;
  const searchWindow = resolveReportSearchWindow(
    process.env.REPORT_SEARCH_WINDOW,
  );

  try {
    const payload = await listReports({
      type,
      q,
      limit,
      searchWindow,
      refresh,
    });
    return jsonWithNoStore(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return jsonWithNoStore({ error: message }, { status: 500 });
  }
}
