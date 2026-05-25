import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { toErrorMessage } from "@/lib/error-utils";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import { holdingPatchSchema, holdingTickerSchema } from "@/lib/schemas";
import {
  deleteHolding,
  SupabaseApiError,
  updateHolding,
} from "@/lib/supabase-admin";

export const runtime = "nodejs";

type RouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

function parseTickerParam(rawTicker: string): string | null {
  const candidate = (() => {
    try {
      return decodeURIComponent(rawTicker);
    } catch {
      return rawTicker;
    }
  })();
  const parsed = holdingTickerSchema.safeParse(candidate);
  return parsed.success ? normalizeHoldingTickerForMutation(parsed.data) : null;
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  const params = await context.params;
  const ticker = parseTickerParam(params.ticker);
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
    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  const params = await context.params;
  const ticker = parseTickerParam(params.ticker);
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
    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}
