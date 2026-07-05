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
import { jsonWithNoStore } from "@/lib/reports-response";
import { recentBuyCandidatesQuerySchema } from "@/lib/schemas";
import { listRecentBuyCandidates } from "@/lib/ticker-directory";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/tickers/recent-candidates";
const METHOD = "GET";
const OPERATION = "list_recent_buy_candidates";

export async function GET(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  const guardError = await enforceAdminApiGuard(request);
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

  const parsedQuery = recentBuyCandidatesQuerySchema.safeParse({
    limitReports: request.nextUrl.searchParams.get("limitReports") ?? undefined,
    limitCandidates:
      request.nextUrl.searchParams.get("limitCandidates") ?? undefined,
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

  try {
    const payload = await listRecentBuyCandidates({
      limitReports: parsedQuery.data.limitReports,
      limitCandidates: parsedQuery.data.limitCandidates,
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
      dependency: "reports",
      duration_ms: elapsedMs(startedAtMs),
      limit_reports: parsedQuery.data.limitReports,
      limit_candidates: parsedQuery.data.limitCandidates,
      item_count: payload.candidates.length,
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
      dependency: "reports",
      duration_ms: elapsedMs(startedAtMs),
      retryable: false,
      limit_reports: parsedQuery.data.limitReports,
      limit_candidates: parsedQuery.data.limitCandidates,
    });
    return withApiRequestId(
      jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}
