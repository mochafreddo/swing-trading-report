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

function stubSessionSecret(): void {
  vi.stubEnv("SAB_SESSION_SECRET", "x".repeat(32));
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("admin-session", () => {
  it("creates and verifies signed session token", async () => {
    stubSessionSecret();
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
    stubSessionSecret();
    const credentialVersion = await buildAdminCredentialVersion("sab", "pass");
    const token = await createAdminSessionToken({ credentialVersion });
    const tampered = `${token}x`;

    await expect(
      verifyAdminSessionToken(tampered, credentialVersion),
    ).resolves.toBe(false);
  });

  it("rejects expired session token", async () => {
    stubSessionSecret();
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
    stubSessionSecret();
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

  it("allows local production deployments to disable secure session cookies", () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("SAB_SESSION_COOKIE_SECURE", "false");

    expect(getAdminSessionCookieOptions()).toMatchObject({
      secure: false,
    });
  });
});
