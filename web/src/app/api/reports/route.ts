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
    const payload = await listReports({ type, q, limit, searchWindow });
    return NextResponse.json(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
