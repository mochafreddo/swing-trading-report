const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const SAFE_METHODS = new Set(["GET", "HEAD"]);

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

function readFirstHeaderValue(raw: string | null): string | null {
  if (!raw) {
    return null;
  }
  const first = raw.split(",")[0]?.trim();
  return first || null;
}

function extractHostnameFromUrl(rawUrl: string | null): string | null {
  const first = readFirstHeaderValue(rawUrl);
  if (!first) {
    return null;
  }
  try {
    return new URL(first).hostname.toLowerCase();
  } catch {
    return null;
  }
}

function isLocalHostname(hostname: string | null): boolean {
  return Boolean(hostname && LOCAL_HOSTS.has(hostname));
}

function isSafeMethod(method?: string): boolean {
  const normalized = (method ?? "GET").trim().toUpperCase();
  return SAFE_METHODS.has(normalized);
}

function shouldEnforceLocalRequestGuard(): boolean {
  return process.env.SAB_ENFORCE_LOCAL_REQUEST !== "0";
}

function shouldTrustHostHeaderForLocalRequest(): boolean {
  return process.env.SAB_TRUST_HOST_HEADER_FOR_LOCAL_REQUESTS === "1";
}

export function isLocalRequest(request: {
  headers: Pick<Headers, "get">;
  method?: string;
}): boolean {
  if (!shouldTrustHostHeaderForLocalRequest()) {
    return false;
  }

  const host = extractHostname(request.headers.get("host"));
  if (!isLocalHostname(host)) {
    return false;
  }

  const forwardedHost = extractHostname(
    request.headers.get("x-forwarded-host"),
  );
  if (forwardedHost && !isLocalHostname(forwardedHost)) {
    return false;
  }

  const originHost = extractHostnameFromUrl(request.headers.get("origin"));
  if (originHost && !isLocalHostname(originHost)) {
    return false;
  }

  const refererHost = extractHostnameFromUrl(request.headers.get("referer"));
  if (refererHost && !isLocalHostname(refererHost)) {
    return false;
  }

  if (!isSafeMethod(request.method) && !originHost && !refererHost) {
    const secFetchSite = readFirstHeaderValue(
      request.headers.get("sec-fetch-site"),
    );
    return secFetchSite?.toLowerCase() === "same-origin";
  }

  return true;
}

export function assertLocalRequest(request: {
  headers: Pick<Headers, "get">;
  method?: string;
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
