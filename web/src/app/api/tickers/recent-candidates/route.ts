import { NextRequest, NextResponse } from "next/server";

import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { recentBuyCandidatesQuerySchema } from "@/lib/schemas";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { listRecentBuyCandidates } from "@/lib/ticker-directory";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

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

  const parsedQuery = recentBuyCandidatesQuerySchema.safeParse({
    limitReports: request.nextUrl.searchParams.get("limitReports") ?? undefined,
    limitCandidates:
      request.nextUrl.searchParams.get("limitCandidates") ?? undefined,
  });
  if (!parsedQuery.success) {
    return NextResponse.json(
      {
        error: "Invalid query parameters",
        details: parsedQuery.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const payload = await listRecentBuyCandidates({
      limitReports: parsedQuery.data.limitReports,
      limitCandidates: parsedQuery.data.limitCandidates,
    });
    return NextResponse.json(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
