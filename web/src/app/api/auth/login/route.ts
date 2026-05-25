import { NextRequest, NextResponse } from "next/server";

import { performAdminLogin } from "@/lib/admin-login";
import {
  ADMIN_SESSION_COOKIE_NAME,
  getAdminSessionCookieOptions,
} from "@/lib/admin-session";
import { toErrorMessage } from "@/lib/error-utils";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

export const runtime = "nodejs";

type LoginPayload = {
  username: string;
  password: string;
};

function parseLoginPayload(payload: unknown): LoginPayload | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const username = (payload as { username?: unknown }).username;
  const password = (payload as { password?: unknown }).password;
  if (typeof username !== "string" || typeof password !== "string") {
    return null;
  }
  const normalized = { username: username.trim(), password };
  if (!normalized.username || !normalized.password) {
    return null;
  }
  return normalized;
}

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
    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Request body must be valid JSON" },
      { status: 400 },
    );
  }

  const parsed = parseLoginPayload(payload);
  if (!parsed) {
    return NextResponse.json(
      { error: "Invalid login payload" },
      { status: 400 },
    );
  }

  try {
    const result = await performAdminLogin(parsed.username, parsed.password);
    if (!result.ok) {
      return NextResponse.json(
        { error: result.error },
        {
          status: result.status,
          headers: result.retryAfterSeconds
            ? { "Retry-After": String(result.retryAfterSeconds) }
            : undefined,
        },
      );
    }

    const response = NextResponse.json({ ok: true });
    response.cookies.set(
      ADMIN_SESSION_COOKIE_NAME,
      result.token,
      getAdminSessionCookieOptions(),
    );
    return response;
  } catch (error) {
    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}
