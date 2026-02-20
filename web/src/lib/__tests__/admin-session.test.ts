import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ADMIN_SESSION_COOKIE_NAME,
  ADMIN_SESSION_TTL_SECONDS,
  buildAdminCredentialVersion,
  createAdminSessionToken,
  getAdminSessionCookieOptions,
  readAdminSessionToken,
  verifyAdminSessionToken,
} from "@/lib/admin-session";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("admin-session", () => {
  it("creates and verifies signed session token", async () => {
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    const credentialVersion = await buildAdminCredentialVersion("sab", "pass");
    const token = await createAdminSessionToken({
      credentialVersion,
      now: 1_700_000_000_000,
    });

    await expect(
      verifyAdminSessionToken(token, credentialVersion, 1_700_000_001_000),
    ).resolves.toBe(true);
  });

  it("rejects tampered session token", async () => {
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    const credentialVersion = await buildAdminCredentialVersion("sab", "pass");
    const token = await createAdminSessionToken({ credentialVersion });
    const tampered = `${token}x`;

    await expect(
      verifyAdminSessionToken(tampered, credentialVersion),
    ).resolves.toBe(false);
  });

  it("rejects expired session token", async () => {
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    const issuedAt = 1_700_000_000_000;
    const credentialVersion = await buildAdminCredentialVersion("sab", "pass");
    const token = await createAdminSessionToken({
      credentialVersion,
      now: issuedAt,
    });
    const now = issuedAt + (ADMIN_SESSION_TTL_SECONDS + 1) * 1_000;

    await expect(
      verifyAdminSessionToken(token, credentialVersion, now),
    ).resolves.toBe(false);
  });

  it("rejects token when credential version mismatches", async () => {
    vi.stubEnv("SAB_SESSION_SECRET", "0123456789abcdef0123456789abcdef");
    const tokenVersion = await buildAdminCredentialVersion("sab", "pass");
    const otherVersion = await buildAdminCredentialVersion("sab", "next-pass");
    const token = await createAdminSessionToken({
      credentialVersion: tokenVersion,
    });

    await expect(verifyAdminSessionToken(token, otherVersion)).resolves.toBe(
      false,
    );
  });

  it("reads session token from cookie header", () => {
    const token = "signed-token";
    const request = {
      headers: new Headers({ cookie: `${ADMIN_SESSION_COOKIE_NAME}=${token}` }),
    };

    expect(readAdminSessionToken(request)).toBe(token);
  });

  it("returns cookie options with fixed policy", () => {
    vi.stubEnv("NODE_ENV", "development");
    expect(getAdminSessionCookieOptions()).toMatchObject({
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: false,
      maxAge: ADMIN_SESSION_TTL_SECONDS,
    });
  });
});
