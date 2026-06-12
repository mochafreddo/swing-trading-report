import "server-only";

import { NextResponse } from "next/server";

import { toErrorMessage } from "@/lib/error-utils";
import { SupabaseApiError } from "@/lib/supabase-admin";

export function holdingsStatusCode(error: unknown): number {
  return error instanceof SupabaseApiError ? error.status : 500;
}

export function holdingsDependency(error: unknown): string | undefined {
  return error instanceof SupabaseApiError ? "supabase" : undefined;
}

export function holdingsJsonError(error: unknown): NextResponse {
  if (error instanceof SupabaseApiError) {
    return NextResponse.json(
      { error: error.message },
      { status: error.status },
    );
  }
  return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
}
