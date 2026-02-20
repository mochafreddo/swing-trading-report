import { NextRequest, NextResponse } from "next/server";

import {
  assertLocalRequest,
  LocalRequestGuardError,
} from "@/lib/local-request-guard";
import { AdminAuthError, requireAdminAuth } from "@/lib/admin-auth";
import { assertSameOrigin, SameOriginError } from "@/lib/same-origin";
import { holdingPatchSchema } from "@/lib/schemas";
import {
  deleteHolding,
  SupabaseApiError,
  updateHolding,
} from "@/lib/supabase-admin";

export const runtime = "nodejs";

type RouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

function parseTicker(raw: string): string | null {
  const decoded = decodeURIComponent(raw).trim();
  if (!decoded) {
    return null;
  }
  return decoded.toUpperCase();
}

export async function PATCH(request: NextRequest, context: RouteContext) {
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

  const params = await context.params;
  const ticker = parseTicker(params.ticker);
  if (!ticker) {
    return NextResponse.json({ error: "Invalid ticker" }, { status: 400 });
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

  const parsed = holdingPatchSchema.safeParse(payload);
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: "Invalid holding patch payload",
        details: parsed.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const updated = await updateHolding(ticker, parsed.data);
    if (!updated) {
      return NextResponse.json({ error: "Holding not found" }, { status: 404 });
    }
    return NextResponse.json(updated);
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

export async function DELETE(request: NextRequest, context: RouteContext) {
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

  const params = await context.params;
  const ticker = parseTicker(params.ticker);
  if (!ticker) {
    return NextResponse.json({ error: "Invalid ticker" }, { status: 400 });
  }

  try {
    const deleted = await deleteHolding(ticker);
    if (!deleted) {
      return NextResponse.json({ error: "Holding not found" }, { status: 404 });
    }
    return NextResponse.json({ deleted: true, ticker });
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
