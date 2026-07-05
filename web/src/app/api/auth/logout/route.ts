import { NextRequest } from "next/server";

import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
} from "@/lib/api-request-log";
import {
  ADMIN_SESSION_COOKIE_NAME,
  getAdminSessionCookieOptions,
} from "@/lib/admin-session";
import { toErrorMessage } from "@/lib/error-utils";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { jsonWithNoStore } from "@/lib/reports-response";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

export const runtime = "nodejs";

const ROUTE = "/api/auth/logout";
const METHOD = "POST";
const OPERATION = "admin_logout";

function logRejectedLogout(
  requestId: string,
  startedAtMs: number,
  statusCode: number,
  reason: string,
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
  });
}

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  try {
    assertSameOrigin(request);
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof SameOriginError) {
      logRejectedLogout(
        requestId,
        startedAtMs,
        error.status,
        "same_origin_guard",
      );
      return withApiRequestId(
        jsonWithNoStore({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    if (error instanceof LocalRequestGuardError) {
      logRejectedLogout(
        requestId,
        startedAtMs,
        error.status,
        "local_request_guard",
      );
      return withApiRequestId(
        jsonWithNoStore({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: 500,
      duration_ms: elapsedMs(startedAtMs),
      retryable: false,
    });
    return withApiRequestId(
      jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }

  const response = jsonWithNoStore({ ok: true });
  response.cookies.set(
    ADMIN_SESSION_COOKIE_NAME,
    "",
    getAdminSessionCookieOptions(0),
  );
  logApiInfo({
    event: "web_api_request_completed",
    request_id: requestId,
    route: ROUTE,
    method: METHOD,
    operation: OPERATION,
    status: "success",
    status_code: 200,
    duration_ms: elapsedMs(startedAtMs),
  });
  return withApiRequestId(response, requestId);
}
