import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AdminAuthError,
  getAdminCredentialVersion,
  requireAdminAuth,
  validateAdminCredentials,
} from "@/lib/admin-auth";
import { createAdminSessionToken } from "@/lib/admin-session";

function makeRequest(cookieValue?: string): { headers: Headers } {
  const headers = new Headers();
  if (cookieValue) {
    headers.set("cookie", cookieValue);
  }
  return { headers };
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("admin-auth", () => {
  it("validates configured admin credentials", () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");

    expect(validateAdminCredentials("sab", "pass")).toBe(true);
    expect(validateAdminCredentials("sab", "wrong")).toBe(false);
  });

  it("accepts valid session cookie", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    const credentialVersion = await getAdminCredentialVersion();
    const token = await createAdminSessionToken({ credentialVersion });

    await expect(
      requireAdminAuth(makeRequest(`sab_admin_session=${token}`)),
    ).resolves.toBeUndefined();
  });

  it("rejects missing session cookie", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");

    await expect(requireAdminAuth(makeRequest())).rejects.toThrow(
      AdminAuthError,
    );
  });

  it("rejects invalid session cookie", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");

    await expect(
      requireAdminAuth(makeRequest("sab_admin_session=bad-token")),
    ).rejects.toThrow(AdminAuthError);
  });

  it("rejects old session when password changes", async () => {
    vi.stubEnv("SAB_BASIC_AUTH_USER", "sab");
    vi.stubEnv("SAB_BASIC_AUTH_PASS", "pass");
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    const credentialVersion = await getAdminCredentialVersion();
    const token = await createAdminSessionToken({ credentialVersion });

    vi.stubEnv("SAB_BASIC_AUTH_PASS", "changed-pass");

    await expect(
      requireAdminAuth(makeRequest(`sab_admin_session=${token}`)),
    ).rejects.toThrow(AdminAuthError);
  });
});
