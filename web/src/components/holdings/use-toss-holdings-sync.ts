import { useCallback, useMemo, useState } from "react";

import { readApiError } from "@/components/holdings/helpers";
import type {
  HoldingReplaceSnapshot,
  HoldingSnapshot,
  HoldingsYamlImportSummary,
} from "@/lib/types";
import type { HoldingReconciliationField } from "@/lib/holdings-reconciliation";
import type {
  TossHoldingsBlockedReason,
  TossHoldingsBlockedRow,
} from "@/lib/toss/holdings-sync";

type Fetcher = typeof fetch;

export type TossSyncStatus =
  | "idle"
  | "loading"
  | "applying"
  | "ready"
  | "applied"
  | "blocked"
  | "empty"
  | "error"
  | "rate-limited";

export interface TossHoldingCreateChange {
  ticker: string;
  after: HoldingReplaceSnapshot;
}

export interface TossHoldingUpdateChange {
  ticker: string;
  before: HoldingSnapshot;
  after: HoldingReplaceSnapshot;
  changedFields: HoldingReconciliationField[];
}

export interface TossHoldingDeleteChange {
  ticker: string;
  before: HoldingSnapshot;
}

interface TossHoldingUnchangedChange {
  ticker: string;
  before: HoldingSnapshot;
  after: HoldingReplaceSnapshot;
}

export interface TossHoldingsDryRunResponse {
  mode: "dry-run" | "apply";
  diffHash: string;
  applyBlocked: boolean;
  summary: HoldingsYamlImportSummary;
  changes: {
    create: TossHoldingCreateChange[];
    update: TossHoldingUpdateChange[];
    delete: TossHoldingDeleteChange[];
    unchanged: TossHoldingUnchangedChange[];
  };
  blockedRows: Array<
    TossHoldingsBlockedRow & {
      reason: TossHoldingsBlockedReason;
    }
  >;
  targetRows: HoldingReplaceSnapshot[];
}

class TossHoldingsSyncRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "TossHoldingsSyncRequestError";
    this.status = status;
  }
}

async function requestTossHoldingsDryRun(
  fetcher: Fetcher = fetch,
): Promise<TossHoldingsDryRunResponse> {
  const response = await fetcher("/api/holdings/toss-sync", {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ mode: "dry-run" }),
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new TossHoldingsSyncRequestError(
      readApiError(payload) || "Failed to run Toss holdings dry-run",
      response.status,
    );
  }
  return payload as TossHoldingsDryRunResponse;
}

async function requestTossHoldingsApply(
  diffHash: string,
  fetcher: Fetcher = fetch,
): Promise<TossHoldingsDryRunResponse> {
  const response = await fetcher("/api/holdings/toss-sync", {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      mode: "apply",
      diffHash,
    }),
  });
  const payload = (await response.json()) as unknown;
  if (!response.ok) {
    throw new TossHoldingsSyncRequestError(
      readApiError(payload) || "Failed to apply Toss holdings sync",
      response.status,
    );
  }
  return payload as TossHoldingsDryRunResponse;
}

function hasChanges(summary: HoldingsYamlImportSummary): boolean {
  return (
    summary.createCount > 0 ||
    summary.updateCount > 0 ||
    summary.deleteCount > 0
  );
}

function statusFromDryRun(
  response: TossHoldingsDryRunResponse,
): TossSyncStatus {
  if (response.applyBlocked) {
    return "blocked";
  }
  return hasChanges(response.summary) ? "ready" : "empty";
}

function statusMessage(status: TossSyncStatus): string {
  switch (status) {
    case "idle":
      return "No Toss snapshot yet";
    case "loading":
      return "Fetching Toss snapshot...";
    case "applying":
      return "Applying Toss snapshot...";
    case "ready":
      return "Dry-run ready";
    case "applied":
      return "Applied Toss holdings sync";
    case "blocked":
      return "Apply blocked";
    case "empty":
      return "Supabase already matches Toss normalized holdings";
    case "rate-limited":
      return "Toss rate limit reached";
    case "error":
      return "Toss dry-run failed";
  }
}

interface UseTossHoldingsSyncOptions {
  requestDryRun?: () => Promise<TossHoldingsDryRunResponse>;
  requestApply?: (diffHash: string) => Promise<TossHoldingsDryRunResponse>;
  onApplied?: () => void | Promise<void>;
}

export function useTossHoldingsSync({
  requestDryRun = requestTossHoldingsDryRun,
  requestApply = requestTossHoldingsApply,
  onApplied,
}: UseTossHoldingsSyncOptions = {}) {
  const [status, setStatus] = useState<TossSyncStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<TossHoldingsDryRunResponse | null>(null);

  const runDryRun = useCallback(async () => {
    setStatus("loading");
    setError(null);
    setSuccess(null);
    setDryRun(null);
    try {
      const response = await requestDryRun();
      setDryRun(response);
      setStatus(statusFromDryRun(response));
    } catch (runError) {
      if (
        runError instanceof TossHoldingsSyncRequestError &&
        runError.status === 429
      ) {
        setStatus("rate-limited");
      } else {
        setStatus("error");
      }
      setError(
        runError instanceof Error
          ? runError.message
          : "Failed to run Toss holdings dry-run",
      );
    }
  }, [requestDryRun]);

  const apply = useCallback(async () => {
    if (!dryRun?.diffHash) {
      setError("Run a Toss dry-run before applying.");
      return;
    }
    if (dryRun.applyBlocked) {
      setError("Resolve blocked Toss rows before applying.");
      return;
    }

    setStatus("applying");
    setError(null);
    setSuccess(null);
    try {
      const response = await requestApply(dryRun.diffHash);
      setDryRun(response);
      setStatus("applied");
      setSuccess("Applied Toss holdings sync");
      await onApplied?.();
    } catch (applyError) {
      setStatus("error");
      setError(
        applyError instanceof Error
          ? applyError.message
          : "Failed to apply Toss holdings sync",
      );
    }
  }, [dryRun, onApplied, requestApply]);

  return useMemo(
    () => ({
      status,
      statusMessage: statusMessage(status),
      loading: status === "loading",
      applying: status === "applying",
      error,
      success,
      summary: dryRun?.summary ?? null,
      changes: dryRun?.changes ?? null,
      blockedRows: dryRun?.blockedRows ?? [],
      targetRows: dryRun?.targetRows ?? [],
      diffHash: dryRun?.diffHash ?? null,
      canRunDryRun: status !== "loading" && status !== "applying",
      canApply:
        dryRun !== null &&
        status === "ready" &&
        !dryRun.applyBlocked &&
        hasChanges(dryRun.summary),
      runDryRun,
      apply,
    }),
    [apply, dryRun, error, runDryRun, status, success],
  );
}
