import { NextRequest, NextResponse } from "next/server";

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
import { tickerSearchQuerySchema } from "@/lib/schemas";
import { searchTickerDirectory } from "@/lib/ticker-directory";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/tickers/search";
const METHOD = "GET";
const OPERATION = "search_tickers";

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

  const parsedQuery = tickerSearchQuerySchema.safeParse({
    q: request.nextUrl.searchParams.get("q") ?? "",
    limit: request.nextUrl.searchParams.get("limit") ?? undefined,
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
      NextResponse.json(
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
    const payload = await searchTickerDirectory({
      q: parsedQuery.data.q,
      limit: parsedQuery.data.limit,
    });
    const response = NextResponse.json(payload);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "success",
      status_code: 200,
      dependency: "ticker_directory",
      duration_ms: elapsedMs(startedAtMs),
      query_length: parsedQuery.data.q.length,
      limit: parsedQuery.data.limit,
      item_count: payload.results.length,
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
      dependency: "ticker_directory",
      duration_ms: elapsedMs(startedAtMs),
      retryable: false,
      query_length: parsedQuery.data.q.length,
      limit: parsedQuery.data.limit,
    });
    return withApiRequestId(
      NextResponse.json({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}
