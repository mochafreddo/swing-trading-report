import "server-only";

import { type NextResponse } from "next/server";

import { toErrorMessage } from "@/lib/error-utils";
import { jsonWithNoStore } from "@/lib/reports-response";
import { SupabaseApiError } from "@/lib/supabase-admin";

export function holdingsStatusCode(error: unknown): number {
  return error instanceof SupabaseApiError ? error.status : 500;
}

export function holdingsDependency(error: unknown): string | undefined {
  return error instanceof SupabaseApiError ? "supabase" : undefined;
}

export function holdingsJsonError(error: unknown): NextResponse {
  if (error instanceof SupabaseApiError) {
    return jsonWithNoStore({ error: error.message }, { status: error.status });
  }
  return jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 });
}
