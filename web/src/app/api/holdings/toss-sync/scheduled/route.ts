import { NextRequest, NextResponse } from "next/server";

import {
  elapsedMs,
  getApiRequestId,
  logApiError,
  logApiInfo,
  logApiWarn,
  withApiRequestId,
} from "@/lib/api-request-log";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { parseJsonBody } from "@/lib/parse-json-body";
import { tossHoldingsScheduledSyncRequestSchema } from "@/lib/schemas";
import { runScheduledTossAutoApply } from "@/lib/toss/holdings-sync-service";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/holdings/toss-sync/scheduled";
// Scheduled local jobs intentionally do not call enforceAdminApiGuard(request).

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) {
    return false;
  }
  let result = 0;
  for (let index = 0; index < left.length; index += 1) {
    result |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return result === 0;
}

function readBearerToken(request: NextRequest): string | null {
  const header = request.headers.get("authorization");
  const match = header?.match(/^Bearer\s+(.+)$/i);
  const token = match?.[1]?.trim();
  return token || null;
}

function requireScheduledJobToken(request: NextRequest): NextResponse | null {
  const expected = process.env.TOSS_SYNC_JOB_TOKEN?.trim() ?? "";
  const actual = readBearerToken(request);
  if (!expected || !actual || !constantTimeEqual(actual, expected)) {
    return NextResponse.json(
      { error: "Unauthorized Toss sync job" },
      { status: 401 },
    );
  }
  return null;
}

function localGuardResponse(error: unknown): NextResponse {
  if (error instanceof LocalRequestGuardError) {
    return NextResponse.json(
      { error: error.message },
      { status: error.status },
    );
  }
  return NextResponse.json(
    { error: "Local request guard failed" },
    { status: 403 },
  );
}

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  try {
    assertLocalRequest(request);
  } catch (error) {
    logApiWarn({
      event: "web_api_request_rejected",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: "failed",
      status_code: error instanceof LocalRequestGuardError ? error.status : 403,
      reason: "local_request_guard",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(localGuardResponse(error), requestId);
  }

  const tokenError = requireScheduledJobToken(request);
  if (tokenError) {
    logApiWarn({
      event: "web_api_request_rejected",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: "failed",
      status_code: 401,
      reason: "job_token",
      duration_ms: elapsedMs(startedAtMs),
    });
    return withApiRequestId(tokenError, requestId);
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    return withApiRequestId(body.response, requestId);
  }

  const parsed = tossHoldingsScheduledSyncRequestSchema.safeParse(body.payload);
  if (!parsed.success) {
    return withApiRequestId(
      NextResponse.json(
        {
          error: "Invalid scheduled Toss holdings sync payload",
          details: parsed.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const result = await runScheduledTossAutoApply({
      autoApplyEnabled: process.env.TOSS_SYNC_AUTO_APPLY_ENABLED === "1",
    });
    const response = NextResponse.json(result);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status:
        result.status === "applied" || result.status === "unchanged"
          ? "success"
          : "skipped",
      status_code: 200,
      dependency: "toss,supabase",
      duration_ms: elapsedMs(startedAtMs),
      mode: result.mode,
      sync_status: result.status,
      blocked_count: result.blockedRows.length,
      create_count: result.summary.createCount,
      update_count: result.summary.updateCount,
      delete_count: result.summary.deleteCount,
      unchanged_count: result.summary.unchangedCount,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "scheduled_toss_holdings_sync",
      status: "failed",
      status_code: 500,
      duration_ms: elapsedMs(startedAtMs),
      retryable: true,
    });
    return withApiRequestId(
      NextResponse.json(
        { error: "Scheduled Toss holdings sync failed" },
        { status: 500 },
      ),
      requestId,
    );
  }
}
