import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { recentBuyCandidatesQuerySchema } from "@/lib/schemas";
import { listRecentBuyCandidates } from "@/lib/ticker-directory";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
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
