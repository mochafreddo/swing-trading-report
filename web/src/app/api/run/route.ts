import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { toErrorMessage } from "@/lib/error-utils";
import { dispatchWorkflow, GitHubDispatchError } from "@/lib/github-actions";
import {
  isScanUniverseAllowed,
  PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
} from "@/lib/run-dispatch-policy";
import { runDispatchSchema } from "@/lib/schemas";
import type { WorkflowDispatchInput } from "@/lib/types";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Request body must be valid JSON" },
      { status: 400 },
    );
  }

  const parsed = runDispatchSchema.safeParse(payload);
  if (!parsed.success) {
    const details = parsed.error.flatten();
    const firstMessage = parsed.error.issues.find(
      (issue) => typeof issue.message === "string" && issue.message.trim(),
    )?.message;
    return NextResponse.json(
      {
        error: firstMessage ?? "Invalid run payload",
        details,
      },
      { status: 400 },
    );
  }

  try {
    let dispatchInput: WorkflowDispatchInput;
    if (parsed.data.workflow === "sell") {
      dispatchInput = {
        workflow: "sell",
        provider: parsed.data.provider,
      };
    } else if (parsed.data.provider === "pykrx") {
      if (!isScanUniverseAllowed(parsed.data.provider, parsed.data.universe)) {
        return NextResponse.json(
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

    const dispatched = await dispatchWorkflow(dispatchInput);
    return NextResponse.json(dispatched, { status: 202 });
  } catch (error) {
    if (error instanceof GitHubDispatchError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }

    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}
