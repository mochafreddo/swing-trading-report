const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

export class LocalRequestGuardError extends Error {
  readonly status = 403;

  constructor(message = "API is only available from local host") {
    super(message);
  }
}

function extractHostname(rawHost: string | null): string | null {
  if (!rawHost) {
    return null;
  }

  const first = rawHost.split(",")[0]?.trim().toLowerCase();
  if (!first) {
    return null;
  }

  if (first.includes("://")) {
    try {
      return new URL(first).hostname.toLowerCase();
    } catch {
      return null;
    }
  }

  if (first.startsWith("[")) {
    const end = first.indexOf("]");
    if (end <= 1) {
      return null;
    }
    return first.slice(1, end);
  }

  const colonCount = (first.match(/:/g) ?? []).length;
  if (colonCount === 0) {
    return first;
  }
  if (colonCount === 1) {
    return first.split(":")[0] ?? null;
  }

  return first;
}

function shouldEnforceLocalRequestGuard(): boolean {
  return process.env.SAB_ENFORCE_LOCAL_REQUEST !== "0";
}

export function isLocalRequest(request: {
  headers: Pick<Headers, "get">;
}): boolean {
  const rawHost = request.headers.get("host");
  const hostname = extractHostname(rawHost);
  return Boolean(hostname && LOCAL_HOSTS.has(hostname));
}

export function assertLocalRequest(request: {
  headers: Pick<Headers, "get">;
}): void {
  if (process.env.NODE_ENV === "test") {
    return;
  }

  if (!shouldEnforceLocalRequestGuard()) {
    return;
  }

  if (!isLocalRequest(request)) {
    throw new LocalRequestGuardError();
  }
}
