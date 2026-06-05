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
import { InvalidReportKeyError, readReportDetail } from "@/lib/reports-data";
import { jsonWithNoStore } from "@/lib/reports-response";
import { reportDetailQuerySchema } from "@/lib/schemas";
import { SupabaseApiError } from "@/lib/supabase-admin";

export const runtime = "nodejs";

const ROUTE = "/api/reports/detail";
const METHOD = "GET";
const OPERATION = "read_report_detail";

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

  const query = reportDetailQuerySchema.safeParse({
    key: request.nextUrl.searchParams.get("key") ?? undefined,
    refresh: request.nextUrl.searchParams.get("refresh") ?? undefined,
  });

  if (!query.success) {
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
          details: query.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const payload = await readReportDetail(query.data.key, {
      refresh: query.data.refresh,
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
      report_key: query.data.key,
      refresh: query.data.refresh,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    if (error instanceof InvalidReportKeyError) {
      logApiWarn({
        event: "web_api_request_rejected",
        request_id: requestId,
        route: ROUTE,
        method: METHOD,
        operation: OPERATION,
        status: "failed",
        status_code: error.status,
        reason: "invalid_report_key",
        report_key: query.data.key,
        duration_ms: elapsedMs(startedAtMs),
      });
      return withApiRequestId(
        jsonWithNoStore({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    if (error instanceof SupabaseApiError && error.status === 404) {
      logApiWarn({
        event: "web_api_request_failed",
        request_id: requestId,
        route: ROUTE,
        method: METHOD,
        operation: OPERATION,
        status: "failed",
        status_code: 404,
        dependency: "supabase",
        reason: "not_found",
        report_key: query.data.key,
        duration_ms: elapsedMs(startedAtMs),
      });
      return withApiRequestId(
        jsonWithNoStore({ error: "Report not found" }, { status: 404 }),
        requestId,
      );
    }

    const statusCode = error instanceof SupabaseApiError ? error.status : 500;
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: statusCode,
      dependency: error instanceof SupabaseApiError ? "supabase" : undefined,
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      report_key: query.data.key,
      refresh: query.data.refresh,
    });
    return withApiRequestId(
      jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}
