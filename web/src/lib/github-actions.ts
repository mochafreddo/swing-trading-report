import "server-only";

import { getGitHubEnv } from "@/lib/env.server";
import type {
  WorkflowDispatchInput,
  WorkflowDispatchResult
} from "@/lib/types";

export class GitHubDispatchError extends Error {
  constructor(
    message: string,
    public readonly status: number
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

export function buildWorkflowDispatchRequest(
  input: WorkflowDispatchInput
): DispatchRequest {
  const gitHubEnv = getGitHubEnv();
  const workflowFile = input.workflow === "scan" ? "scan.yml" : "sell.yml";
  const ref = "main";

  const inputs: Record<string, string> = {
    provider: input.provider
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
      inputs
    }
  };
}

export async function dispatchWorkflow(
  input: WorkflowDispatchInput
): Promise<WorkflowDispatchResult> {
  const env = getGitHubEnv();
  const request = buildWorkflowDispatchRequest(input);

  const response = await fetch(request.dispatchUrl, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_PAT}`,
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(request.body),
    cache: "no-store"
  });

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
    ref: request.body.ref
  };
}
