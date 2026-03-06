import { cookies, headers } from "next/headers";

import { requireAdminAuth } from "@/lib/admin-auth";
import { assertLocalRequest } from "@/lib/local-request-guard";
import { assertSameOrigin } from "@/lib/same-origin";

const ACTION_METHOD = "POST";

export async function requireAdminActionRequest(): Promise<
  Awaited<ReturnType<typeof headers>>
> {
  const headerStore = await headers();
  assertSameOrigin({ headers: headerStore });
  assertLocalRequest({ headers: headerStore, method: ACTION_METHOD });
  return headerStore;
}

export async function requireAdminActionSession(): Promise<void> {
  const [headerStore, cookieStore] = await Promise.all([
    requireAdminActionRequest(),
    cookies(),
  ]);
  await requireAdminAuth({
    headers: headerStore,
    cookies: cookieStore,
  });
}
