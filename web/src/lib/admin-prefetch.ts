import "server-only";

import { cookies, headers } from "next/headers";

import { getAdminCredentialVersion } from "@/lib/admin-auth";
import {
  ADMIN_SESSION_COOKIE_NAME,
  verifyAdminSessionToken,
} from "@/lib/admin-session";
import { assertLocalRequest } from "@/lib/local-request-guard";

export async function hasValidAdminSession(): Promise<boolean> {
  const headerStore = await headers();
  try {
    assertLocalRequest({ headers: headerStore, method: "GET" });
  } catch {
    return false;
  }

  const cookieStore = await cookies();
  const token = cookieStore.get(ADMIN_SESSION_COOKIE_NAME)?.value;
  if (!token) {
    return false;
  }

  try {
    const credentialVersion = await getAdminCredentialVersion();
    return await verifyAdminSessionToken(token, credentialVersion);
  } catch {
    return false;
  }
}
