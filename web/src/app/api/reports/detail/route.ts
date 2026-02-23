import { NextRequest, NextResponse } from "next/server";

import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { InvalidReportKeyError, readReportDetail } from "@/lib/reports-data";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { reportDetailQuerySchema } from "@/lib/schemas";
import { SupabaseApiError } from "@/lib/supabase-admin";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  try {
    await requireAdminAuth(request);
    assertSameOrigin(request);
    assertLocalRequest(request);
  } catch (error) {
    if (error instanceof AdminAuthError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status, headers: error.headers },
      );
    }
    if (error instanceof SameOriginError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof LocalRequestGuardError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  const query = reportDetailQuerySchema.safeParse({
    key: request.nextUrl.searchParams.get("key") ?? undefined,
  });

  if (!query.success) {
    return NextResponse.json(
      {
        error: "Invalid query parameters",
        details: query.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const payload = await readReportDetail(query.data.key);
    return NextResponse.json(payload);
  } catch (error) {
    if (error instanceof InvalidReportKeyError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof SupabaseApiError && error.status === 404) {
      return NextResponse.json({ error: "Report not found" }, { status: 404 });
    }

    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
