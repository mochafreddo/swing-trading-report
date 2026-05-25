"use server";

import { cookies } from "next/headers";

import { requireAdminActionRequest } from "@/lib/admin-action-auth";
import { performAdminLogin } from "@/lib/admin-login";
import {
  ADMIN_SESSION_COOKIE_NAME,
  getAdminSessionCookieOptions,
} from "@/lib/admin-session";
import { toErrorMessage } from "@/lib/error-utils";

export type AuthActionResult =
  | {
      ok: true;
    }
  | {
      ok: false;
      error: string;
    };

export interface LoginActionInput {
  username: string;
  password: string;
}

export async function loginAction(
  input: LoginActionInput,
): Promise<AuthActionResult> {
  try {
    await requireAdminActionRequest();
    const result = await performAdminLogin(input.username, input.password);
    if (!result.ok) {
      return {
        ok: false,
        error: result.error,
      };
    }

    const cookieStore = await cookies();
    cookieStore.set(
      ADMIN_SESSION_COOKIE_NAME,
      result.token,
      getAdminSessionCookieOptions(),
    );

    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      error: toErrorMessage(error),
    };
  }
}

export async function logoutAction(): Promise<AuthActionResult> {
  try {
    await requireAdminActionRequest();

    const cookieStore = await cookies();
    cookieStore.set(
      ADMIN_SESSION_COOKIE_NAME,
      "",
      getAdminSessionCookieOptions(0),
    );
    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      error: toErrorMessage(error),
    };
  }
}
