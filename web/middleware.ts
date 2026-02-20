import { NextResponse, type NextRequest } from "next/server";

import { AdminAuthError, requireAdminAuth } from "./src/lib/admin-auth";
import { assertSameOrigin, SameOriginError } from "./src/lib/same-origin";

function isSafeMethod(method: string): boolean {
  return method === "GET" || method === "HEAD";
}

function isApiPath(pathname: string): boolean {
  return pathname.startsWith("/api/");
}

function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
    pathname === "/api/auth/login" ||
    pathname === "/api/auth/logout" ||
    pathname.startsWith("/_next/") ||
    pathname === "/favicon.ico"
  );
}

function buildLoginRedirectUrl(request: NextRequest): URL {
  const loginUrl = new URL("/login", request.url);
  const next = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  if (next && next !== "/login") {
    loginUrl.searchParams.set("next", next);
  }
  return loginUrl;
}

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname;
  const isApi = isApiPath(pathname);

  if (isApi && !isSafeMethod(request.method)) {
    try {
      assertSameOrigin(request);
    } catch (error) {
      if (error instanceof SameOriginError) {
        return new NextResponse(JSON.stringify({ error: error.message }), {
          status: error.status,
          headers: { "Content-Type": "application/json" },
        });
      }
      const message = error instanceof Error ? error.message : "Unknown error";
      return new NextResponse(JSON.stringify({ error: message }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  try {
    await requireAdminAuth(request);
  } catch (error) {
    if (error instanceof AdminAuthError) {
      if (isApi) {
        return NextResponse.json({ error: error.message }, { status: 401 });
      }
      return NextResponse.redirect(buildLoginRedirectUrl(request));
    }

    const message = error instanceof Error ? error.message : "Unknown error";
    if (isApi) {
      return NextResponse.json({ error: message }, { status: 500 });
    }
    return new NextResponse(message, { status: 500 });
  }

  return NextResponse.next();
}
