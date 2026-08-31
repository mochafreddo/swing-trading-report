import { NextResponse, type NextRequest } from "next/server";

import { AdminAuthError, requireAdminAuth } from "./src/lib/admin-auth";

function isPublicPath(pathname: string): boolean {
  return (
    pathname === "/login" ||
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

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  try {
    await requireAdminAuth(request);
  } catch (error) {
    if (error instanceof AdminAuthError) {
      return NextResponse.redirect(buildLoginRedirectUrl(request));
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return new NextResponse(message, { status: 500 });
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/today/:path*",
    "/holdings/:path*",
    "/reports/:path*",
    "/metrics/:path*",
    "/run/:path*",
  ],
};
