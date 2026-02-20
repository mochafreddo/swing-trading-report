export const ADMIN_SESSION_COOKIE_NAME = "sab_admin_session";
export const ADMIN_SESSION_TTL_SECONDS = 60 * 60 * 12;

type SessionPayload = {
  v: "v1";
  exp: number;
  nonce: string;
  cv: string;
};

type CookieAccessor = {
  get(name: string): string | { value: string } | undefined;
};

export type SessionRequest = {
  headers: Pick<Headers, "get">;
  cookies?: CookieAccessor;
};

type CreateAdminSessionTokenOptions = {
  credentialVersion: string;
  now?: number;
};

export class AdminSessionConfigError extends Error {
  readonly status = 500;

  constructor(message = "Admin session is not configured") {
    super(message);
  }
}

function requireSessionSecret(): string {
  const secret = process.env.SAB_SESSION_SECRET?.trim() ?? "";
  if (!secret || secret.length < 32) {
    throw new AdminSessionConfigError(
      "SAB_SESSION_SECRET is required and must be at least 32 characters.",
    );
  }
  return secret;
}

function bytesToBase64Url(bytes: Uint8Array): string {
  let base64: string;
  if (typeof btoa === "function") {
    let binary = "";
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    base64 = btoa(binary);
  } else {
    const bufferCtor = (globalThis as unknown as { Buffer?: typeof Buffer })
      .Buffer;
    if (!bufferCtor) {
      throw new Error("Base64 encoding is unavailable in this runtime");
    }
    base64 = bufferCtor.from(bytes).toString("base64");
  }

  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value: string): Uint8Array | null {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");

  try {
    if (typeof atob === "function") {
      const binary = atob(padded);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
      }
      return bytes;
    }
  } catch {
    return null;
  }

  try {
    const bufferCtor = (globalThis as unknown as { Buffer?: typeof Buffer })
      .Buffer;
    if (!bufferCtor) {
      return null;
    }
    return Uint8Array.from(bufferCtor.from(padded, "base64"));
  } catch {
    return null;
  }
}

function parseCookieHeader(cookieHeader: string): Record<string, string> {
  const parsed: Record<string, string> = {};
  for (const item of cookieHeader.split(";")) {
    const [rawName, ...rest] = item.split("=");
    const name = rawName?.trim();
    if (!name || rest.length === 0) {
      continue;
    }
    const value = rest.join("=").trim();
    parsed[name] = value;
  }
  return parsed;
}

function randomNonceHex(byteLength = 16): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

async function importSessionKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

async function signPayload(
  payload: string,
  secret: string,
): Promise<Uint8Array> {
  const key = await importSessionKey(secret);
  const signed = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(payload),
  );
  return new Uint8Array(signed);
}

async function verifyPayloadSignature(
  payloadBase64Url: string,
  signature: Uint8Array,
  secret: string,
): Promise<boolean> {
  const key = await importSessionKey(secret);
  const signatureCopy = new Uint8Array(signature.byteLength);
  signatureCopy.set(signature);
  return crypto.subtle.verify(
    "HMAC",
    key,
    signatureCopy,
    new TextEncoder().encode(payloadBase64Url),
  );
}

export function readAdminSessionToken(request: SessionRequest): string | null {
  const cookieFromAccessor = request.cookies?.get(ADMIN_SESSION_COOKIE_NAME);
  if (typeof cookieFromAccessor === "string") {
    return cookieFromAccessor || null;
  }
  if (cookieFromAccessor && typeof cookieFromAccessor.value === "string") {
    return cookieFromAccessor.value || null;
  }

  const cookieHeader = request.headers.get("cookie");
  if (!cookieHeader) {
    return null;
  }
  const parsed = parseCookieHeader(cookieHeader);
  return parsed[ADMIN_SESSION_COOKIE_NAME] ?? null;
}

export async function buildAdminCredentialVersion(
  username: string,
  password: string,
): Promise<string> {
  const signature = await signPayload(
    `${username}\u0000${password}`,
    requireSessionSecret(),
  );
  return bytesToBase64Url(signature);
}

export async function createAdminSessionToken(
  options: CreateAdminSessionTokenOptions,
): Promise<string> {
  const credentialVersion = options.credentialVersion.trim();
  if (!credentialVersion) {
    throw new AdminSessionConfigError("Credential version is required.");
  }

  const now = options.now ?? Date.now();
  const payload: SessionPayload = {
    v: "v1",
    exp: Math.floor(now / 1000) + ADMIN_SESSION_TTL_SECONDS,
    nonce: randomNonceHex(),
    cv: credentialVersion,
  };

  const payloadBase64Url = bytesToBase64Url(
    new TextEncoder().encode(JSON.stringify(payload)),
  );
  const signature = await signPayload(payloadBase64Url, requireSessionSecret());
  return `${payloadBase64Url}.${bytesToBase64Url(signature)}`;
}

export async function verifyAdminSessionToken(
  token: string,
  expectedCredentialVersion: string,
  now = Date.now(),
): Promise<boolean> {
  const credentialVersion = expectedCredentialVersion.trim();
  if (!credentialVersion) {
    return false;
  }

  const [payloadBase64Url, signatureBase64Url, ...rest] = token.split(".");
  if (!payloadBase64Url || !signatureBase64Url || rest.length > 0) {
    return false;
  }

  const signature = base64UrlToBytes(signatureBase64Url);
  if (!signature) {
    return false;
  }

  const secret = requireSessionSecret();
  const signatureValid = await verifyPayloadSignature(
    payloadBase64Url,
    signature,
    secret,
  );
  if (!signatureValid) {
    return false;
  }

  const payloadBytes = base64UrlToBytes(payloadBase64Url);
  if (!payloadBytes) {
    return false;
  }

  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(payloadBytes));
  } catch {
    return false;
  }

  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return false;
  }
  const parsed = payload as Partial<SessionPayload>;
  if (
    parsed.v !== "v1" ||
    typeof parsed.exp !== "number" ||
    typeof parsed.cv !== "string"
  ) {
    return false;
  }
  if (parsed.cv !== credentialVersion) {
    return false;
  }

  return parsed.exp > Math.floor(now / 1000);
}

export function getAdminSessionCookieOptions(
  maxAge = ADMIN_SESSION_TTL_SECONDS,
) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}
