import "server-only";

const DEFAULT_EXTERNAL_FETCH_TIMEOUT_MS = 10_000;

type AbortSignalWithReason = AbortSignal & {
  reason?: unknown;
};

function resolveExternalFetchTimeoutMs(): number {
  const raw = process.env.SAB_EXTERNAL_FETCH_TIMEOUT_MS;
  const parsed = Number.parseInt(raw ?? "", 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return DEFAULT_EXTERNAL_FETCH_TIMEOUT_MS;
  }
  return parsed;
}

function isTimeoutLikeError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  const name = error.name.toLowerCase();
  if (name.includes("timeout")) {
    return true;
  }
  if (name !== "aborterror") {
    return false;
  }
  const message = error.message.toLowerCase();
  return (
    message.includes("timeout") ||
    message.includes("timed out") ||
    message.includes("time out")
  );
}

export class FetchTimeoutError extends Error {
  public readonly rootCause: unknown;

  constructor(
    public readonly url: string,
    public readonly timeoutMs: number,
    cause: unknown,
  ) {
    super(`Request timed out after ${timeoutMs}ms: ${url}`);
    this.name = "FetchTimeoutError";
    this.rootCause = cause;
  }
}

interface MergedAbortSignal {
  signal: AbortSignal;
  didTimeout: () => boolean;
}

function mergeAbortSignal(
  timeoutMs: number,
  inputSignal: AbortSignal | undefined,
): MergedAbortSignal {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  let timedOut = false;
  if (!inputSignal) {
    if (timeoutSignal.aborted) {
      timedOut = true;
    } else {
      timeoutSignal.addEventListener(
        "abort",
        () => {
          timedOut = true;
        },
        { once: true },
      );
    }
    return {
      signal: timeoutSignal,
      didTimeout: () => timedOut,
    };
  }
  const abortSignalAny = (
    AbortSignal as unknown as {
      any?: (signals: AbortSignal[]) => AbortSignal;
    }
  ).any;
  if (typeof abortSignalAny === "function") {
    const combinedSignal = abortSignalAny([inputSignal, timeoutSignal]);
    const syncTimedOutFromReason = () => {
      const combinedReason = (combinedSignal as AbortSignalWithReason).reason;
      const timeoutReason = (timeoutSignal as AbortSignalWithReason).reason;
      timedOut = timeoutSignal.aborted && combinedReason === timeoutReason;
    };
    if (combinedSignal.aborted) {
      syncTimedOutFromReason();
    } else {
      combinedSignal.addEventListener("abort", syncTimedOutFromReason, {
        once: true,
      });
    }
    return {
      signal: combinedSignal,
      didTimeout: () => timedOut,
    };
  }

  const controller = new AbortController();
  const relayAbort = (
    signal: AbortSignalWithReason,
    source: "input" | "timeout",
  ) => {
    if (signal.aborted) {
      if (!controller.signal.aborted) {
        timedOut = source === "timeout";
      }
      controller.abort(signal.reason);
      return;
    }
    signal.addEventListener(
      "abort",
      () => {
        if (!controller.signal.aborted) {
          timedOut = source === "timeout";
        }
        controller.abort(signal.reason);
      },
      { once: true },
    );
  };

  relayAbort(inputSignal as AbortSignalWithReason, "input");
  relayAbort(timeoutSignal as AbortSignalWithReason, "timeout");
  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
  };
}

export async function fetchWithTimeout(
  input: string,
  init?: RequestInit,
): Promise<Response> {
  const timeoutMs = resolveExternalFetchTimeoutMs();
  const mergedSignal = mergeAbortSignal(timeoutMs, init?.signal ?? undefined);
  try {
    return await fetch(input, {
      ...init,
      signal: mergedSignal.signal,
    });
  } catch (error) {
    if (mergedSignal.didTimeout() || isTimeoutLikeError(error)) {
      throw new FetchTimeoutError(input, timeoutMs, error);
    }
    throw error;
  }
}
