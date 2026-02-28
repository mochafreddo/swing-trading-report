import { NextRequest, NextResponse } from "next/server";

import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { listReports } from "@/lib/reports-data";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
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
  try {
    await requireAdminAuth(request);
    assertSameOrigin(request);
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof AdminAuthError) {
      return jsonWithNoStore(
        { error: error.message },
        { status: error.status, headers: error.headers },
      );
    }
    if (error instanceof SameOriginError) {
      return jsonWithNoStore(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof LocalRequestGuardError) {
      return jsonWithNoStore(
        { error: error.message },
        { status: error.status },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return jsonWithNoStore({ error: message }, { status: 500 });
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
