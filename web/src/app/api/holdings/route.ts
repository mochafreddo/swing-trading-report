import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
  type ApiLogFields,
} from "@/lib/api-request-log";
import {
  decodeHoldingCursor,
  HoldingCursorError,
} from "@/lib/holdings-pagination";
import { parseJsonBody } from "@/lib/parse-json-body";
import { holdingCreateSchema, holdingListQuerySchema } from "@/lib/schemas";
import {
  createHolding,
  fetchHoldingsPage,
  SupabaseApiError,
} from "@/lib/supabase-admin";

import {
  holdingsDependency,
  holdingsJsonError,
  holdingsStatusCode,
} from "./holding-api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/holdings";

function logRejectedHoldingsRequest(
  requestId: string,
  startedAtMs: number,
  method: "GET" | "POST",
  operation: string,
  statusCode: number,
  reason: string,
  fields: ApiLogFields = {},
): void {
  logApiWarn({
    event: "web_api_request_rejected",
    request_id: requestId,
    route: ROUTE,
    method,
    operation,
    status: "failed",
    status_code: statusCode,
    reason,
    duration_ms: elapsedMs(startedAtMs),
    ...fields,
  });
}

function holdingsRetryable(error: unknown, statusCode: number): boolean {
  return error instanceof SupabaseApiError && statusCode >= 500;
}

export async function GET(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();
  const method = "GET";
  const operation = "list_holdings";

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedHoldingsRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const parsedQuery = holdingListQuerySchema.safeParse({
    limit: request.nextUrl.searchParams.get("limit") ?? undefined,
    cursor: request.nextUrl.searchParams.get("cursor") ?? undefined,
  });
  if (!parsedQuery.success) {
    logRejectedHoldingsRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_query",
    );
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
    const cursor = parsedQuery.data.cursor
      ? decodeHoldingCursor(parsedQuery.data.cursor)
      : undefined;

    const page = await fetchHoldingsPage({
      limit: parsedQuery.data.limit,
      cursor,
    });
    const response = NextResponse.json(page);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "success",
      status_code: 200,
      dependency: "supabase",
      duration_ms: elapsedMs(startedAtMs),
      limit: parsedQuery.data.limit,
      item_count: page.items.length,
      has_next_page: Boolean(page.nextCursor),
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    if (error instanceof HoldingCursorError) {
      logRejectedHoldingsRequest(
        requestId,
        startedAtMs,
        method,
        operation,
        error.status,
        "invalid_cursor",
      );
      return withApiRequestId(
        NextResponse.json({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    const statusCode = holdingsStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "failed",
      status_code: statusCode,
      dependency: holdingsDependency(error),
      duration_ms: elapsedMs(startedAtMs),
      retryable: holdingsRetryable(error, statusCode),
      limit: parsedQuery.data.limit,
    });
    return withApiRequestId(holdingsJsonError(error), requestId);
  }
}

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();
  const method = "POST";
  const operation = "create_holding";

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedHoldingsRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    logRejectedHoldingsRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      body.response.status,
      "invalid_json",
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsed = holdingCreateSchema.safeParse(body.payload);
  if (!parsed.success) {
    logRejectedHoldingsRequest(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_payload",
    );
    return withApiRequestId(
      NextResponse.json(
        {
          error: "Invalid holding payload",
          details: parsed.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const created = await createHolding(parsed.data);
    const response = NextResponse.json(created, { status: 201 });
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "success",
      status_code: 201,
      dependency: "supabase",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    const statusCode = holdingsStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "failed",
      status_code: statusCode,
      dependency: holdingsDependency(error),
      duration_ms: elapsedMs(startedAtMs),
      retryable: holdingsRetryable(error, statusCode),
    });
    return withApiRequestId(holdingsJsonError(error), requestId);
  }
}
