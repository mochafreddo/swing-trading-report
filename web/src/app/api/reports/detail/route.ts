import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { InvalidReportKeyError, readReportDetail } from "@/lib/reports-data";
import { reportDetailQuerySchema } from "@/lib/schemas";
import { SupabaseApiError } from "@/lib/supabase-admin";

export const runtime = "nodejs";
const REPORTS_CACHE_CONTROL = "private, no-store, max-age=0, must-revalidate";

function jsonWithNoStore(
  payload: unknown,
  init?: {
    status?: number;
    headers?: HeadersInit;
  },
): NextResponse {
  const headers = new Headers(init?.headers);
  headers.set("Cache-Control", REPORTS_CACHE_CONTROL);
  return NextResponse.json(payload, {
    status: init?.status,
    headers,
  });
}

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request, jsonWithNoStore);
  if (guardError) {
    return guardError;
  }

  const query = reportDetailQuerySchema.safeParse({
    key: request.nextUrl.searchParams.get("key") ?? undefined,
    refresh: request.nextUrl.searchParams.get("refresh") ?? undefined,
  });

  if (!query.success) {
    return jsonWithNoStore(
      {
        error: "Invalid query parameters",
        details: query.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const payload = await readReportDetail(query.data.key, {
      refresh: query.data.refresh,
    });
    return jsonWithNoStore(payload);
  } catch (error) {
    if (error instanceof InvalidReportKeyError) {
      return jsonWithNoStore(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof SupabaseApiError && error.status === 404) {
      return jsonWithNoStore({ error: "Report not found" }, { status: 404 });
    }

    const message = error instanceof Error ? error.message : "Unknown error";
    return jsonWithNoStore({ error: message }, { status: 500 });
  }
}
