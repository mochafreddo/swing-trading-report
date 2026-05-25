import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { toErrorMessage } from "@/lib/error-utils";
import {
  decodeHoldingCursor,
  HoldingCursorError,
} from "@/lib/holdings-pagination";
import { holdingCreateSchema, holdingListQuerySchema } from "@/lib/schemas";
import {
  createHolding,
  fetchHoldingsPage,
  SupabaseApiError,
} from "@/lib/supabase-admin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  try {
    const parsedQuery = holdingListQuerySchema.safeParse({
      limit: request.nextUrl.searchParams.get("limit") ?? undefined,
      cursor: request.nextUrl.searchParams.get("cursor") ?? undefined,
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

    const cursor = parsedQuery.data.cursor
      ? decodeHoldingCursor(parsedQuery.data.cursor)
      : undefined;

    const page = await fetchHoldingsPage({
      limit: parsedQuery.data.limit,
      cursor,
    });
    return NextResponse.json(page);
  } catch (error) {
    if (error instanceof HoldingCursorError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof SupabaseApiError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Request body must be valid JSON" },
      { status: 400 },
    );
  }

  const parsed = holdingCreateSchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: "Invalid holding payload",
        details: parsed.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const created = await createHolding(parsed.data);
    return NextResponse.json(created, { status: 201 });
  } catch (error) {
    if (error instanceof SupabaseApiError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }

    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}
