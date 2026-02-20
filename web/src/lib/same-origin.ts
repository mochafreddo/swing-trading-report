export class SameOriginError extends Error {
  readonly status = 403;

  constructor(message = "Cross-site request blocked") {
    super(message);
  }
}

export function assertSameOrigin(request: {
  headers: Pick<Headers, "get">;
  nextUrl: URL;
}): void {
  const expectedOrigin = request.nextUrl.origin;

  const origin = request.headers.get("origin");
  if (origin) {
    if (origin !== expectedOrigin) {
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
    try {
      if (new URL(referer).origin !== expectedOrigin) {
        throw new SameOriginError();
      }
      return;
    } catch {
      throw new SameOriginError();
    }
  }

  throw new SameOriginError("Missing Origin/Referer for unsafe request");
}
