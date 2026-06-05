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
import { dispatchWorkflow, GitHubDispatchError } from "@/lib/github-actions";
import { parseJsonBody } from "@/lib/parse-json-body";
import {
  isScanUniverseAllowed,
  PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
} from "@/lib/run-dispatch-policy";
import { runDispatchSchema } from "@/lib/schemas";
import type { WorkflowDispatchInput } from "@/lib/types";

export const runtime = "nodejs";

const ROUTE = "/api/run";
const METHOD = "POST";
const OPERATION = "dispatch_workflow";

function dispatchLogFields(input: WorkflowDispatchInput): ApiLogFields {
  if (input.workflow === "sell") {
    return { workflow: input.workflow, provider: input.provider };
  }
  return {
    workflow: input.workflow,
    provider: input.provider,
    universe: input.universe,
  };
}

function logRejectedRunRequest(
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

export async function POST(request: NextRequest) {
  const requestId = getApiRequestId(request);
  const startedAtMs = Date.now();

  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    logRejectedRunRequest(
      requestId,
      startedAtMs,
      guardError.status,
      "admin_guard",
    );
    return withApiRequestId(guardError, requestId);
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    logRejectedRunRequest(
      requestId,
      startedAtMs,
      body.response.status,
      "invalid_json",
    );
    return withApiRequestId(body.response, requestId);
  }

  const parsed = runDispatchSchema.safeParse(body.payload);
  if (!parsed.success) {
    const details = parsed.error.flatten();
    const firstMessage = parsed.error.issues.find(
      (issue) => typeof issue.message === "string" && issue.message.trim(),
    )?.message;
    logRejectedRunRequest(requestId, startedAtMs, 400, "invalid_payload");
    return withApiRequestId(
      NextResponse.json(
        {
          error: firstMessage ?? "Invalid run payload",
          details,
        },
        { status: 400 },
      ),
      requestId,
    );
  }

  let dispatchInput: WorkflowDispatchInput;
  if (parsed.data.workflow === "sell") {
    dispatchInput = {
      workflow: "sell",
      provider: parsed.data.provider,
    };
  } else if (parsed.data.provider === "pykrx") {
    if (!isScanUniverseAllowed(parsed.data.provider, parsed.data.universe)) {
      logRejectedRunRequest(
        requestId,
        startedAtMs,
        400,
        "unsupported_universe",
        {
          workflow: "scan",
          provider: "pykrx",
          universe: parsed.data.universe,
        },
      );
      return withApiRequestId(
        NextResponse.json(
          {
            error: PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
            details: {
              formErrors: [],
              fieldErrors: {
                universe: [PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE],
              },
            },
          },
          { status: 400 },
        ),
        requestId,
      );
    }
    dispatchInput = {
      workflow: "scan",
      provider: "pykrx",
      universe: parsed.data.universe,
    };
  } else {
    dispatchInput = {
      workflow: "scan",
      provider: "kis",
      universe: parsed.data.universe,
    };
  }

  const logFields = dispatchLogFields(dispatchInput);

  try {
    const dispatched = await dispatchWorkflow(dispatchInput);
    const response = NextResponse.json(dispatched, { status: 202 });
    logApiInfo({
      event: "web_api_request_completed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "success",
      status_code: 202,
      dependency: "github_actions",
      duration_ms: elapsedMs(startedAtMs),
      ...logFields,
    });
    return withApiRequestId(response, requestId);
  } catch (error) {
    const statusCode =
      error instanceof GitHubDispatchError ? error.status : 500;
    logApiError(error, {
      event: "web_api_request_failed",
      request_id: requestId,
      route: ROUTE,
      method: METHOD,
      operation: OPERATION,
      status: "failed",
      status_code: statusCode,
      dependency: "github_actions",
      duration_ms: elapsedMs(startedAtMs),
      retryable: statusCode >= 500,
      ...logFields,
    });

    if (error instanceof GitHubDispatchError) {
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
