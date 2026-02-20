import { NextRequest, NextResponse } from "next/server";

import {
  ADMIN_SESSION_COOKIE_NAME,
  getAdminSessionCookieOptions,
} from "@/lib/admin-session";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  try {
    assertSameOrigin(request);
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof SameOriginError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof LocalRequestGuardError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  const response = NextResponse.json({ ok: true });
  response.cookies.set(
    ADMIN_SESSION_COOKIE_NAME,
    "",
    getAdminSessionCookieOptions(0),
  );
  return response;
}
