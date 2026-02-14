import { NextRequest, NextResponse } from "next/server";

import { getSupabaseEnv } from "@/lib/env.server";
import { parseReportStorageKey } from "@/lib/report-key";
import { reportDetailQuerySchema } from "@/lib/schemas";
import {
  downloadStorageJson,
  SupabaseApiError
} from "@/lib/supabase-admin";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const query = reportDetailQuerySchema.safeParse({
    key: request.nextUrl.searchParams.get("key") ?? undefined
  });

  if (!query.success) {
    return NextResponse.json(
      {
        error: "Invalid query parameters",
        details: query.error.flatten()
      },
      { status: 400 }
    );
  }

  const parsedKey = parseReportStorageKey(query.data.key);
  if (!parsedKey) {
    return NextResponse.json({ error: "Invalid report key format" }, { status: 400 });
  }

  try {
    const env = getSupabaseEnv();
    const report = await downloadStorageJson(env.SUPABASE_REPORTS_BUCKET, parsedKey.key);
    return NextResponse.json({ key: parsedKey.key, report });
  } catch (error) {
    if (error instanceof SupabaseApiError && error.status === 404) {
      return NextResponse.json({ error: "Report not found" }, { status: 404 });
    }

    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
