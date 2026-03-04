import "server-only";

import { getGitHubEnv } from "@/lib/env.server";
import { FetchTimeoutError, fetchWithTimeout } from "@/lib/fetch-timeout";
import type {
  WorkflowDispatchInput,
  WorkflowDispatchResult,
} from "@/lib/types";

export class GitHubDispatchError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

interface DispatchRequest {
  workflowFile: "scan.yml" | "sell.yml";
  workflowUrl: string;
  actionsUrl: string;
  dispatchUrl: string;
  body: {
    ref: string;
    inputs: Record<string, string>;
  };
}

const GITHUB_DISPATCH_ENV_KEYS = [
  "GITHUB_OWNER",
  "GITHUB_REPO",
  "GITHUB_PAT",
] as const;

function hasNonEmptyEnv(name: string): boolean {
  const raw = process.env[name];
  return typeof raw === "string" && raw.trim().length > 0;
}

function hasAllGitHubDispatchEnv(): boolean {
  return GITHUB_DISPATCH_ENV_KEYS.every((name) => hasNonEmptyEnv(name));
}

function isRunDispatchEnabled(): boolean {
  const raw = process.env.RUN_DISPATCH_ENABLED;
  const value = typeof raw === "string" ? raw.trim() : "";

  if (!value) {
    // Backward compatibility: legacy deployments had no feature flag.
    return hasAllGitHubDispatchEnv();
  }
  if (value === "1") {
    return true;
  }
  if (value === "0") {
    return false;
  }
  throw new GitHubDispatchError('RUN_DISPATCH_ENABLED must be "0" or "1"', 500);
}

export function buildWorkflowDispatchRequest(
  input: WorkflowDispatchInput,
): DispatchRequest {
  const gitHubEnv = getGitHubEnv();
  const workflowFile = input.workflow === "scan" ? "scan.yml" : "sell.yml";
  const ref = "main";

  const inputs: Record<string, string> = {
    provider: input.provider,
  };

  if (input.workflow === "scan") {
    inputs.universe = input.universe ?? "both";
  }

  const actionsBase = `https://github.com/${gitHubEnv.GITHUB_OWNER}/${gitHubEnv.GITHUB_REPO}/actions`;

  return {
    workflowFile,
    workflowUrl: `${actionsBase}/workflows/${workflowFile}`,
    actionsUrl: actionsBase,
    dispatchUrl: `https://api.github.com/repos/${gitHubEnv.GITHUB_OWNER}/${gitHubEnv.GITHUB_REPO}/actions/workflows/${workflowFile}/dispatches`,
    body: {
      ref,
      inputs,
    },
  };
}

export async function dispatchWorkflow(
  input: WorkflowDispatchInput,
): Promise<WorkflowDispatchResult> {
  if (!isRunDispatchEnabled()) {
    throw new GitHubDispatchError(
      "Run dispatch is disabled. Set RUN_DISPATCH_ENABLED=1 to enable /api/run.",
      503,
    );
  }

  const request = buildWorkflowDispatchRequest(input);
  const env = getGitHubEnv();

  let response: Response;
  try {
    response = await fetchWithTimeout(request.dispatchUrl, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_PAT}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request.body),
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof FetchTimeoutError) {
      throw new GitHubDispatchError(
        `GitHub workflow dispatch timed out after ${error.timeoutMs}ms`,
        504,
      );
    }
    throw error;
  }

  if (response.status !== 204) {
    let message = `GitHub workflow dispatch failed (${response.status})`;
    const text = await response.text();
    if (text) {
      try {
        const payload = JSON.parse(text) as { message?: string };
        if (payload.message) {
          message = `${message}: ${payload.message}`;
        } else {
          message = `${message}: ${text}`;
        }
      } catch {
        message = `${message}: ${text}`;
      }
    }
    throw new GitHubDispatchError(message, response.status);
  }

  return {
    dispatched: true,
    workflow: input.workflow,
    workflowFile: request.workflowFile,
    workflowUrl: request.workflowUrl,
    actionsUrl: request.actionsUrl,
    ref: request.body.ref,
  };
}
