import { NextRequest, type NextResponse } from "next/server";

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
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";
import { isValidIdempotencyKey } from "@/lib/idempotency-key";
import { parseJsonBody } from "@/lib/parse-json-body";
import { jsonWithNoStore } from "@/lib/reports-response";
import { holdingAddBuySchema } from "@/lib/schemas";
import { addBuyToHolding, SupabaseApiError } from "@/lib/supabase-admin";

import {
  holdingsDependency,
  holdingsJsonError,
  holdingsStatusCode,
} from "../../holding-api-errors";
import {
  parseHoldingTickerRouteParam,
  type SingleTickerRouteContext,
} from "../../ticker-route-params";

type ParsedIdempotencyKeyHeader = {
  key: string | null;
  invalid: boolean;
};

export const runtime = "nodejs";

const ROUTE = "/api/holdings/[ticker]/add-buy";
const METHOD = "POST";
const OPERATION = "add_buy_to_holding";

function parseIdempotencyKeyHeader(
  request: NextRequest,
): ParsedIdempotencyKeyHeader {
  const raw = request.headers.get("idempotency-key");
  if (!raw) {
    return { key: null, invalid: false };
  }
  const key = raw.trim();
  if (!key) {
    return { key: null, invalid: false };
  }
  if (!isValidIdempotencyKey(key)) {
    return { key: null, invalid: true };
  }
  return { key, invalid: false };
}

function logRejectedAddBuy(
  requestId: string,
  startedAtMs: number,
  statusCode: number,
  reason: string,
  fields: ApiLogFields = {},
): void {
  logApiWarn({
    event: "web_api_request_rejected",
    request_id: requestId,
    route: ROUTE,
    method: METHOD,
    operation: OPERATION,
    status: "failed",
    status_code: statusCode,
    reason,
    duration_ms: elapsedMs(startedAtMs),
    ...fields,
  });
}

function addBuyJsonError(error: unknown): NextResponse {
  if (
    error instanceof SupabaseApiError &&
    error.status === 409 &&
    error.code === ADD_BUY_IDEMPOTENCY_MISMATCH_CODE
  ) {
    return jsonWithNoStore(
      {
        error: error.message,
        code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
      },
      { status: error.status },
    );
  }
  return holdingsJsonError(error);
}

export async function POST(
  request: NextRequest,
  context: SingleTickerRouteContext,
) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedAddBuy(requestId, startedAtMs, guardError.status, "admin_guard");
    return withApiRequestId(guardError, requestId);
  }

  const params = await context.params;
  const ticker = parseHoldingTickerRouteParam(params.ticker);
  if (!ticker) {
    logRejectedAddBuy(requestId, startedAtMs, 400, "invalid_ticker");
    return withApiRequestId(
      jsonWithNoStore({ error: "Invalid ticker" }, { status: 400 }),
      requestId,
    );
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    logRejectedAddBuy(
      requestId,
      startedAtMs,
      body.response.status,
      "invalid_json",
      {
        ticker_count: 1,
      },
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsed = holdingAddBuySchema.safeParse(body.payload);
  if (!parsed.success) {
    logRejectedAddBuy(requestId, startedAtMs, 400, "invalid_payload", {
      ticker_count: 1,
    });
    return withApiRequestId(
      jsonWithNoStore(
        {
          error: "Invalid holding add-buy payload",
          details: parsed.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  const idempotencyKeyHeader = parseIdempotencyKeyHeader(request);
  if (!idempotencyKeyHeader.key) {
    logRejectedAddBuy(
      requestId,
      startedAtMs,
      400,
      idempotencyKeyHeader.invalid
        ? "invalid_idempotency_key"
        : "missing_idempotency_key",
      { ticker_count: 1, idempotency_key_present: false },
    );
    return withApiRequestId(
      jsonWithNoStore(
        {
          error: idempotencyKeyHeader.invalid
            ? "Invalid Idempotency-Key header"
            : "Missing Idempotency-Key header",
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const updated = await addBuyToHolding(
      ticker,
      parsed.data,
      idempotencyKeyHeader.key,
    );
    if (!updated) {
      logRejectedAddBuy(requestId, startedAtMs, 404, "not_found", {
        ticker_count: 1,
        dependency: "supabase",
        idempotency_key_present: true,
      });
      return withApiRequestId(
        jsonWithNoStore({ error: "Holding not found" }, { status: 404 }),
        requestId,
      );
    }
    const response = jsonWithNoStore(updated);
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
      ticker_count: 1,
      idempotency_key_present: true,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    const statusCode = holdingsStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: statusCode,
      dependency: holdingsDependency(error),
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      ticker_count: 1,
      idempotency_key_present: true,
    });
    return withApiRequestId(addBuyJsonError(error), requestId);
  }
}
