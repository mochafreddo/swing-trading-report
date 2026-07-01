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
import { tossHoldingsSyncRequestSchema } from "@/lib/schemas";
import {
  applyTossHoldingsSyncPreview,
  buildTossHoldingsSyncPreview,
} from "@/lib/toss/holdings-sync-service";
import { TossInvestApiError, TossInvestConfigError } from "@/lib/toss/client";
import { type TossHoldingsDryRunResult } from "@/lib/toss/holdings-sync";

import {
  holdingsDependency,
  holdingsJsonError,
  holdingsStatusCode,
} from "../holding-api-errors";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const ROUTE = "/api/holdings/toss-sync";

function logRejectedTossSyncRequest(
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
    method: "POST",
    operation: "dry_run_toss_holdings",
    status: "failed",
    status_code: statusCode,
    reason,
    duration_ms: elapsedMs(startedAtMs),
    ...fields,
  });
}

function tossSyncStatusCode(error: unknown): number {
  if (error instanceof TossInvestApiError) {
    return error.status;
  }
  if (error instanceof TossInvestConfigError) {
    return 500;
  }
  return holdingsStatusCode(error);
}

function tossSyncDependency(error: unknown): string | undefined {
  if (
    error instanceof TossInvestApiError ||
    error instanceof TossInvestConfigError
  ) {
    return "toss";
  }
  return holdingsDependency(error);
}

function tossSyncJsonError(error: unknown): NextResponse {
  if (
    error instanceof TossInvestApiError ||
    error instanceof TossInvestConfigError
  ) {
    return NextResponse.json(
      { error: error.message },
      { status: tossSyncStatusCode(error) },
    );
  }
  return holdingsJsonError(error);
}

function tossSyncConflictResponse(
  error: string,
  dryRun: TossHoldingsDryRunResult,
  diffHash: string,
): NextResponse {
  return NextResponse.json(
    {
      error,
      diffHash,
      applyBlocked: dryRun.applyBlocked,
      summary: dryRun.reconciliation.summary,
      changes: dryRun.reconciliation.changes,
      blockedRows: dryRun.blockedRows,
      targetRows: dryRun.targetRows,
    },
    { status: 409 },
  );
}

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedTossSyncRequest(
      requestId,
      startedAtMs,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    logRejectedTossSyncRequest(
      requestId,
      startedAtMs,
      body.response.status,
      "invalid_json",
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsedRequest = tossHoldingsSyncRequestSchema.safeParse(body.payload);
  if (!parsedRequest.success) {
    logRejectedTossSyncRequest(requestId, startedAtMs, 400, "invalid_payload");
    return withApiRequestId(
      NextResponse.json(
        {
          error: "Invalid Toss holdings sync payload",
          details: parsedRequest.error.flatten(),
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  try {
    const preview = await buildTossHoldingsSyncPreview();
    const dryRun = preview.dryRun;
    const diffHash = preview.diffHash;

    if (parsedRequest.data.mode === "apply") {
      if (dryRun.applyBlocked) {
        logRejectedTossSyncRequest(
          requestId,
          startedAtMs,
          409,
          "apply_blocked_rows",
          {
            mode: "apply",
            blocked_count: dryRun.blockedRows.length,
          },
        );
        return withApiRequestId(
          tossSyncConflictResponse(
            "Toss holdings apply is blocked by unresolved rows. Run a new dry-run after resolving them.",
            dryRun,
            diffHash,
          ),
          requestId,
        );
      }

      if (parsedRequest.data.diffHash !== diffHash) {
        logRejectedTossSyncRequest(
          requestId,
          startedAtMs,
          409,
          "stale_diff_hash",
          { mode: "apply" },
        );
        return withApiRequestId(
          tossSyncConflictResponse(
            "Toss holdings diff changed. Run a new dry-run before applying.",
            dryRun,
            diffHash,
          ),
          requestId,
        );
      }

      const responsePayload = await applyTossHoldingsSyncPreview(preview);
      const response = NextResponse.json(responsePayload);
      logApiInfo({
        event: "web_api_request_completed",
        request_id: requestId,
        route: ROUTE,
        method: "POST",
        operation: "apply_toss_holdings",
        status: "success",
        status_code: 200,
        dependency: "toss,supabase",
        duration_ms: elapsedMs(startedAtMs),
        mode: responsePayload.mode,
        toss_item_count: preview.tossItems.length,
        blocked_count: dryRun.blockedRows.length,
        create_count: responsePayload.summary.createCount,
        update_count: responsePayload.summary.updateCount,
        delete_count: responsePayload.summary.deleteCount,
        unchanged_count: responsePayload.summary.unchangedCount,
      });
      return withApiRequestId(response, requestId);
    }

    const responsePayload = preview.payload;
    const response = NextResponse.json(responsePayload);
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation: "dry_run_toss_holdings",
      status: "success",
      status_code: 200,
      dependency: "toss,supabase",
      duration_ms: elapsedMs(startedAtMs),
      mode: responsePayload.mode,
      toss_item_count: preview.tossItems.length,
      blocked_count: dryRun.blockedRows.length,
      create_count: dryRun.reconciliation.summary.createCount,
      update_count: dryRun.reconciliation.summary.updateCount,
      delete_count: dryRun.reconciliation.summary.deleteCount,
      unchanged_count: dryRun.reconciliation.summary.unchangedCount,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    const statusCode = tossSyncStatusCode(error);
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: "POST",
      operation:
        parsedRequest.data.mode === "apply"
          ? "apply_toss_holdings"
          : "dry_run_toss_holdings",
      status: "failed",
      status_code: statusCode,
      dependency: tossSyncDependency(error),
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      mode: parsedRequest.data.mode,
    });
    return withApiRequestId(tossSyncJsonError(error), requestId);
  }
}
