import "server-only";

import { NextRequest } from "next/server";

import { toErrorMessage } from "@/lib/error-utils";

type ApiLogValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | ApiLogValue[]
  | { [key: string]: ApiLogValue };

export type ApiLogFields = Record<string, ApiLogValue>;

const REDACTED = "[REDACTED]";
const MAX_TEXT_LENGTH = 500;
const SENSITIVE_FIELD_PATTERN =
  /(^|[_-])(authorization|cookie|password|secret|token|api[_-]?key|pat|session|credential)([_-]|$)/i;
const SENSITIVE_TEXT_PATTERNS = [
  /Bearer\s+[A-Za-z0-9._~+/=-]+/gi,
  /(authorization|api[_-]?key|token|secret|password)=([^\s&]+)/gi,
];

function errorType(error: unknown): string {
  if (error instanceof Error && error.name) {
    if (error.name !== "Error") {
      return error.name;
    }
    return error.constructor.name || error.name;
  }
  return typeof error;
}

function sanitizeText(value: string): string {
  let sanitized = value;
  for (const pattern of SENSITIVE_TEXT_PATTERNS) {
    sanitized = sanitized.replace(pattern, (match, key) =>
      typeof key === "string" ? `${key}=${REDACTED}` : REDACTED,
    );
  }
  if (sanitized.length > MAX_TEXT_LENGTH) {
    return `${sanitized.slice(0, MAX_TEXT_LENGTH)}...`;
  }
  return sanitized;
}

function sanitizeValue(field: string, value: ApiLogValue): ApiLogValue {
  if (value === undefined) {
    return undefined;
  }
  if (SENSITIVE_FIELD_PATTERN.test(field)) {
    return REDACTED;
  }
  if (typeof value === "string") {
    return sanitizeText(value);
  }
  if (Array.isArray(value)) {
    return value.slice(0, 20).map((item) => sanitizeValue(field, item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [
        key,
        sanitizeValue(key, nested),
      ]),
    );
  }
  return value;
}

export function getApiRequestId(request: NextRequest): string {
  const incoming = request.headers.get("x-request-id")?.trim();
  if (incoming) {
    return sanitizeText(incoming).slice(0, 128);
  }
  return (
    globalThis.crypto?.randomUUID?.() ??
    `req_${Date.now()}_${Math.random().toString(36).slice(2)}`
  );
}

export function elapsedMs(startedAtMs: number): number {
  return Math.max(0, Date.now() - startedAtMs);
}

export function withApiRequestId<T extends Response>(
  response: T,
  requestId: string,
): T {
  response.headers.set("x-request-id", requestId);
  return response;
}

export function sanitizeApiLogFields(fields: ApiLogFields): ApiLogFields {
  return Object.fromEntries(
    Object.entries(fields)
      .map(([key, value]) => [key, sanitizeValue(key, value)])
      .filter(([, value]) => value !== undefined),
  );
}

export function logApiInfo(fields: ApiLogFields): void {
  console.info(sanitizeApiLogFields({ component: "web", ...fields }));
}

export function logApiWarn(fields: ApiLogFields): void {
  console.warn(sanitizeApiLogFields({ component: "web", ...fields }));
}

export function logApiError(error: unknown, fields: ApiLogFields): void {
  console.error(
    sanitizeApiLogFields({
      component: "web",
      ...fields,
      error_type: errorType(error),
      error_message: toErrorMessage(error),
    }),
  );
}
