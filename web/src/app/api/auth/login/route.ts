import { NextRequest, NextResponse } from "next/server";

import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
} from "@/lib/api-request-log";
import { performAdminLogin } from "@/lib/admin-login";
import {
  ADMIN_SESSION_COOKIE_NAME,
  getAdminSessionCookieOptions,
} from "@/lib/admin-session";
import { toErrorMessage } from "@/lib/error-utils";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { parseJsonBody } from "@/lib/parse-json-body";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

export const runtime = "nodejs";

type LoginPayload = {
  username: string;
  password: string;
};

const ROUTE = "/api/auth/login";
const METHOD = "POST";
const OPERATION = "admin_login";

function parseLoginPayload(payload: unknown): LoginPayload | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const username = (payload as { username?: unknown }).username;
  const password = (payload as { password?: unknown }).password;
  if (typeof username !== "string" || typeof password !== "string") {
    return null;
  }
  const normalized = { username: username.trim(), password };
  if (!normalized.username || !normalized.password) {
    return null;
  }
  return normalized;
}

function logRejectedLogin(
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
      logRejectedLogin(
        requestId,
        startedAtMs,
        error.status,
        "same_origin_guard",
      );
      return withApiRequestId(
        NextResponse.json({ error: error.message }, { status: error.status }),
        requestId,
      );
    }
    if (error instanceof LocalRequestGuardError) {
      logRejectedLogin(
        requestId,
        startedAtMs,
        error.status,
        "local_request_guard",
      );
      return withApiRequestId(
        NextResponse.json({ error: error.message }, { status: error.status }),
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
      NextResponse.json({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    logRejectedLogin(
      requestId,
      startedAtMs,
      body.response.status,
      "invalid_json",
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsed = parseLoginPayload(body.payload);
  if (!parsed) {
    logRejectedLogin(requestId, startedAtMs, 400, "invalid_payload");
    return withApiRequestId(
      NextResponse.json({ error: "Invalid login payload" }, { status: 400 }),
      requestId,
    );
  }

  try {
    const result = await performAdminLogin(parsed.username, parsed.password);
    if (!result.ok) {
      logRejectedLogin(requestId, startedAtMs, result.status, "login_denied");
      return withApiRequestId(
        NextResponse.json(
          { error: result.error },
          {
            status: result.status,
            headers: result.retryAfterSeconds
              ? { "Retry-After": String(result.retryAfterSeconds) }
              : undefined,
          },
        ),
        requestId,
      );
    }

    const response = NextResponse.json({ ok: true });
    response.cookies.set(
      ADMIN_SESSION_COOKIE_NAME,
      result.token,
      getAdminSessionCookieOptions(),
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
  } catch (error) {
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
      NextResponse.json({ error: toErrorMessage(error) }, { status: 500 }),
      requestId,
    );
  }
}
