import {
  getAdminCredentialVersion,
  validateAdminCredentials,
} from "@/lib/admin-auth";
import { createAdminSessionToken } from "@/lib/admin-session";
import {
  assertLoginAttemptAllowed,
  buildGlobalLoginThrottleKey,
  buildLoginThrottleKey,
  clearLoginAttemptFailures,
  LoginThrottleError,
  recordLoginAttemptFailure,
} from "@/lib/login-throttle";

export type AdminLoginResult =
  | {
      ok: true;
      token: string;
    }
  | {
      ok: false;
      error: string;
      status: number;
      retryAfterSeconds?: number;
    };

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

export async function performAdminLogin(
  username: string,
  password: string,
): Promise<AdminLoginResult> {
  const normalizedUsername = username.trim();
  if (!normalizedUsername || !password) {
    return {
      ok: false,
      error: "Invalid login payload",
      status: 400,
    };
  }

  const throttleKeys = Array.from(
    new Set([
      buildGlobalLoginThrottleKey(),
      buildLoginThrottleKey(normalizedUsername),
    ]),
  );

  try {
    for (const throttleKey of throttleKeys) {
      await assertLoginAttemptAllowed(throttleKey);
    }
  } catch (error) {
    if (error instanceof LoginThrottleError) {
      return {
        ok: false,
        error: error.message,
        status: error.status,
        retryAfterSeconds: error.retryAfterSeconds,
      };
    }

    throw error;
  }

  if (!validateAdminCredentials(normalizedUsername, password)) {
    try {
      for (const throttleKey of throttleKeys) {
        await recordLoginAttemptFailure(throttleKey);
      }
    } catch (error) {
      if (error instanceof LoginThrottleError) {
        return {
          ok: false,
          error: error.message,
          status: error.status,
          retryAfterSeconds: error.retryAfterSeconds,
        };
      }

      throw error;
    }

    return {
      ok: false,
      error: "Unauthorized",
      status: 401,
    };
  }

  const credentialVersion = await getAdminCredentialVersion();
  const token = await createAdminSessionToken({ credentialVersion });

  await clearLoginThrottleKeysBestEffort(throttleKeys);

  return {
    ok: true,
    token,
  };
}
