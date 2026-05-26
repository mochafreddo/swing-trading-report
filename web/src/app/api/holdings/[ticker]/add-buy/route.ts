import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { ADD_BUY_IDEMPOTENCY_MISMATCH_CODE } from "@/lib/add-buy-idempotency";
import { toErrorMessage } from "@/lib/error-utils";
import { normalizeHoldingTickerForMutation } from "@/lib/holding-ticker";
import { isValidIdempotencyKey } from "@/lib/idempotency-key";
import { parseJsonBody } from "@/lib/parse-json-body";
import { holdingAddBuySchema, holdingTickerSchema } from "@/lib/schemas";
import { addBuyToHolding, SupabaseApiError } from "@/lib/supabase-admin";

export const runtime = "nodejs";

type RouteContext = {
  params: { ticker: string } | Promise<{ ticker: string }>;
};

type ParsedIdempotencyKeyHeader = {
  key: string | null;
  invalid: boolean;
};

function parseIdempotencyKeyHeader(
  request: NextRequest,
): ParsedIdempotencyKeyHeader {
  const raw = request.headers.get("idempotency-key");
  if (!raw) {
    return { key: null, invalid: false };
  }
  const key = raw.trim();
  if (!key) {
    return { key: null, invalid: false };
  }
  if (!isValidIdempotencyKey(key)) {
    return { key: null, invalid: true };
  }
  return { key, invalid: false };
}

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

export async function POST(request: NextRequest, context: RouteContext) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  const params = await context.params;
  const ticker = parseTickerParam(params.ticker);
  if (!ticker) {
    return NextResponse.json({ error: "Invalid ticker" }, { status: 400 });
  }

  const body = await parseJsonBody(request);
  if (!body.ok) {
    return body.response;
  }

  const parsed = holdingAddBuySchema.safeParse(body.payload);
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: "Invalid holding add-buy payload",
        details: parsed.error.flatten(),
      },
      { status: 400 },
    );
  }

  const idempotencyKeyHeader = parseIdempotencyKeyHeader(request);
  if (!idempotencyKeyHeader.key) {
    return NextResponse.json(
      {
        error: idempotencyKeyHeader.invalid
          ? "Invalid Idempotency-Key header"
          : "Missing Idempotency-Key header",
      },
      { status: 400 },
    );
  }

  try {
    const updated = await addBuyToHolding(
      ticker,
      parsed.data,
      idempotencyKeyHeader.key,
    );
    if (!updated) {
      return NextResponse.json({ error: "Holding not found" }, { status: 404 });
    }
    return NextResponse.json(updated);
  } catch (error) {
    if (error instanceof SupabaseApiError) {
      if (
        error.status === 409 &&
        error.code === ADD_BUY_IDEMPOTENCY_MISMATCH_CODE
      ) {
        return NextResponse.json(
          {
            error: error.message,
            code: ADD_BUY_IDEMPOTENCY_MISMATCH_CODE,
          },
          { status: error.status },
        );
      }
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    return NextResponse.json({ error: toErrorMessage(error) }, { status: 500 });
  }
}
