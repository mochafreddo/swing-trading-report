import { NextRequest } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { toErrorMessage } from "@/lib/error-utils";
import { InvalidReportKeyError, readReportDetail } from "@/lib/reports-data";
import { jsonWithNoStore } from "@/lib/reports-response";
import { reportDetailQuerySchema } from "@/lib/schemas";
import { SupabaseApiError } from "@/lib/supabase-admin";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request, jsonWithNoStore);
  if (guardError) {
    return guardError;
  }

  const query = reportDetailQuerySchema.safeParse({
    key: request.nextUrl.searchParams.get("key") ?? undefined,
    refresh: request.nextUrl.searchParams.get("refresh") ?? undefined,
  });

  if (!query.success) {
    return jsonWithNoStore(
      {
        error: "Invalid query parameters",
        details: query.error.flatten(),
      },
      { status: 400 },
    );
  }

  try {
    const payload = await readReportDetail(query.data.key, {
      refresh: query.data.refresh,
    });
    return jsonWithNoStore(payload);
  } catch (error) {
    if (error instanceof InvalidReportKeyError) {
      return jsonWithNoStore(
        { error: error.message },
        { status: error.status },
      );
    }
    if (error instanceof SupabaseApiError && error.status === 404) {
      return jsonWithNoStore({ error: "Report not found" }, { status: 404 });
    }

    return jsonWithNoStore({ error: toErrorMessage(error) }, { status: 500 });
  }
}
