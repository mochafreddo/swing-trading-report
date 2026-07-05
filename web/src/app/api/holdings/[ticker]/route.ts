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
import { parseJsonBody } from "@/lib/parse-json-body";
import {
  holdingPatchSchema,
  isHoldingEntryCurrencyValidForTicker,
} from "@/lib/schemas";
import { deleteHolding, updateHolding } from "@/lib/supabase-admin";

import {
  holdingsDependency,
  holdingsJsonError,
  holdingsStatusCode,
} from "../holding-api-errors";
import {
  parseHoldingTickerRouteParam,
  type SingleTickerRouteContext,
} from "../ticker-route-params";

export const runtime = "nodejs";

const ROUTE = "/api/holdings/[ticker]";

function logRejectedHoldingMutation(
  requestId: string,
  startedAtMs: number,
  method: "PATCH" | "DELETE",
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

export async function PATCH(
  request: NextRequest,
  context: SingleTickerRouteContext,
) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();
  const method = "PATCH";
  const operation = "update_holding";

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const params = await context.params;
  const ticker = parseHoldingTickerRouteParam(params.ticker);
  if (!ticker) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_ticker",
    );
    return withApiRequestId(
      NextResponse.json({ error: "Invalid ticker" }, { status: 400 }),
      requestId,
    );
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      body.response.status,
      "invalid_json",
      { ticker_count: 1 },
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsed = holdingPatchSchema.safeParse(body.payload);
  if (!parsed.success) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_payload",
      { ticker_count: 1 },
    );
    return withApiRequestId(
      NextResponse.json(
        {
          error: "Invalid holding patch payload",
          details: parsed.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }
  const currencyTicker = parsed.data.ticker ?? ticker;
  if (
    !isHoldingEntryCurrencyValidForTicker(
      currencyTicker,
      parsed.data.entry_currency,
    )
  ) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_payload",
      { ticker_count: 1 },
    );
    return withApiRequestId(
      NextResponse.json(
        { error: "Invalid holding patch payload" },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const updated = await updateHolding(ticker, parsed.data);
    if (!updated) {
      logRejectedHoldingMutation(
        requestId,
        startedAtMs,
        method,
        operation,
        404,
        "not_found",
        { ticker_count: 1, dependency: "supabase" },
      );
      return withApiRequestId(
        NextResponse.json({ error: "Holding not found" }, { status: 404 }),
        requestId,
      );
    }
    const response = NextResponse.json(updated);
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
      ticker_count: 1,
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
      retryable: statusCode >= 500,
      ticker_count: 1,
    });
    return withApiRequestId(holdingsJsonError(error), requestId);
  }
}

export async function DELETE(
  request: NextRequest,
  context: SingleTickerRouteContext,
) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();
  const method = "DELETE";
  const operation = "delete_holding";

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const params = await context.params;
  const ticker = parseHoldingTickerRouteParam(params.ticker);
  if (!ticker) {
    logRejectedHoldingMutation(
      requestId,
      startedAtMs,
      method,
      operation,
      400,
      "invalid_ticker",
    );
    return withApiRequestId(
      NextResponse.json({ error: "Invalid ticker" }, { status: 400 }),
      requestId,
    );
  }

  try {
    const deleted = await deleteHolding(ticker);
    if (!deleted) {
      logRejectedHoldingMutation(
        requestId,
        startedAtMs,
        method,
        operation,
        404,
        "not_found",
        { ticker_count: 1, dependency: "supabase" },
      );
      return withApiRequestId(
        NextResponse.json({ error: "Holding not found" }, { status: 404 }),
        requestId,
      );
    }
    const response = NextResponse.json({ deleted: true, ticker });
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
      ticker_count: 1,
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
      retryable: statusCode >= 500,
      ticker_count: 1,
    });
    return withApiRequestId(holdingsJsonError(error), requestId);
  }
}
