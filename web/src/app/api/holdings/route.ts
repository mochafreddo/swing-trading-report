import { NextRequest, NextResponse } from "next/server";

import {
  decodeHoldingCursor,
  HoldingCursorError,
} from "@/lib/holdings-pagination";
import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { holdingCreateSchema, holdingListQuerySchema } from "@/lib/schemas";
import {
  createHolding,
  fetchHoldingsPage,
  SupabaseApiError,
} from "@/lib/supabase-admin";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    await requireAdminAuth(request);
    assertSameOrigin(request);
    assertLocalRequest(request);

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
    if (error instanceof HoldingCursorError) {
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
    if (error instanceof SupabaseApiError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
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

    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
