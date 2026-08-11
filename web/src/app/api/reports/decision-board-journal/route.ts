import { NextRequest } from "next/server";

import { enforceAdminApiGuard } from "@/lib/admin-api-guard";
import { readDecisionBoardJournalStatus } from "@/lib/decision-board-journal.server";
import { jsonWithNoStore } from "@/lib/reports-response";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const guardError = await enforceAdminApiGuard(request, jsonWithNoStore);
  if (guardError) {
    return guardError;
  }

  try {
    return jsonWithNoStore(await readDecisionBoardJournalStatus());
  } catch {
    return jsonWithNoStore(
      { error: "Local journal status unavailable" },
      { status: 500 },
    );
  }
}
