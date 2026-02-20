export class SameOriginError extends Error {
  readonly status = 403;

  constructor(message = "Cross-site request blocked") {
    super(message);
  }
}

function readFirstHeaderValue(raw: string | null): string | null {
  if (!raw) {
    return null;
  }
  const first = raw.split(",")[0]?.trim();
  return first || null;
}

function normalizeOrigin(value: string): string | null {
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

function resolveExpectedOrigins(request: {
  headers: Pick<Headers, "get">;
  nextUrl: URL;
}): Set<string> {
  const expectedOrigins = new Set<string>();

  const nextUrlOrigin = normalizeOrigin(request.nextUrl.origin);
  if (nextUrlOrigin) {
    expectedOrigins.add(nextUrlOrigin);
  }

  const host = readFirstHeaderValue(request.headers.get("host"));
  if (!host) {
    return expectedOrigins;
  }

  const forwardedProto = readFirstHeaderValue(
    request.headers.get("x-forwarded-proto"),
  );
  const protocol =
    forwardedProto === "http" || forwardedProto === "https"
      ? forwardedProto
      : request.nextUrl.protocol.replace(/:$/, "");
  const hostOrigin = normalizeOrigin(`${protocol}://${host}`);
  if (hostOrigin) {
    expectedOrigins.add(hostOrigin);
  }

  return expectedOrigins;
}

export function assertSameOrigin(request: {
  headers: Pick<Headers, "get">;
  nextUrl: URL;
}): void {
  const expectedOrigins = resolveExpectedOrigins(request);

  const origin = readFirstHeaderValue(request.headers.get("origin"));
  if (origin) {
    const normalizedOrigin = normalizeOrigin(origin);
    if (!normalizedOrigin || !expectedOrigins.has(normalizedOrigin)) {
      throw new SameOriginError();
    }
    return;
  }

  const secFetchSite = request.headers.get("sec-fetch-site");
  if (secFetchSite === "cross-site") {
    throw new SameOriginError();
  }
  if (secFetchSite === "same-origin") {
    return;
  }

  const referer = request.headers.get("referer");
  if (referer) {
    const refererValue = readFirstHeaderValue(referer);
    try {
      if (!refererValue) {
        throw new SameOriginError();
      }
      const refererOrigin = normalizeOrigin(refererValue);
      if (!refererOrigin || !expectedOrigins.has(refererOrigin)) {
        throw new SameOriginError();
      }
      return;
    } catch {
      throw new SameOriginError();
    }
  }

  throw new SameOriginError("Missing Origin/Referer for unsafe request");
}
