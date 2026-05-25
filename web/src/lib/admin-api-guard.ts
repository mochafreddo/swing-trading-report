import { NextRequest, NextResponse } from "next/server";

import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { toErrorMessage } from "@/lib/error-utils";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";

type JsonResponseInit = {
  status?: number;
  headers?: HeadersInit;
};

export type ApiJsonResponder = (
  payload: unknown,
  init?: JsonResponseInit,
) => NextResponse;

const defaultJsonResponder: ApiJsonResponder = (payload, init) =>
  NextResponse.json(payload, init);

export async function requireAdminApiGuard(
  request: NextRequest,
): Promise<void> {
  await requireAdminAuth(request);
  assertSameOrigin(request);
  assertLocalRequest(request);
}

export function toAdminApiGuardErrorResponse(
  error: unknown,
  json: ApiJsonResponder = defaultJsonResponder,
): NextResponse {
  if (error instanceof AdminAuthError) {
    return json(
      { error: error.message },
      { status: error.status, headers: error.headers },
    );
  }
  if (error instanceof SameOriginError) {
    return json({ error: error.message }, { status: error.status });
  }
  if (error instanceof LocalRequestGuardError) {
    return json({ error: error.message }, { status: error.status });
  }

  return json({ error: toErrorMessage(error) }, { status: 500 });
}

export async function enforceAdminApiGuard(
  request: NextRequest,
  json?: ApiJsonResponder,
): Promise<NextResponse | null> {
  try {
    await requireAdminApiGuard(request);
    return null;
  } catch (error) {
    return toAdminApiGuardErrorResponse(error, json);
  }
}
