import { NextRequest } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { toErrorMessage } from "@/lib/error-utils";
import { listReports } from "@/lib/reports-data";
import { jsonWithNoStore } from "@/lib/reports-response";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import { reportListQuerySchema } from "@/lib/schemas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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
    return jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 });
  }
}
