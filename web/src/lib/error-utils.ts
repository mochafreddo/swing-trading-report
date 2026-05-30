export function toErrorMessage(
  error: unknown,
  fallback: string = "Unknown error",
): string {
  return error instanceof Error ? error.message : fallback;
}

function asPayloadRecord(payload: unknown): Record<string, unknown> | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  return payload as Record<string, unknown>;
}

function readApiStringField(
  payload: unknown,
  field: string,
): string | undefined {
  const record = asPayloadRecord(payload);
  if (!record) {
    return undefined;
  }
  const value = record[field];
  return typeof value === "string" && value.trim() ? value : undefined;
}

export function readApiError(payload: unknown): string | undefined {
  return readApiStringField(payload, "error");
}

export function readApiErrorCode(payload: unknown): string | undefined {
  return readApiStringField(payload, "code");
}
