import {
  buildAdminCredentialVersion,
  readAdminSessionToken,
  type SessionRequest,
  verifyAdminSessionToken,
} from "./admin-session";

export class AdminAuthError extends Error {
  readonly status = 401;
  readonly headers: HeadersInit;

  constructor(message = "Unauthorized") {
    super(message);
    this.headers = {};
  }
}

export class AdminAuthConfigError extends Error {
  readonly status = 500;

  constructor(message = "Admin auth is not configured") {
    super(message);
  }
}

export type AdminBasicAuth = Readonly<{
  username: string;
  password: string;
}>;

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let result = 0;
  for (let i = 0; i < a.length; i += 1) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

function decodeBase64(value: string): string | null {
  try {
    if (typeof atob === "function") {
      return atob(value);
    }
  } catch {
    // fallthrough
  }

  try {
    const bufferCtor = (globalThis as unknown as { Buffer?: typeof Buffer })
      .Buffer;
    if (!bufferCtor) {
      return null;
    }
    return bufferCtor.from(value, "base64").toString("utf-8");
  } catch {
    return null;
  }
}

function parseBasicAuthorization(
  header: string | null,
): { username: string; password: string } | null {
  if (!header) {
    return null;
  }

  const match = header.match(/^Basic\s+(.+)$/i);
  if (!match) {
    return null;
  }

  const decoded = decodeBase64(match[1] ?? "");
  if (!decoded) {
    return null;
  }

  const separator = decoded.indexOf(":");
  if (separator < 0) {
    return null;
  }

  const username = decoded.slice(0, separator);
  const password = decoded.slice(separator + 1);
  return { username, password };
}

export function loadAdminBasicAuthEnv(): AdminBasicAuth {
  const username = process.env.SAB_BASIC_AUTH_USER?.trim() ?? "";
  const password = process.env.SAB_BASIC_AUTH_PASS?.trim() ?? "";

  if (!username || !password) {
    throw new AdminAuthConfigError(
      "SAB basic auth is required (SAB_BASIC_AUTH_USER/SAB_BASIC_AUTH_PASS).",
    );
  }

  return { username, password };
}

export function validateAdminCredentials(
  username: string,
  password: string,
): boolean {
  const expected = loadAdminBasicAuthEnv();
  return (
    constantTimeEqual(username, expected.username) &&
    constantTimeEqual(password, expected.password)
  );
}

export function parseBasicAuthHeader(
  header: string | null,
): { username: string; password: string } | null {
  return parseBasicAuthorization(header);
}

export async function getAdminCredentialVersion(): Promise<string> {
  const expected = loadAdminBasicAuthEnv();
  return buildAdminCredentialVersion(expected.username, expected.password);
}

export async function requireAdminAuth(request: SessionRequest): Promise<void> {
  const token = readAdminSessionToken(request);
  if (!token) {
    throw new AdminAuthError();
  }

  const credentialVersion = await getAdminCredentialVersion();
  const valid = await verifyAdminSessionToken(token, credentialVersion);
  if (!valid) {
    throw new AdminAuthError();
  }
}
