"use server";

import { requireAdminActionSession } from "@/lib/admin-action-auth";
import { dispatchWorkflow, GitHubDispatchError } from "@/lib/github-actions";
import {
  isScanUniverseAllowed,
  PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
} from "@/lib/run-dispatch-policy";
import { runDispatchSchema } from "@/lib/schemas";
import type {
  WorkflowDispatchInput,
  WorkflowDispatchResult,
} from "@/lib/types";

export type RunActionResult =
  | {
      ok: true;
      result: WorkflowDispatchResult;
    }
  | {
      ok: false;
      error: string;
    };

export async function dispatchRunAction(
  input: unknown,
): Promise<RunActionResult> {
  try {
    await requireAdminActionSession();
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }

  const parsed = runDispatchSchema.safeParse(input);
  if (!parsed.success) {
    const firstMessage = parsed.error.issues.find(
      (issue) => typeof issue.message === "string" && issue.message.trim(),
    )?.message;

    return {
      ok: false,
      error: firstMessage ?? "Invalid run payload",
    };
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
        return {
          ok: false,
          error: PYKRX_SCAN_UNIVERSE_ERROR_MESSAGE,
        };
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

    return {
      ok: true,
      result: await dispatchWorkflow(dispatchInput),
    };
  } catch (error) {
    if (error instanceof GitHubDispatchError) {
      return {
        ok: false,
        error: error.message,
      };
    }

    return {
      ok: false,
      error: error instanceof Error ? error.message : "Unknown error",
    };
  }
}
