import { NextRequest, NextResponse } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import {
  buildHoldingsYamlDocument,
  buildHoldingsYamlImportSummary,
  HoldingsYamlError,
  parseHoldingsYamlDocument,
} from "@/lib/holdings-yaml";
import { holdingYamlImportRequestSchema } from "@/lib/schemas";
import {
  fetchAllHoldings,
  replaceAllHoldings,
  SupabaseApiError,
} from "@/lib/supabase-admin";
import type { HoldingsYamlImportResponse } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function toUnknownErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request);
  if (guardError) {
    return guardError;
  }

  try {
    const holdings = await fetchAllHoldings();
    const document = buildHoldingsYamlDocument(holdings);
    return new Response(document, {
      status: 200,
      headers: {
        "Content-Type": "application/yaml; charset=utf-8",
        "Content-Disposition": 'attachment; filename="holdings.yaml"',
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    if (error instanceof SupabaseApiError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    return NextResponse.json(
      { error: toUnknownErrorMessage(error) },
      { status: 500 },
    );
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

  const parsedRequest = holdingYamlImportRequestSchema.safeParse(payload);
  if (!parsedRequest.success) {
    return NextResponse.json(
      {
        error: "Invalid holdings YAML import payload",
        details: parsedRequest.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const importedHoldings = parseHoldingsYamlDocument(
      parsedRequest.data.document,
    );
    const currentHoldings = await fetchAllHoldings();
    const summary = buildHoldingsYamlImportSummary(
      currentHoldings,
      importedHoldings,
    );

    if (parsedRequest.data.apply) {
      const hasChanges =
        summary.createCount > 0 ||
        summary.updateCount > 0 ||
        summary.deleteCount > 0;
      if (hasChanges) {
        const result = await replaceAllHoldings(importedHoldings);
        const appliedResponse: HoldingsYamlImportResponse = {
          mode: "apply",
          summary: {
            ...summary,
            createCount: result.insertedCount,
            updateCount: result.updatedCount,
            deleteCount: result.deletedCount,
            unchangedCount: result.unchangedCount,
          },
        };
        return NextResponse.json(appliedResponse);
      }
    }

    const response: HoldingsYamlImportResponse = {
      mode: parsedRequest.data.apply ? "apply" : "dry-run",
      summary,
    };
    return NextResponse.json(response);
  } catch (error) {
    if (error instanceof HoldingsYamlError) {
      return NextResponse.json({ error: error.message }, { status: 400 });
    }
    if (error instanceof SupabaseApiError) {
      return NextResponse.json(
        { error: error.message },
        { status: error.status },
      );
    }
    return NextResponse.json(
      { error: toUnknownErrorMessage(error) },
      { status: 500 },
    );
  }
}
