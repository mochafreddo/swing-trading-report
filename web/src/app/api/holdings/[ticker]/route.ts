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
import { toErrorMessage } from "@/lib/error-utils";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import { parseJsonBody } from "@/lib/parse-json-body";
import { holdingPatchSchema, holdingTickerSchema } from "@/lib/schemas";
import {
  deleteHolding,
  SupabaseApiError,
  updateHolding,
} from "@/lib/supabase-admin";

export const runtime = "nodejs";

type RouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

const ROUTE = "/api/holdings/[ticker]";

function parseTickerParam(rawTicker: string): string | null {
  const candidate = (() => {
    try {
      return decodeURIComponent(rawTicker);
    } catch {
      return rawTicker;
    }
  })();
  const parsed = holdingTickerSchema.safeParse(candidate);
  return parsed.success ? normalizeHoldingTickerForMutation(parsed.data) : null;
}

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

function supabaseStatusCode(error: unknown): number {
  return error instanceof SupabaseApiError ? error.status : 500;
}

export async function PATCH(request: NextRequest, context: RouteContext) {
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
  const ticker = parseTickerParam(params.ticker);
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
    const statusCode = supabaseStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "failed",
      status_code: statusCode,
      dependency: error instanceof SupabaseApiError ? "supabase" : undefined,
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      ticker_count: 1,
    });
    if (error instanceof SupabaseApiError) {
      return withApiRequestId(
        NextResponse.json({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    return withApiRequestId(
      NextResponse.json({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}

export async function DELETE(request: NextRequest, context: RouteContext) {
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
  const ticker = parseTickerParam(params.ticker);
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
    const statusCode = supabaseStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method,
      operation,
      status: "failed",
      status_code: statusCode,
      dependency: error instanceof SupabaseApiError ? "supabase" : undefined,
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      ticker_count: 1,
    });
    if (error instanceof SupabaseApiError) {
      return withApiRequestId(
        NextResponse.json({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    return withApiRequestId(
      NextResponse.json({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}
