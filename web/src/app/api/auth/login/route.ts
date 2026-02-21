import { NextRequest, NextResponse } from "next/server";

import {
  getAdminCredentialVersion,
  validateAdminCredentials,
} from "@/lib/admin-auth";
import {
  ADMIN_SESSION_COOKIE_NAME,
  createAdminSessionToken,
  getAdminSessionCookieOptions,
} from "@/lib/admin-session";
import {
  assertLoginAttemptAllowed,
  buildGlobalLoginThrottleKey,
  buildLoginThrottleKey,
  clearLoginAttemptFailures,
  LoginThrottleError,
  recordLoginAttemptFailure,
} from "@/lib/login-throttle";
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

async function clearLoginThrottleKeysBestEffort(
  throttleKeys: string[],
): Promise<void> {
  for (const throttleKey of throttleKeys) {
    try {
      await clearLoginAttemptFailures(throttleKey);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      console.warn(
        `Failed to clear login throttle state after successful login: ${message}`,
      );
    }
  }
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
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
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

  const throttleKeys = Array.from(
    new Set([
      buildGlobalLoginThrottleKey(),
      buildLoginThrottleKey(parsed.username),
    ]),
  );
  try {
    for (const throttleKey of throttleKeys) {
      await assertLoginAttemptAllowed(throttleKey);
    }
  } catch (error) {
    if (error instanceof LoginThrottleError) {
      return NextResponse.json(
        { error: error.message },
        {
          status: error.status,
          headers: { "Retry-After": String(error.retryAfterSeconds) },
        },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  if (!validateAdminCredentials(parsed.username, parsed.password)) {
    try {
      for (const throttleKey of throttleKeys) {
        await recordLoginAttemptFailure(throttleKey);
      }
    } catch (error) {
      if (error instanceof LoginThrottleError) {
        return NextResponse.json(
          { error: error.message },
          {
            status: error.status,
            headers: { "Retry-After": String(error.retryAfterSeconds) },
          },
        );
      }
      const message = error instanceof Error ? error.message : "Unknown error";
      return NextResponse.json({ error: message }, { status: 500 });
    }
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let token: string;
  try {
    const credentialVersion = await getAdminCredentialVersion();
    token = await createAdminSessionToken({ credentialVersion });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  await clearLoginThrottleKeysBestEffort(throttleKeys);

  const response = NextResponse.json({ ok: true });
  response.cookies.set(
    ADMIN_SESSION_COOKIE_NAME,
    token,
    getAdminSessionCookieOptions(),
  );
  return response;
}
