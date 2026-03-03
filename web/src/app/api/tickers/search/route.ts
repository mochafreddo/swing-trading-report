import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { tickerSearchQuerySchema } from "@/lib/schemas";
import { searchTickerDirectory } from "@/lib/ticker-directory";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  const parsedQuery = tickerSearchQuerySchema.safeParse({
    q: request.nextUrl.searchParams.get("q") ?? "",
    limit: request.nextUrl.searchParams.get("limit") ?? undefined,
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
    const payload = await searchTickerDirectory({
      q: parsedQuery.data.q,
      limit: parsedQuery.data.limit,
    });
    return NextResponse.json(payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
