import { NextRequest } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
} from "@/lib/api-request-log";
import { toErrorMessage } from "@/lib/error-utils";
import { listReports } from "@/lib/reports-data";
import { jsonWithNoStore } from "@/lib/reports-response";
import { resolveReportSearchWindow } from "@/lib/report-search-policy";
import { reportListQuerySchema } from "@/lib/schemas";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/reports";
const METHOD = "GET";
const OPERATION = "list_reports";

export async function GET(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  const guardError = await enforceAdminApiGuard(request, jsonWithNoStore);
  if (guardError) {
    logApiWarn({
      event: "web_api_request_rejected",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: guardError.status,
      reason: "admin_guard",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(guardError, requestId);
  }

  const parsedQuery = reportListQuerySchema.safeParse({
    type: request.nextUrl.searchParams.get("type") ?? undefined,
    q: request.nextUrl.searchParams.get("q") ?? "",
    limit: request.nextUrl.searchParams.get("limit") ?? undefined,
    refresh: request.nextUrl.searchParams.get("refresh") ?? undefined,
  });

  if (!parsedQuery.success) {
    logApiWarn({
      event: "web_api_request_rejected",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: 400,
      reason: "invalid_query",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(
      jsonWithNoStore(
        {
          error: "Invalid query parameters",
          details: parsedQuery.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
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
    const response = jsonWithNoStore(payload);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "success",
      status_code: 200,
      dependency: "supabase",
      duration_ms: elapsedMs(startedAtMs),
      report_type: type,
      limit,
      search_window: searchWindow,
      item_count: payload.items.length,
      warning_count: payload.warnings.length,
      refresh,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: 500,
      dependency: "supabase",
      duration_ms: elapsedMs(startedAtMs),
      retryable: true,
      report_type: type,
      limit,
      search_window: searchWindow,
      refresh,
    });
    return withApiRequestId(
      jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}
